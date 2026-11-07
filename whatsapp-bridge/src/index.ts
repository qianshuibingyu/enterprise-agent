import express, { type Request, type Response } from "express";
import { mkdir, readdir, rm } from "node:fs/promises";
import path from "node:path";
import makeWASocket, { DisconnectReason, useMultiFileAuthState, type WAMessage } from "baileys";
import QRCode from "qrcode";
import { DurableInbox, type InboundRecord } from "./durable-inbox.js";
import { captureWhatsAppBatch } from "./event-handler.js";
import { createMessageCache, externalMessageIdForMessage, type MessageCache } from "./message-cache.js";
import { phoneFromWhatsAppJid, isLidJid, messageContent } from "./whatsapp-message.js";

type Metrics = {
  socketConnected: boolean;
  upsertEvents: number;
  notifyMessages: number;
  appendMessages: number;
  queued: number;
  forwarded: number;
  pendingDurableEvents: number;
  backendFailures: number;
  missingAccountId: number;
  missingMessageId: number;
  lastCaptureAt?: string;
  lastEventAt?: string;
  lastForwardAt?: string;
  recoveryWindowStart?: string;
  recoveryWindowEnd?: string;
};

type RuntimeState = {
  channelAccountId: number;
  state: any;
  saveCreds: () => Promise<void>;
  socket?: ReturnType<typeof makeWASocket>;
  connectionState: string;
  qrDataUrl?: string;
  qrExpiresAt?: string;
  externalAccountId?: string;
  error?: string;
  metrics: Metrics;
  inbox: DurableInbox;
  retryTimer?: NodeJS.Timeout;
  retryDelayMs: number;
  reconnectTimer?: NodeJS.Timeout;
  reconnectDelayMs: number;
  inFlight: Set<string>;
  generation: number;
  messageCache: MessageCache;
};

const PORT = Number(process.env.PORT ?? "8090");
const BACKEND_URL = (process.env.BACKEND_URL ?? "http://backend:8000").replace(/\/$/, "");
const ADAPTER_TOKEN = process.env.WHATSAPP_ADAPTER_TOKEN ?? "";
const AUTH_ROOT = process.env.WHATSAPP_AUTH_ROOT ?? "/var/lib/whatsapp-auth";
const INBOX_ROOT = process.env.WHATSAPP_INBOX_ROOT ?? "/var/lib/whatsapp-inbox";
const INBOX_KEY = process.env.WHATSAPP_INBOX_ENCRYPTION_KEY ?? "";
const QR_TTL_MS = 5 * 60_000;
const MAX_RETRY_MS = 5 * 60_000;

if (!ADAPTER_TOKEN) throw new Error("WHATSAPP_ADAPTER_TOKEN is required");
if (!INBOX_KEY) throw new Error("WHATSAPP_INBOX_ENCRYPTION_KEY is required");

const runtimes = new Map<number, RuntimeState>();

function requireToken(request: Request, response: Response): boolean {
  if (request.header("authorization") !== `Bearer ${ADAPTER_TOKEN}`) {
    response.status(403).json({ detail: "adapter authorization failed" });
    return false;
  }
  return true;
}

function accountId(request: Request): number {
  const value = Number(request.params.channelAccountId);
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error("invalid channel account id");
  return value;
}

function externalId(state: any): string | undefined {
  const id = state?.creds?.me?.id;
  return typeof id === "string" && id.length > 0 ? id : undefined;
}

function parseExternalMessageId(value: string): { remoteJid: string; participant?: string; messageId: string } {
  const messageSeparator = value.lastIndexOf(":");
  const participantSeparator = value.lastIndexOf(":", messageSeparator - 1);
  if (messageSeparator <= 0 || participantSeparator < 0) throw new Error("invalid WhatsApp message identity");
  const remoteJid = value.slice(0, participantSeparator);
  const participant = value.slice(participantSeparator + 1, messageSeparator);
  const messageId = value.slice(messageSeparator + 1);
  if (!remoteJid || !messageId) throw new Error("invalid WhatsApp message identity");
  return { remoteJid, participant: participant || undefined, messageId };
}

function serializedProviderMessage(message: WAMessage) {
  return {
    external_message_id: externalMessageIdForMessage(message),
    raw_content: messageContent(message),
    customer_contact: phoneFromWhatsAppJid(message.key?.remoteJid) ?? null,
    customer_nickname: typeof message.pushName === "string" ? message.pushName : null,
  };
}

async function fetchProviderMessage(runtime: RuntimeState, externalMessageId: string): Promise<WAMessage> {
  const cached = runtime.messageCache.get(externalMessageId);
  if (cached) return cached;
  const socket = runtime.socket as any;
  if (!socket?.loadMessages) throw new Error("WhatsApp message history is unavailable");
  const identity = parseExternalMessageId(externalMessageId);
  // Baileys point queries are best-effort: try both fromMe variants before
  // giving up, since the stored identity does not record the sender flag.
  for (const fromMe of [false, true]) {
    const messages = await socket.loadMessages(
      identity.remoteJid,
      1,
      {
        key: {
          remoteJid: identity.remoteJid,
          id: identity.messageId,
          fromMe,
          ...(identity.participant ? { participant: identity.participant } : {}),
        },
        messageTimestamp: 0,
      },
    );
    const match = (messages as WAMessage[]).find(
      (message) => externalMessageIdForMessage(message) === externalMessageId,
    );
    if (match) return match;
  }
  throw new Error("WhatsApp message was not found");
}

async function deliver(runtime: RuntimeState, record: InboundRecord): Promise<void> {
  const response = await fetch(
    `${BACKEND_URL}/api/integrations/whatsapp/accounts/${runtime.channelAccountId}/inbound`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "X-WhatsApp-Adapter-Token": ADAPTER_TOKEN,
      },
      body: JSON.stringify({
        external_account_id: record.externalAccountId,
        external_message_id: record.externalMessageId,
        direction: "inbound",
        status: "received",
        occurred_at: record.occurredAt,
        raw_content: record.rawContent,
        customer_contact: record.customerContact,
        customer_nickname: record.customerNickname,
        attachments: [],
      }),
      signal: AbortSignal.timeout(15_000),
    },
  );
  if (!response.ok) throw new Error(`backend inbound rejected with HTTP ${response.status}`);
  await runtime.inbox.markDelivered(record.eventId);
  runtime.metrics.forwarded += 1;
  runtime.metrics.lastForwardAt = new Date().toISOString();
  runtime.metrics.pendingDurableEvents = runtime.inbox.pending().length;
  if (!runtime.metrics.pendingDurableEvents) runtime.metrics.recoveryWindowEnd = new Date().toISOString();
  runtime.retryDelayMs = 1_000;
  runtime.error = undefined;
}

async function drainPending(runtime: RuntimeState): Promise<void> {
  for (const record of runtime.inbox.pending()) {
    if (runtime.inFlight.has(record.eventId)) continue;
    runtime.inFlight.add(record.eventId);
    try {
      await deliver(runtime, record);
    } catch (error) {
      runtime.metrics.backendFailures += 1;
      runtime.error = error instanceof Error ? error.message : "backend inbound delivery failed";
      runtime.retryTimer ??= setTimeout(() => {
        runtime.retryTimer = undefined;
        runtime.retryDelayMs = Math.min(runtime.retryDelayMs * 2, MAX_RETRY_MS);
        void drainPending(runtime);
      }, runtime.retryDelayMs);
      runtime.retryTimer.unref();
      return;
    } finally {
      runtime.inFlight.delete(record.eventId);
    }
  }
}

async function captureBatch(runtime: RuntimeState, messages: WAMessage[], type: string): Promise<void> {
  await captureWhatsAppBatch(
    {
      externalAccountId: runtime.externalAccountId ?? externalId(runtime.state),
      inbox: runtime.inbox,
      metrics: runtime.metrics,
      setError: (message) => { runtime.error = message; },
      drain: () => drainPending(runtime),
      resolvePhone: async (lidJid) => {
        const mapping = (runtime.socket as any)?.signalRepository?.lidMapping;
        if (!mapping?.getPNForLID) return undefined;
        return phoneFromWhatsAppJid(await mapping.getPNForLID(lidJid));
      },
    },
    messages,
    type,
  );
}

function startSocket(runtime: RuntimeState): void {
  const generation = ++runtime.generation;
  const socket = makeWASocket({
    auth: runtime.state,
    syncFullHistory: true,
    shouldSyncHistoryMessage: () => true,
    emitOwnEvents: false,
    markOnlineOnConnect: false,
    fireInitQueries: true,
  } as any);
  runtime.socket = socket;
  socket.ev.on("creds.update", runtime.saveCreds);
  socket.ev.on("messages.upsert", ({ messages, type }) => {
    runtime.messageCache.remember(messages);
    void captureBatch(runtime, messages, type).catch((error) => {
      runtime.error = error instanceof Error ? error.message : "WhatsApp event capture failed";
    });
  });
  socket.ev.on("connection.update", (update) => {
    if (generation !== runtime.generation) return;
    if (update.qr) {
      void QRCode.toDataURL(update.qr, { errorCorrectionLevel: "M" }).then((url) => {
        if (generation !== runtime.generation) return;
        runtime.qrDataUrl = url;
        runtime.qrExpiresAt = new Date(Date.now() + QR_TTL_MS).toISOString();
        runtime.connectionState = "awaiting_authorization";
        setTimeout(() => {
          if (runtime.qrExpiresAt && Date.parse(runtime.qrExpiresAt) <= Date.now()) {
            runtime.qrDataUrl = undefined;
            runtime.qrExpiresAt = undefined;
          }
        }, QR_TTL_MS).unref();
      }).catch(() => {
        runtime.connectionState = "system_error";
        runtime.error = "WhatsApp QR rendering failed";
      });
    }
    if (update.connection === "open") {
      runtime.metrics.socketConnected = true;
      runtime.externalAccountId = externalId(runtime.state);
      runtime.connectionState = runtime.externalAccountId ? "connected" : "connected_pending_inbound";
      runtime.qrDataUrl = undefined;
      runtime.qrExpiresAt = undefined;
      runtime.metrics.recoveryWindowEnd = new Date().toISOString();
      runtime.metrics.recoveryWindowStart ??= runtime.metrics.lastEventAt;
      runtime.reconnectDelayMs = 1_000;
      void drainPending(runtime);
    }
    if (update.connection === "close") {
      runtime.metrics.socketConnected = false;
      const code = (update.lastDisconnect?.error as any)?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) {
        runtime.connectionState = "revoked";
        return;
      }
      runtime.connectionState = "disconnected";
      runtime.metrics.recoveryWindowStart ??= runtime.metrics.lastEventAt ?? new Date().toISOString();
      if (!runtime.reconnectTimer) {
        runtime.reconnectTimer = setTimeout(() => {
          runtime.reconnectTimer = undefined;
          runtime.reconnectDelayMs = Math.min(runtime.reconnectDelayMs * 2, MAX_RETRY_MS);
          startSocket(runtime);
        }, runtime.reconnectDelayMs);
        runtime.reconnectTimer.unref();
      }
    }
  });
}

async function createRuntime(channelAccountId: number): Promise<RuntimeState> {
  const authPath = path.join(AUTH_ROOT, String(channelAccountId));
  const inboxPath = path.join(INBOX_ROOT, `${channelAccountId}.events`);
  await mkdir(authPath, { recursive: true, mode: 0o700 });
  const auth = await useMultiFileAuthState(authPath);
  const inbox = await DurableInbox.open(inboxPath, INBOX_KEY);
  const pending = inbox.pending();
  const runtime: RuntimeState = {
    channelAccountId,
    state: auth.state,
    saveCreds: auth.saveCreds,
    connectionState: "starting",
    metrics: {
      socketConnected: false,
      upsertEvents: 0,
      notifyMessages: 0,
      appendMessages: 0,
      queued: 0,
      forwarded: 0,
      pendingDurableEvents: pending.length,
      backendFailures: 0,
      missingAccountId: 0,
      missingMessageId: 0,
      recoveryWindowStart: pending[0]?.receivedAt,
      recoveryWindowEnd: pending.length ? new Date().toISOString() : undefined,
    },
    inbox,
    retryDelayMs: 1_000,
    reconnectDelayMs: 1_000,
    inFlight: new Set(),
    generation: 0,
    messageCache: createMessageCache(),
  };
  startSocket(runtime);
  void drainPending(runtime);
  return runtime;
}

async function getRuntime(channelAccountId: number): Promise<RuntimeState> {
  const existing = runtimes.get(channelAccountId);
  if (existing) return existing;
  const runtime = await createRuntime(channelAccountId);
  runtimes.set(channelAccountId, runtime);
  return runtime;
}

async function resetRuntime(channelAccountId: number): Promise<RuntimeState> {
  const current = runtimes.get(channelAccountId);
  if (current) {
    if (current.retryTimer) clearTimeout(current.retryTimer);
    if (current.reconnectTimer) clearTimeout(current.reconnectTimer);
    current.generation += 1;
    current.socket?.end(undefined);
  }
  runtimes.delete(channelAccountId);
  // Pairing is non-destructive. Reuse a valid linked-device session and only
  // create a fresh QR when Baileys reports an unregistered/logged-out session.
  return getRuntime(channelAccountId);
}

async function startKnownAccounts(): Promise<void> {
  try {
    const entries = await readdir(AUTH_ROOT, { withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isDirectory() || !/^\d+$/.test(entry.name)) continue;
      try {
        await getRuntime(Number(entry.name));
      } catch (error) {
        console.error("WhatsApp account restore failed", error instanceof Error ? error.message : "unknown error");
      }
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
}

const app = express();
app.use(express.json({ limit: "256kb" }));

app.post("/internal/whatsapp/accounts/:channelAccountId/pair", async (request, response) => {
  if (!requireToken(request, response)) return;
  try {
    const runtime = await resetRuntime(accountId(request));
    const deadline = Date.now() + 15_000;
    while (!runtime.qrDataUrl && !runtime.metrics.socketConnected && !runtime.error && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (runtime.error) {
      response.status(503).json({ detail: "WhatsApp pairing could not start" });
      return;
    }
    if (runtime.metrics.socketConnected) {
      response.json({ qr: "", expires_at: "", state: runtime.connectionState, test_only: false });
      return;
    }
    if (!runtime.qrDataUrl) {
      response.status(503).json({ detail: "WhatsApp pairing timed out waiting for QR" });
      return;
    }
    response.json({ qr: runtime.qrDataUrl, expires_at: runtime.qrExpiresAt ?? "", state: runtime.connectionState, test_only: false });
  } catch (error) {
    console.error("WhatsApp pairing unavailable", error instanceof Error ? error.message : "unknown error");
    response.status(503).json({ detail: "WhatsApp pairing unavailable" });
  }
});

app.get("/internal/whatsapp/accounts/:channelAccountId/status", async (request, response) => {
  if (!requireToken(request, response)) return;
  try {
    const runtime = await getRuntime(accountId(request));
    response.json({
      state: runtime.connectionState,
      qr: runtime.qrDataUrl ?? "",
      expires_at: runtime.qrExpiresAt ?? "",
      external_account_id: runtime.externalAccountId ?? externalId(runtime.state) ?? null,
      detail: runtime.error ?? null,
    });
  } catch (error) {
    console.error("WhatsApp status unavailable", error instanceof Error ? error.message : "unknown error");
    response.status(503).json({ detail: "WhatsApp status unavailable" });
  }
});

app.get("/internal/whatsapp/accounts/:channelAccountId/metrics", async (request, response) => {
  if (!requireToken(request, response)) return;
  try {
    const runtime = await getRuntime(accountId(request));
    runtime.metrics.pendingDurableEvents = runtime.inbox.pending().length;
    response.json({
      state: runtime.connectionState,
      metrics: runtime.metrics,
      last_error: runtime.error ?? null,
      history_sync_complete: false,
      note: "Reports only events actually delivered by WhatsApp; provider omissions cannot be inferred.",
    });
  } catch {
    response.status(503).json({ detail: "WhatsApp metrics unavailable" });
  }
});

app.post("/internal/whatsapp/accounts/:channelAccountId/disconnect", async (request, response) => {
  if (!requireToken(request, response)) return;
  try {
    const runtime = await getRuntime(accountId(request));
    runtime.connectionState = "revoked";
    runtime.generation += 1;
    runtime.socket?.end(undefined);
    await rm(path.join(AUTH_ROOT, String(runtime.channelAccountId)), { recursive: true, force: true });
    // Keep the encrypted inbox so any captured-but-undelivered messages survive disconnect.
    response.json({ state: runtime.connectionState, external_account_id: runtime.externalAccountId ?? null, detail: null });
  } catch {
    response.status(503).json({ detail: "WhatsApp disconnect unavailable" });
  }
});

app.get("/internal/whatsapp/accounts/:channelAccountId/messages/:messageId", async (request, response) => {
  if (!requireToken(request, response)) return;
  try {
    const runtime = await getRuntime(accountId(request));
    // Cached messages are served even when the session is down: the content
    // contract only needs a consistent, sanitized snapshot, not a live socket.
    const cached = runtime.messageCache.get(request.params.messageId);
    if (cached) {
      response.json(serializedProviderMessage(cached));
      return;
    }
    if (!runtime.metrics.socketConnected) {
      response.status(503).json({ detail: "WhatsApp session is not connected" });
      return;
    }
    const message = await fetchProviderMessage(runtime, request.params.messageId);
    runtime.messageCache.remember([message]);
    response.json(serializedProviderMessage(message));
  } catch (error) {
    response.status(502).json({ detail: error instanceof Error ? error.message : "WhatsApp message fetch failed" });
  }
});
app.post("/internal/whatsapp/accounts/:channelAccountId/lid-phone", async (request, response) => {
  if (!requireToken(request, response)) return;
  const lid = typeof request.body?.lid === "string" ? request.body.lid.trim() : "";
  if (!isLidJid(lid)) {
    response.status(400).json({ detail: "lid is not a WhatsApp LID JID" });
    return;
  }
  try {
    const runtime = await getRuntime(accountId(request));
    const mapping = (runtime.socket as any)?.signalRepository?.lidMapping;
    const pn = mapping?.getPNForLID ? await mapping.getPNForLID(lid) : null;
    // Only a phone number can address a chat; an unresolved LID stays null so
    // the console keeps the WhatsApp root instead of opening a stranger.
    response.json({ lid, phone: phoneFromWhatsAppJid(pn) ?? null });
  } catch {
    response.status(503).json({ detail: "WhatsApp LID mapping unavailable" });
  }
});

app.get("/healthz", (_request, response) => response.json({ status: "ok" }));
void startKnownAccounts().catch(() => undefined);
app.listen(PORT, "0.0.0.0", () => console.log(`WhatsApp bridge listening on ${PORT}`));
