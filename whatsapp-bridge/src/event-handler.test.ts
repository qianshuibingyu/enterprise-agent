import assert from "node:assert/strict";
import test from "node:test";
import { captureWhatsAppBatch } from "./event-handler.js";
import type { InboundRecord } from "./durable-inbox.js";

function message(id: string, fromMe = false): any {
  return { key: { remoteJid: "chat", participant: "sender", id, fromMe }, message: { conversation: "fixture" }, messageTimestamp: 1_762_120_000 };
}

function context() {
  const records = new Map<string, InboundRecord>();
  const metrics = { upsertEvents: 0, notifyMessages: 0, appendMessages: 0, queued: 0, pendingDurableEvents: 0, missingAccountId: 0, missingMessageId: 0 };
  let drained = 0;
  const capture = (externalAccountId: string | undefined, messages: any[], type: string) => captureWhatsAppBatch({
    externalAccountId,
    inbox: {
      enqueue: async (record) => { if (records.has(record.eventId)) return false; records.set(record.eventId, record); return true; },
      pending: () => [...records.values()],
    },
    metrics,
    setError: () => undefined,
    drain: async () => { drained += 1; },
    now: () => "2026-11-03T00:00:00.000Z",
  }, messages, type);
  return { records, metrics, get drained() { return drained; }, capture };
}

test("notify and append share the durable handler and duplicate IDs are local-idempotent", async () => {
  const fixture = context();
  await fixture.capture("account-1", [message("one")], "notify");
  await fixture.capture("account-1", [message("one")], "append");
  assert.equal(fixture.metrics.notifyMessages, 1);
  assert.equal(fixture.metrics.appendMessages, 1);
  assert.equal(fixture.metrics.queued, 1);
  assert.equal(fixture.records.size, 1);
  assert.equal(fixture.drained, 2);
});

test("other upsert types, fromMe, missing identity, and missing message IDs are rejected", async () => {
  const fixture = context();
  await fixture.capture("account-1", [message("ignored")], "replace");
  await fixture.capture("account-1", [message("self", true)], "notify");
  await fixture.capture(undefined, [message("no-account")], "append");
  await fixture.capture("account-1", [{ key: { remoteJid: "chat", id: "" } } as any], "append");
  assert.equal(fixture.records.size, 0);
  assert.equal(fixture.metrics.missingAccountId, 1);
  assert.equal(fixture.metrics.missingMessageId, 1);
});
