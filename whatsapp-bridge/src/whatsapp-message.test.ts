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

test("normalization only exposes a verified personal phone as customer contact", () => {
  const personal = normalizeWhatsAppMessage({
    key: { remoteJid: "8613812345678@s.whatsapp.net", id: "message-1" },
    message: { conversation: "hello" },
  } as any, "account-1", "notify");
  const group = normalizeWhatsAppMessage({
    key: { remoteJid: "12345-67890@g.us", participant: "8613812345678@s.whatsapp.net", id: "message-2" },
    message: { conversation: "hello" },
  } as any, "account-1", "notify");
  const lid = normalizeWhatsAppMessage({
    key: { remoteJid: "123456789@lid", id: "message-3" },
    message: { conversation: "hello" },
  } as any, "account-1", "notify");

  assert.equal(personal?.customerContact, "8613812345678");
  assert.equal(group?.customerContact, undefined);
  assert.equal(lid?.customerContact, undefined);
});

test("LID direct chats resolve to the paired phone so the console can open the chat", () => {
  const fromAlt = normalizeWhatsAppMessage({
    key: {
      remoteJid: "123456789@lid",
      remoteJidAlt: "8613812345678:12@s.whatsapp.net",
      id: "message-4",
    },
    message: { conversation: "hello" },
  } as any, "account-1", "notify");
  // The LID mapping store answers asynchronously and is passed in by callers.
  const fromMapping = normalizeWhatsAppMessage({
    key: { remoteJid: "987654321@lid", id: "message-5" },
    message: { conversation: "hello" },
  } as any, "account-1", "notify", undefined, "8613900000000");
  // A group keeps no phone contact even when the sender PN is known.
  const groupWithAlt = normalizeWhatsAppMessage({
    key: {
      remoteJid: "120363410510354466@g.us",
      participant: "52695339638929@lid",
      participantAlt: "8613812345678@s.whatsapp.net",
      id: "message-6",
    },
    message: { conversation: "hello" },
  } as any, "account-1", "notify");

  assert.equal(fromAlt?.customerContact, "8613812345678");
  assert.equal(fromMapping?.customerContact, "8613900000000");
  assert.equal(groupWithAlt?.customerContact, undefined);
  // The provider-scoped identity still contains the LID JID.
  assert.equal(fromAlt?.externalMessageId, "123456789@lid::message-4");
});

test("an unusable LID mapping value is ignored", () => {
  const record = normalizeWhatsAppMessage({
    key: { remoteJid: "987654321@lid", id: "message-7" },
    message: { conversation: "hello" },
  } as any, "account-1", "notify", undefined, "not-a-phone");

  assert.equal(record?.customerContact, undefined);
});
