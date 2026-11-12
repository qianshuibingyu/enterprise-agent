import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import { chmod, mkdir, open, readFile, rename, unlink } from "node:fs/promises";
import path from "node:path";

export type InboundRecord = {
  eventId: string;
  eventType: "notify" | "append";
  receivedAt: string;
  externalAccountId: string;
  externalMessageId: string;
  occurredAt: string;
  rawContent: string;
  customerContact?: string;
  customerNickname?: string;
};

type StoredRecord =
  | { kind: "queued"; record: InboundRecord }
  | { kind: "delivered"; eventId: string };

type EncryptedLine = { iv: string; tag: string; data: string };

const COMPACTION_RECORD_THRESHOLD = 64;

function encryptionKey(value: string): Buffer {
  const key = Buffer.from(value, "base64");
  if (key.length !== 32) {
    throw new Error("WHATSAPP_INBOX_ENCRYPTION_KEY must encode 32 random bytes");
  }
  return key;
}

function encrypt(value: StoredRecord, key: Buffer): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const data = Buffer.concat([cipher.update(JSON.stringify(value), "utf8"), cipher.final()]);
  const line: EncryptedLine = {
    iv: iv.toString("base64"),
    tag: cipher.getAuthTag().toString("base64"),
    data: data.toString("base64"),
  };
  return JSON.stringify(line);
}

function decrypt(line: string, key: Buffer): StoredRecord {
  const encrypted = JSON.parse(line) as EncryptedLine;
  const decipher = createDecipheriv("aes-256-gcm", key, Buffer.from(encrypted.iv, "base64"));
  decipher.setAuthTag(Buffer.from(encrypted.tag, "base64"));
  const plaintext = Buffer.concat([
    decipher.update(Buffer.from(encrypted.data, "base64")),
    decipher.final(),
  ]).toString("utf8");
  return JSON.parse(plaintext) as StoredRecord;
}

export class DurableInbox {
  private readonly key: Buffer;
  private readonly filePath: string;
  private readonly records = new Map<string, InboundRecord>();
  private readonly delivered = new Set<string>();
  private writeChain: Promise<void> = Promise.resolve();
  private appendCount = 0;

  private constructor(filePath: string, key: Buffer) {
    this.filePath = filePath;
    this.key = key;
  }

  static async open(filePath: string, keyValue: string): Promise<DurableInbox> {
    const inbox = new DurableInbox(filePath, encryptionKey(keyValue));
    await mkdir(path.dirname(filePath), { recursive: true, mode: 0o700 });
    await chmod(path.dirname(filePath), 0o700);
    try {
      const content = await readFile(filePath, "utf8");
      await chmod(filePath, 0o600);
      for (const line of content.split("\n")) {
        if (!line) continue;
        const record = decrypt(line, inbox.key);
        if (record.kind === "queued") inbox.records.set(record.record.eventId, record.record);
        else inbox.delivered.add(record.eventId);
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        throw new Error("WhatsApp durable inbox cannot be opened or decrypted");
      }
    }
    return inbox;
  }

  enqueue(record: InboundRecord): Promise<boolean> {
    let created = false;
    return this.append(() => {
      if (this.records.has(record.eventId) || this.delivered.has(record.eventId)) return undefined;
      created = true;
      return { kind: "queued", record };
    }).then(() => created);
  }

  markDelivered(eventId: string): Promise<void> {
    return this.append(() => {
      if (this.delivered.has(eventId)) return undefined;
      return { kind: "delivered", eventId };
    });
  }

  pending(): InboundRecord[] {
    return [...this.records.values()].filter((record) => !this.delivered.has(record.eventId));
  }

  get size(): number {
    return this.records.size;
  }

  private append(recordFactory: () => StoredRecord | undefined): Promise<void> {
    const operation = this.writeChain.then(async () => {
      const record = recordFactory();
      if (!record) return;
      const file = await open(this.filePath, "a", 0o600);
      try {
        await file.write(`${encrypt(record, this.key)}\n`);
        await file.sync();
      } finally {
        await file.close();
      }
      if (record.kind === "queued") this.records.set(record.record.eventId, record.record);
      else this.delivered.add(record.eventId);
      this.appendCount += 1;
      if (this.appendCount >= COMPACTION_RECORD_THRESHOLD) await this.compactLocked();
    });
    this.writeChain = operation.catch(() => undefined);
    return operation;
  }

  private async compactLocked(): Promise<void> {
    const temporaryPath = `${this.filePath}.tmp-${process.pid}-${Date.now()}`;
    const keepDelivered = [...this.delivered].slice(-COMPACTION_RECORD_THRESHOLD);
    const lines = [
      ...this.pending().map((record) => encrypt({ kind: "queued", record }, this.key)),
      ...keepDelivered.map((eventId) => encrypt({ kind: "delivered", eventId }, this.key)),
    ];
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
      this.delivered.clear();
      for (const eventId of keepDelivered) this.delivered.add(eventId);
      this.appendCount = 0;
    } catch (error) {
      await unlink(temporaryPath).catch(() => undefined);
      throw error;
    }
  }
}
