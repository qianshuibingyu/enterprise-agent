import type { WAMessage } from "baileys";
import type { InboundRecord } from "./durable-inbox.js";

export const WHATSAPP_PROVIDER = "whatsapp_web_baileys";

/**
 * Stable marker for "delete for everyone". The backend turns it into the
 * Chinese revocation note; it must never be shown to an operator as-is.
 */
export const WHATSAPP_REVOKED_MARKER = "[WhatsApp message revoked]";

/**
 * WhatsApp delivers 双端删除/撤回 as a *protocol stub*, not as a message with
 * an empty body. Baileys exposes it either through `messageStubType=REVOKE` or
 * through `protocolMessage.type=REVOKE` (proto enum value 0). Older bridge
 * builds stored `[empty WhatsApp message]` for those stubs and the console
 * then filed them as "消息内容为空 / 意图不明 / 待处理".
 */
/** WebMessageInfo.StubType.REVOKE = 1 (UNKNOWN = 0); ProtocolMessage.Type.REVOKE = 0. */
const REVOKE_STUB_NUMBER = 1;

export function isRevokedWhatsAppMessage(message: WAMessage): boolean {
  const body = message.message as any;
  // A payload that actually carries customer text is never a revoke stub.
  // WhatsApp can attach stale stub/protocol fields to a re-delivered message;
  // classifying those as 撤回 would hide an original that is plainly readable.
  if (
    body?.conversation ||
    body?.extendedTextMessage?.text ||
    body?.imageMessage?.caption ||
    body?.videoMessage?.caption ||
    body?.documentMessage?.caption ||
    body?.templateMessage?.hydratedTemplate?.hydratedContentText
  ) {
    return false;
  }
  const rawStub = (message as any).messageStubType;
  const stub = String(rawStub ?? "").toUpperCase();
  // `stub.includes("DELETE")` used to match GROUP_DELETE / other group stubs
  // and mislabelled ordinary chats as revocations. Only REVOKE counts.
  if (stub === "REVOKE" || rawStub === REVOKE_STUB_NUMBER) return true;
  const protocol = body?.protocolMessage;
  if (!protocol) return false;
  const type = protocol.type;
  return type === 0 || String(type ?? "").toUpperCase() === "REVOKE";
}

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
  // Detect the revoke stub before looking at the body: protocol messages have
  // no `message` payload at all, so the empty-body branch would swallow them.
  if (isRevokedWhatsAppMessage(message)) return WHATSAPP_REVOKED_MARKER;
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
