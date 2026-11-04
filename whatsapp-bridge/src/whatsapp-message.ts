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

export function normalizeWhatsAppMessage(
  message: WAMessage,
  externalAccountId: string | undefined,
  eventType: "notify" | "append",
  now = new Date().toISOString(),
): InboundRecord | undefined {
  const messageId = message.key?.id;
  if (!externalAccountId || !messageId) return undefined;
  const externalMessageId = whatsappExternalMessageId({
    remoteJid: message.key?.remoteJid,
    participant: message.key?.participant,
    messageId,
  });
  return {
    eventId: externalMessageId,
    eventType,
    receivedAt: now,
    externalAccountId,
    externalMessageId,
    occurredAt: messageTimestamp(message),
    rawContent: messageContent(message),
  };
}
