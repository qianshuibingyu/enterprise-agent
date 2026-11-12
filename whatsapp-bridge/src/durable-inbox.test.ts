import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { randomBytes } from "node:crypto";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { DurableInbox, type InboundRecord } from "./durable-inbox.js";

function record(eventId: string): InboundRecord {
  return {
    eventId,
    eventType: "append",
    receivedAt: "2026-11-03T00:00:00.000Z",
    externalAccountId: "fixture-account",
    externalMessageId: `fixture-message-${eventId}`,
    occurredAt: "2026-11-02T23:59:00.000Z",
    rawContent: "FIXTURE_ONLY private message body",
  };
}

test("durable inbox encrypts queued records and restores pending events after restart", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "wa-inbox-test-"));
  const file = path.join(directory, "inbox.events");
  const key = randomBytes(32).toString("base64");
  try {
    const inbox = await DurableInbox.open(file, key);
    assert.equal(await inbox.enqueue(record("event-1")), true);
    assert.equal(await inbox.enqueue(record("event-1")), false);

    const disk = await readFile(file, "utf8");
    assert.equal(disk.includes("FIXTURE_ONLY private message body"), false);

    const restored = await DurableInbox.open(file, key);
    assert.deepEqual(restored.pending(), [record("event-1")]);
    await restored.markDelivered("event-1");

    const afterDelivery = await DurableInbox.open(file, key);
    assert.deepEqual(afterDelivery.pending(), []);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("durable inbox fails closed with invalid key or tampered ciphertext", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "wa-inbox-invalid-"));
  const file = path.join(directory, "inbox.events");
  const key = randomBytes(32).toString("base64");
  try {
    await assert.rejects(DurableInbox.open(file, "invalid-key"));
    const inbox = await DurableInbox.open(file, key);
    await inbox.enqueue(record("event-2"));
    await (await import("node:fs/promises")).writeFile(file, "tampered\n");
    await assert.rejects(DurableInbox.open(file, key), /cannot be opened or decrypted/);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("durable inbox compacts delivered history while retaining pending and dedupe tombstones", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "wa-inbox-compact-"));
  const file = path.join(directory, "inbox.events");
  const key = randomBytes(32).toString("base64");
  try {
    const inbox = await DurableInbox.open(file, key);
    for (let index = 0; index < 64; index += 1) {
      const eventId = `delivered-${index}`;
      assert.equal(await inbox.enqueue(record(eventId)), true);
      await inbox.markDelivered(eventId);
    }
    assert.equal(await inbox.enqueue(record("pending")), true);
    const restored = await DurableInbox.open(file, key);
    assert.equal(restored.pending().length, 1);
    assert.equal(restored.pending()[0].eventId, "pending");
    assert.equal(await restored.enqueue(record("delivered-63")), false);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
