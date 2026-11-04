import assert from "node:assert/strict";
import test from "node:test";
import { normalizeWhatsAppMessage, whatsappExternalMessageId } from "./whatsapp-message.js";

test("WhatsApp message IDs are scoped by chat and participant", () => {
  assert.notEqual(
    whatsappExternalMessageId({ remoteJid: "chat-a", participant: "user", messageId: "same" }),
    whatsappExternalMessageId({ remoteJid: "chat-b", participant: "user", messageId: "same" }),
  );
  assert.notEqual(
    whatsappExternalMessageId({ remoteJid: "group", participant: "user-a", messageId: "same" }),
    whatsappExternalMessageId({ remoteJid: "group", participant: "user-b", messageId: "same" }),
  );
  assert.equal(
    whatsappExternalMessageId({ remoteJid: "group", participant: "user", messageId: "same" }),
    whatsappExternalMessageId({ remoteJid: "group", participant: "user", messageId: "same" }),
  );
  assert.throws(() => whatsappExternalMessageId({ remoteJid: "group", participant: "user", messageId: "" }));
});

test("normalization accepts notify and append without logging provider payloads", () => {
  const message = {
    key: { remoteJid: "group", participant: "sender", id: "message-1", fromMe: false },
    messageTimestamp: 1_762_120_000,
    message: { conversation: "fixture message" },
  } as any;
  const record = normalizeWhatsAppMessage(message, "account-1", "append", "2026-11-03T00:00:00.000Z");
  assert.equal(record?.eventId, "group:sender:message-1");
  assert.equal(record?.eventType, "append");
  assert.equal(record?.rawContent, "fixture message");
  assert.equal(normalizeWhatsAppMessage(message, undefined, "notify"), undefined);
  assert.equal(normalizeWhatsAppMessage({ key: { id: "" } } as any, "account-1", "notify"), undefined);
});
