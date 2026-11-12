import type { WAMessage } from "baileys";
import type { InboundRecord, DurableInbox } from "./durable-inbox.js";
import { isLidJid, normalizeWhatsAppMessage } from "./whatsapp-message.js";

export type CaptureMetrics = {
  upsertEvents: number;
  notifyMessages: number;
  appendMessages: number;
  queued: number;
  pendingDurableEvents: number;
  missingAccountId: number;
  missingMessageId: number;
  lastEventAt?: string;
  lastCaptureAt?: string;
};

export type CaptureContext = {
  externalAccountId?: string;
  inbox: Pick<DurableInbox, "enqueue" | "pending">;
  metrics: CaptureMetrics;
  setError: (message: string) => void;
  drain: () => Promise<void>;
  now?: () => string;
  /**
   * Resolve the phone number behind a LID chat. WhatsApp increasingly delivers
   * direct chats under `<id>@lid`, which is not a phone number, so the console
   * could not build a chat deep link for those messages.
   */
  resolvePhone?: (lidJid: string) => Promise<string | undefined>;
};

async function resolvedPhone(context: CaptureContext, message: WAMessage): Promise<string | undefined> {
  const remoteJid = message.key?.remoteJid;
  if (!context.resolvePhone || !isLidJid(remoteJid)) return undefined;
  try {
    return await context.resolvePhone(remoteJid as string);
  } catch {
    // A missing mapping must never block message capture.
    return undefined;
  }
}

export async function captureWhatsAppBatch(
  context: CaptureContext,
  messages: WAMessage[],
  type: string,
): Promise<void> {
  if (type !== "notify" && type !== "append") return;
  const eventType = type;
  const now = context.now ?? (() => new Date().toISOString());
  context.metrics.upsertEvents += 1;
  if (type === "notify") context.metrics.notifyMessages += messages.length;
  else context.metrics.appendMessages += messages.length;
  context.metrics.lastEventAt = now();

  for (const message of messages) {
    if (message.key?.fromMe) continue;
    const record = normalizeWhatsAppMessage(
      message,
      context.externalAccountId,
      eventType,
      undefined,
      await resolvedPhone(context, message),
    );
    if (!record) {
      if (!context.externalAccountId) context.metrics.missingAccountId += 1;
      if (!message.key?.id) context.metrics.missingMessageId += 1;
      context.setError("WhatsApp account or message identity is unavailable");
      continue;
    }
    if (await context.inbox.enqueue(record)) context.metrics.queued += 1;
    context.metrics.pendingDurableEvents = context.inbox.pending().length;
  }
  context.metrics.lastCaptureAt = now();
  await context.drain();
}
