import type { WAMessage } from "baileys";
import type { InboundRecord } from "./durable-inbox.js";

export const WHATSAPP_PROVIDER = "whatsapp_web_baileys";

export function whatsappExternalMessageId({
  remoteJid,
  participant,
  messageId,
}: {
  remoteJid?: string | null;
  participant?: string | null;
  messageId: string;
}): string {
  if (!messageId) throw new Error("WhatsApp message ID is required");
  return `${remoteJid || "unknown"}:${participant || ""}:${messageId}`;
}

export function messageTimestamp(message: WAMessage): string {
  const raw = message.messageTimestamp as unknown as { toNumber?: () => number } | number | string | undefined;
  const seconds = typeof raw === "number" ? raw : typeof raw === "string" ? Number(raw) : raw?.toNumber?.() ?? 0;
  return Number.isFinite(seconds) && seconds > 0
    ? new Date(seconds * 1000).toISOString()
    : new Date().toISOString();
}

export function messageContent(message: WAMessage): string {
  const body = message.message;
  if (!body) return "[empty WhatsApp message]";
  return String(
    body.conversation ??
    body.extendedTextMessage?.text ??
    body.imageMessage?.caption ??
    body.videoMessage?.caption ??
    body.documentMessage?.caption ??
    body.templateMessage?.hydratedTemplate?.hydratedContentText ??
    "[non-text WhatsApp message]",
  );
}

/**
 * Extract a personal phone number from a WhatsApp JID.
 *
 * Only `<phone>@s.whatsapp.net` addresses a chat. Group JIDs (`@g.us`) and
 * privacy-linked ids (`@lid`) are not phone numbers, so they are rejected
 * instead of being misused as a deep-link target.
 */
export function phoneFromWhatsAppJid(jid: string | null | undefined): string | undefined {
  const candidate = (jid ?? "").trim();
  if (!candidate.endsWith("@s.whatsapp.net")) return undefined;
  const user = candidate.slice(0, -"@s.whatsapp.net".length).split(":")[0];
  return /^\d{6,15}$/.test(user) ? user : undefined;
}

/**
 * Resolve the phone a chat can be opened with.
 *
 * Modern WhatsApp delivers direct chats under a LID (`<id>@lid`) and keeps the
 * phone number in the paired `remoteJidAlt` field, or makes it reachable
 * through the LID mapping store. Without this fallback every LID message had an
 * empty customer contact, so the console could only open the WhatsApp root
 * instead of the conversation.
 */
export function customerPhoneForKey(
  key: {
    remoteJid?: string | null;
    remoteJidAlt?: string | null;
    participantAlt?: string | null;
  } | null | undefined,
  resolvedPhone?: string,
): string | undefined {
  const remoteJid = key?.remoteJid ?? "";
  if (remoteJid.endsWith("@g.us")) {
    // A group conversation cannot be addressed by a phone number.
    return undefined;
  }
  const direct = phoneFromWhatsAppJid(remoteJid);
  if (direct) return direct;
  const alt = phoneFromWhatsAppJid(key?.remoteJidAlt) ?? phoneFromWhatsAppJid(key?.participantAlt);
  if (alt) return alt;
  return /^\d{6,15}$/.test(resolvedPhone ?? "") ? resolvedPhone : undefined;
}

export function isLidJid(jid: string | null | undefined): boolean {
  return (jid ?? "").trim().endsWith("@lid");
}

export function normalizeWhatsAppMessage(
  message: WAMessage,
  externalAccountId: string | undefined,
  eventType: "notify" | "append",
  now = new Date().toISOString(),
  resolvedPhone?: string,
): InboundRecord | undefined {
  const messageId = message.key?.id;
  if (!externalAccountId || !messageId) return undefined;
  const externalMessageId = whatsappExternalMessageId({
    remoteJid: message.key?.remoteJid,
    participant: message.key?.participant,
    messageId,
  });
  // LID and group JIDs are not phone numbers and cannot be safely converted
  // into a WhatsApp Desktop deep link. Preserve the JID in externalMessageId
  // while only exposing an actual number as customerContact.
  const customerContact = customerPhoneForKey(message.key, resolvedPhone);
  return {
    eventId: externalMessageId,
    eventType,
    receivedAt: now,
    externalAccountId,
    externalMessageId,
    occurredAt: messageTimestamp(message),
    rawContent: messageContent(message),
    customerContact,
    customerNickname: typeof message.pushName === "string" ? message.pushName : undefined,
  };
}
