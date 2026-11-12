import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import { chmod, mkdir, open, readFile, rename, unlink } from "node:fs/promises";
import path from "node:path";

/** A persisted, sanitized snapshot of one provider message, keyed by external id. */
export type ArchivedMessage = {
  external_message_id: string;
  raw_content: string;
  customer_contact: string | null;
  customer_nickname: string | null;
  archived_at: string;
};

type EncryptedLine = { iv: string; tag: string; data: string };

const MAX_ENTRIES = 20_000;
const COMPACTION_WRITE_THRESHOLD = 500;

function encryptionKey(value: string): Buffer {
  const key = Buffer.from(value, "base64");
  if (key.length !== 32) {
    throw new Error("WHATSAPP_INBOX_ENCRYPTION_KEY must encode 32 random bytes");
  }
  return key;
}

function encrypt(record: ArchivedMessage, key: Buffer): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const data = Buffer.concat([cipher.update(JSON.stringify(record), "utf8"), cipher.final()]);
  const line: EncryptedLine = {
    iv: iv.toString("base64"),
    tag: cipher.getAuthTag().toString("base64"),
    data: data.toString("base64"),
  };
  return JSON.stringify(line);
}

function decrypt(line: string, key: Buffer): ArchivedMessage {
  const encrypted = JSON.parse(line) as EncryptedLine;
  const decipher = createDecipheriv("aes-256-gcm", key, Buffer.from(encrypted.iv, "base64"));
  decipher.setAuthTag(Buffer.from(encrypted.tag, "base64"));
  const plaintext = Buffer.concat([
    decipher.update(Buffer.from(encrypted.data, "base64")),
    decipher.final(),
  ]).toString("utf8");
  return JSON.parse(plaintext) as ArchivedMessage;
}

/**
 * Durable provider-message snapshots for the original-content refetch path.
 *
 * The in-memory MessageCache is an LRU that disappears on restart, and the
 * DurableInbox deliberately drops message bodies once they are delivered to the
 * backend. Without this archive a historical message can only be refetched
 * through Baileys `loadMessages`, which is best-effort and unavailable while the
 * session is offline. Persisting the sanitized snapshot here makes the refetch
 * chain reproducible across restarts and disconnects.
 */
export class MessageArchive {
  private readonly key: Buffer;
  private readonly filePath: string;
  private readonly entries = new Map<string, ArchivedMessage>();
  private writeChain: Promise<void> = Promise.resolve();
  private writesSinceCompaction = 0;

  private constructor(filePath: string, key: Buffer) {
    this.filePath = filePath;
    this.key = key;
  }

  static async open(filePath: string, keyValue: string): Promise<MessageArchive> {
    const archive = new MessageArchive(filePath, encryptionKey(keyValue));
    await mkdir(path.dirname(filePath), { recursive: true, mode: 0o700 });
    await chmod(path.dirname(filePath), 0o700);
    try {
      const content = await readFile(filePath, "utf8");
      await chmod(filePath, 0o600);
      for (const line of content.split("\n")) {
        if (!line) continue;
        const record = decrypt(line, archive.key);
        if (record.external_message_id) {
          // Later lines win: a re-captured message replaces the earlier snapshot.
          archive.entries.set(record.external_message_id, record);
        }
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        throw new Error("WhatsApp message archive cannot be opened or decrypted");
      }
    }
    return archive;
  }

  get(externalMessageId: string): ArchivedMessage | undefined {
    return this.entries.get(externalMessageId);
  }

  get size(): number {
    return this.entries.size;
  }

  remember(records: readonly ArchivedMessage[]): Promise<void> {
    const operation = this.writeChain.then(async () => {
      const fresh = records.filter((record) =>
        Boolean(record.external_message_id)
        && this.entries.get(record.external_message_id)?.raw_content !== record.raw_content,
      );
      if (!fresh.length) return;
      const file = await open(this.filePath, "a", 0o600);
      try {
        await file.write(`${fresh.map((record) => encrypt(record, this.key)).join("\n")}\n`);
        await file.sync();
      } finally {
        await file.close();
      }
      for (const record of fresh) {
        this.entries.delete(record.external_message_id);
        this.entries.set(record.external_message_id, record);
      }
      while (this.entries.size > MAX_ENTRIES) {
        const oldest = this.entries.keys().next().value;
        if (oldest === undefined) break;
        this.entries.delete(oldest);
      }
      this.writesSinceCompaction += 1;
      if (this.writesSinceCompaction >= COMPACTION_WRITE_THRESHOLD) await this.compactLocked();
    });
    this.writeChain = operation.catch(() => undefined);
    return operation;
  }

  private async compactLocked(): Promise<void> {
    const temporaryPath = `${this.filePath}.tmp-${process.pid}-${Date.now()}`;
    const lines = [...this.entries.values()].map((record) => encrypt(record, this.key));
    try {
      const file = await open(temporaryPath, "w", 0o600);
      try {
        if (lines.length) await file.write(`${lines.join("\n")}\n`);
        await file.sync();
      } finally {
        await file.close();
      }
      await chmod(temporaryPath, 0o600);
      await rename(temporaryPath, this.filePath);
      const directory = await open(path.dirname(this.filePath), "r");
      try {
        try {
          await directory.sync();
        } catch (error) {
          const code = (error as NodeJS.ErrnoException).code;
          if (code !== "EPERM" && code !== "ENOTSUP") throw error;
        }
      } finally {
        await directory.close();
      }
      this.writesSinceCompaction = 0;
    } catch (error) {
      await unlink(temporaryPath).catch(() => undefined);
      throw error;
    }
  }
}
