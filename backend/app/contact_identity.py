"""Deterministic contact identity normalization; never infer identity from body text."""

from __future__ import annotations

import email.utils
from dataclasses import dataclass

try:
    import phonenumbers
except ImportError:  # Keep non-phone API/test collection usable in minimal environments.
    phonenumbers = None


@dataclass(frozen=True)
class ContactIdentity:
    raw: str | None
    normalized: str | None
    state: str
    kind: str | None


def normalize_email(value: str | None) -> ContactIdentity:
    if value is None or not value.strip():
        return ContactIdentity(value, None, "needs_manual_review", None)
    raw = value
    text = value.strip()
    _, address = email.utils.parseaddr(text)
    if not address or "@" not in address or any(ch.isspace() for ch in address):
        return ContactIdentity(raw, None, "needs_manual_review", "email")
    local, domain = address.rsplit("@", 1)
    if not local or not domain or "." not in domain:
        return ContactIdentity(raw, None, "needs_manual_review", "email")
    # No plus-tag removal, dot folding, alias expansion or shared mailbox merge.
    return ContactIdentity(raw, f"{local}@{domain}".casefold(), "certain", "email")


def normalize_whatsapp(value: str | None) -> ContactIdentity:
    if value is None or not value.strip():
        return ContactIdentity(value, None, "needs_manual_review", None)
    raw = value
    jid = value.strip()
    if "@" in jid:
        user, host = jid.rsplit("@", 1)
        if host.casefold() != "s.whatsapp.net":
            return ContactIdentity(raw, None, "unsupported", "whatsapp")
        candidate = user.split(":", 1)[0]
        # A JID is accepted only when it embeds a complete international number.
        # Never infer a country code from locale or surrounding message content.
        candidate = f"+{candidate}" if candidate.isdigit() else candidate
    else:
        candidate = jid
    if phonenumbers is None:
        # Keep the provider's international JID usable when the optional
        # parser is unavailable, without ever guessing a country code.
        if not candidate.startswith("+"):
            return ContactIdentity(raw, None, "needs_manual_review", "whatsapp")
        digits = "".join(ch for ch in candidate[1:] if ch.isdigit())
        if not digits.isdigit() or not 8 <= len(digits) <= 15:
            return ContactIdentity(raw, None, "needs_manual_review", "whatsapp")
        return ContactIdentity(raw, f"+{digits}", "certain", "whatsapp")
    try:
        parsed = phonenumbers.parse(candidate, None)
    except phonenumbers.NumberParseException:
        return ContactIdentity(raw, None, "needs_manual_review", "whatsapp")
    if not phonenumbers.is_possible_number(parsed) or not phonenumbers.is_valid_number(parsed):
        return ContactIdentity(raw, None, "needs_manual_review", "whatsapp")
    normalized = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    return ContactIdentity(raw, normalized, "certain", "whatsapp")
