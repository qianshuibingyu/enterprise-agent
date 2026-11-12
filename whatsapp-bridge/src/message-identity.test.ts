import assert from "node:assert/strict";
import test from "node:test";
import { parseExternalMessageId } from "./message-identity.js";
import { externalMessageIdForMessage } from "./message-cache.js";
import type { WAMessage } from "baileys";

test("parses the cache's empty-participant remoteJid::id identity", () => {
  const parsed = parseExternalMessageId("8613800000000@s.whatsapp.net::ABC");
  assert.deepEqual(parsed, {
    remoteJid: "8613800000000@s.whatsapp.net",
    participant: undefined,
    messageId: "ABC",
  });

  const cachedId = externalMessageIdForMessage({
    key: { remoteJid: parsed.remoteJid, id: parsed.messageId },
  } as unknown as WAMessage);
  assert.equal(cachedId, "8613800000000@s.whatsapp.net::ABC");
});

test("parses a non-empty participant identity without losing JID colons", () => {
  assert.deepEqual(
    parseExternalMessageId("120363000000000000@g.us:8613800000000@s.whatsapp.net:MSG-1"),
    {
      remoteJid: "120363000000000000@g.us",
      participant: "8613800000000@s.whatsapp.net",
      messageId: "MSG-1",
    },
  );
});

test("rejects malformed or incomplete WhatsApp message identities", () => {
  for (const value of ["", "chat", ":id", "chat::", "chat:participant:"]) {
    assert.throws(() => parseExternalMessageId(value), /invalid WhatsApp message identity/);
  }
});
