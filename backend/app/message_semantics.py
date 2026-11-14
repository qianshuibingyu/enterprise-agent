"""Semantics for provider-controlled body placeholders.

WhatsApp delivers "delete for everyone" (双端删除 / 撤回) as a protocol stub
with no message body. Older bridge builds stored the literal
``[empty WhatsApp message]`` for those stubs. That is *not* an empty customer
message: it is a revocation. Business APIs must say so instead of letting the
UI describe the row as "消息内容为空 / 意图不明" and queue it for manual
processing.

The module also owns the single place where "cleaned safe original text" is
produced for list and detail views, so the customer chain can lead with the
operator's sanitized body rather than the AI summary.
"""

from __future__ import annotations

from typing import Any

from app.content_security import content_view, full_content_view

CONTENT_STATE_READY = "ready"
CONTENT_STATE_REVOKED = "revoked"
CONTENT_STATE_HIDDEN = "hidden"

REVOKED_DISPLAY_TEXT = "客户已撤回（双端删除）这条消息，原文不再可用。"

# Stable, provider-written placeholders. Matching is exact (after trim/case
# folding) so a customer who legitimately quotes a bracketed phrase in a longer
# message is never mistaken for a revoked one.
_REVOKED_MARKERS = frozenset(
    {
        "[empty whatsapp message]",
        "[whatsapp message revoked]",
        "[whatsapp message deleted for everyone]",
        "[whatsapp 消息已撤回]",
    }
)

# Provider-written "we captured no text" placeholders. They are NOT proof of a
# revocation: WhatsApp can deliver a bodyless stub first and the real message
# for the same id a moment later, while the ingest row keeps the stub snapshot.
# Only when no real body can be recovered do we keep calling it 已撤回.
_EMPTY_MARKERS = frozenset(
    {
        "[non-text whatsapp message]",
    }
)

# Inline chain display is a preview; the "查看客户消息" dialog carries the full
# sanitized body. Bounding it keeps list responses small.
INLINE_SAFE_TEXT_LIMIT = 1600


def is_revoked_content(raw_content: Any) -> bool:
    """True when the stored body is a delete-for-everyone / revoke placeholder."""
    text = "" if raw_content is None else str(raw_content)
    return text.strip().casefold() in _REVOKED_MARKERS


def is_provider_placeholder(raw_content: Any) -> bool:
    """True for a provider-written stub marker (or a genuinely blank body).

    A bracketed phrase inside a longer customer message is not a placeholder:
    this check is exact after trim/case folding, just like ``is_revoked_content``.
    """
    text = ("" if raw_content is None else str(raw_content)).strip().casefold()
    return not text or text in _REVOKED_MARKERS or text in _EMPTY_MARKERS


def is_recoverable_body(raw_content: Any) -> bool:
    """True when the provider supplied an actual customer body."""
    return not is_provider_placeholder(raw_content)


def needs_body_repair(stored_content: Any, candidate_content: Any) -> bool:
    """A real provider body must replace a stale stub snapshot.

    撤回 means "原文不可恢复". If the bridge can still return the customer's
    words, the row was never a revocation — it was a bad first capture.
    Persisting the recovered body keeps list, chain and dialog views consistent.
    """
    return is_provider_placeholder(stored_content) and is_recoverable_body(candidate_content)


def content_state(raw_content: Any) -> str:
    return CONTENT_STATE_REVOKED if is_revoked_content(raw_content) else CONTENT_STATE_READY


def safe_content_view(raw_content: Any, *, full: bool = False) -> dict[str, object]:
    """Sanitized text view plus an explicit content state.

    A revoked message has no recoverable body. Its display text is replaced
    with a human-readable revocation note so no UI ever shows the raw English
    placeholder as if it were the customer's own words.
    """
    view = dict(full_content_view(raw_content) if full else content_view(raw_content))
    if is_revoked_content(raw_content):
        view["display_text"] = REVOKED_DISPLAY_TEXT
        view["display_excerpt"] = REVOKED_DISPLAY_TEXT
        view["content_truncated"] = False
        view["content_state"] = CONTENT_STATE_REVOKED
    else:
        view["content_state"] = CONTENT_STATE_READY
    return view


def inline_safe_text(raw_content: Any, *, limit: int = INLINE_SAFE_TEXT_LIMIT) -> tuple[str | None, bool]:
    """Return the bounded sanitized body used as the primary chain text."""
    text = str(safe_content_view(raw_content)["display_text"])
    if not text:
        return None, False
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip() + "…", True


__all__ = [
    "CONTENT_STATE_READY",
    "CONTENT_STATE_REVOKED",
    "CONTENT_STATE_HIDDEN",
    "REVOKED_DISPLAY_TEXT",
    "content_state",
    "inline_safe_text",
    "is_provider_placeholder",
    "is_recoverable_body",
    "is_revoked_content",
    "needs_body_repair",
    "safe_content_view",
]
