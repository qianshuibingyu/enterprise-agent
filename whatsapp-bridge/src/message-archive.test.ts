import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { MessageArchive, type ArchivedMessage } from "./message-archive.js";

function record(id: string, content: string): ArchivedMessage {
  return {
    external_message_id: id,
    raw_content: content,
    customer_contact: "+16502530000",
    customer_nickname: "fixture sender",
    archived_at: "2026-11-10T00:00:00.000Z",
  };
}

test("message archive survives a restart and never stores plaintext bodies", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "wa-archive-test-"));
  const file = path.join(directory, "account.messages");
  const key = randomBytes(32).toString("base64");
  try {
    const archive = await MessageArchive.open(file, key);
    await archive.remember([record("jid::id-1", "PRIVATE provider body"), record("jid::id-2", "second body")]);
    assert.equal(archive.size, 2);

    const onDisk = await readFile(file, "utf8");
    assert.ok(!onDisk.includes("PRIVATE provider body"));
    assert.ok(onDisk.includes("iv"));

    const restored = await MessageArchive.open(file, key);
    assert.equal(restored.get("jid::id-1")?.raw_content, "PRIVATE provider body");
    assert.equal(restored.get("jid::id-2")?.customer_nickname, "fixture sender");
    assert.equal(restored.get("missing"), undefined);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("re-archiving identical content is a no-op and re-captured content wins", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "wa-archive-test-"));
  const file = path.join(directory, "account.messages");
  const key = randomBytes(32).toString("base64");
  try {
    const archive = await MessageArchive.open(file, key);
    await archive.remember([record("id-1", "original")]);
    const afterFirst = await readFile(file, "utf8");
    await archive.remember([record("id-1", "original")]);
    assert.equal(await readFile(file, "utf8"), afterFirst);

    await archive.remember([record("id-1", "updated")]);
    assert.equal(archive.get("id-1")?.raw_content, "updated");
    const restored = await MessageArchive.open(file, key);
    assert.equal(restored.get("id-1")?.raw_content, "updated");
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("archive refuses to open with the wrong encryption key", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "wa-archive-test-"));
  const file = path.join(directory, "account.messages");
  try {
    const archive = await MessageArchive.open(file, randomBytes(32).toString("base64"));
    await archive.remember([record("id-1", "body")]);
    await assert.rejects(
      MessageArchive.open(file, randomBytes(32).toString("base64")),
      /cannot be opened or decrypted/,
    );
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
