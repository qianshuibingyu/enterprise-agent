import type { WAMessage } from "baileys";

export type MessageCache = {
  remember: (messages: readonly WAMessage[] | undefined) => void;
  get: (externalMessageId: string) => WAMessage | undefined;
  size: () => number;
};

const DEFAULT_CAPACITY = 2000;

export function externalMessageIdForMessage(message: WAMessage): string | undefined {
  const id = message.key?.id;
  if (!id) return undefined;
  return `${message.key?.remoteJid || "unknown"}:${message.key?.participant || ""}:${id}`;
}

export function createMessageCache(capacity: number = DEFAULT_CAPACITY): MessageCache {
  const entries = new Map<string, WAMessage>();
  return {
    remember(messages) {
      for (const message of messages ?? []) {
        const id = externalMessageIdForMessage(message);
        if (!id) continue;
        if (entries.has(id)) {
          entries.delete(id);
        } else if (entries.size >= capacity) {
          const oldest = entries.keys().next().value;
          if (oldest !== undefined) entries.delete(oldest);
        }
        entries.set(id, message);
      }
    },
    get(externalMessageId) {
      if (!externalMessageId) return undefined;
      return entries.get(externalMessageId);
    },
    size: () => entries.size,
  };
}
