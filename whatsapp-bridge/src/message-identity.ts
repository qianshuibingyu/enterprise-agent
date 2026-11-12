export type ParsedExternalMessageId = {
  remoteJid: string;
  participant?: string;
  messageId: string;
};

/** Parse the canonical remoteJid:participant:id identity, including empty participant remoteJid::id. */
export function parseExternalMessageId(value: string): ParsedExternalMessageId {
  const messageSeparator = value.lastIndexOf(":");
  if (messageSeparator <= 0) throw new Error("invalid WhatsApp message identity");
  const prefix = value.slice(0, messageSeparator);
  const messageId = value.slice(messageSeparator + 1);
  if (!messageId) throw new Error("invalid WhatsApp message identity");
  const participantSeparator = prefix.lastIndexOf(":");
  if (participantSeparator < 0) throw new Error("invalid WhatsApp message identity");
  const remoteJid = prefix.slice(0, participantSeparator);
  const participant = prefix.slice(participantSeparator + 1) || undefined;
  if (!remoteJid) throw new Error("invalid WhatsApp message identity");
  return { remoteJid, participant, messageId };
}
