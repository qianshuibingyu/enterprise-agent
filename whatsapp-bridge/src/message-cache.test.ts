import test from "node:test";
import assert from "node:assert/strict";
import type { WAMessage } from "baileys";
import { createMessageCache, externalMessageIdForMessage } from "./message-cache.js";

function message(id: string, body: string, remoteJid = "8613800000000@s.whatsapp.net"): WAMessage {
  return { key: { remoteJid, id }, message: { conversation: body } } as unknown as WAMessage;
}

test("externalMessageIdForMessage composes chat:participant:id", () => {
  assert.equal(externalMessageIdForMessage(message("ABC", "hi")), "8613800000000@s.whatsapp.net::ABC");
  assert.equal(externalMessageIdForMessage(message("ABC", "hi", "120363@g.us")), "120363@g.us::ABC");
  assert.equal(externalMessageIdForMessage({ key: {} } as unknown as WAMessage), undefined);
});

test("cache stores and retrieves messages by external id", () => {
  const cache = createMessageCache();
  cache.remember([message("m1", "first"), message("m2", "second")]);
  assert.equal(cache.get("8613800000000@s.whatsapp.net::m1")?.message?.conversation, "first");
  assert.equal(cache.get("8613800000000@s.whatsapp.net::m2")?.message?.conversation, "second");
  assert.equal(cache.get("8613800000000@s.whatsapp.net::missing"), undefined);
  assert.equal(cache.get(""), undefined);
});

test("cache evicts oldest entries beyond capacity", () => {
  const cache = createMessageCache(2);
  cache.remember([message("m1", "one"), message("m2", "two")]);
  cache.remember([message("m3", "three")]);
  assert.equal(cache.get("8613800000000@s.whatsapp.net::m1"), undefined);
  assert.ok(cache.get("8613800000000@s.whatsapp.net::m2"));
  assert.ok(cache.get("8613800000000@s.whatsapp.net::m3"));
  assert.equal(cache.size(), 2);
});

test("cache refreshes insertion order on duplicates and ignores id-less messages", () => {
  const cache = createMessageCache(2);
  cache.remember([message("m1", "one"), message("m2", "two")]);
  cache.remember([message("m1", "one-updated")]);
  cache.remember([message("", "no id")]);
  assert.equal(cache.size(), 2);
  cache.remember([message("m3", "three")]);
  assert.equal(cache.get("8613800000000@s.whatsapp.net::m2"), undefined);
  assert.equal(cache.get("8613800000000@s.whatsapp.net::m1")?.message?.conversation, "one-updated");
});

test("cache tolerates undefined batches", () => {
  const cache = createMessageCache();
  cache.remember(undefined);
  assert.equal(cache.size(), 0);
});
