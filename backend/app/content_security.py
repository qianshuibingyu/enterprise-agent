"""Safe presentation helpers for provider-controlled message content.

Provider payloads are business data, not trusted markup.  The API therefore
returns text/plain display fields and never exposes raw HTML to the frontend.
"""

from __future__ import annotations

from html.parser import HTMLParser
import re
from typing import Any


# Keep enough text for the detail view while bounding the amount of untrusted
# provider data returned in every list/detail response.
MAX_DISPLAY_TEXT = 12_000
MAX_DISPLAY_EXCERPT = 280

_DANGEROUS_TAGS = frozenset(
    {"script", "style", "iframe", "frame", "object", "embed", "form", "svg", "math"}
)
_BLOCK_TAGS = frozenset({"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"})
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")


class _TextExtractor(HTMLParser):
    """Extract visible text while ignoring active and embedded HTML content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _DANGEROUS_TAGS:
            self._ignored_depth += 1
        elif not self._ignored_depth and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self._ignored_depth and tag.lower() in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _DANGEROUS_TAGS:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif not self._ignored_depth and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)

    def handle_comment(self, data: str) -> None:
        return


def _plain_text(value: Any) -> str:
    source = "" if value is None else str(value)
    parser = _TextExtractor()
    try:
        parser.feed(source)
        parser.close()
        text = "".join(parser.parts)
    except Exception:
        # Malformed MIME/HTML must not make an otherwise valid message unreadable.
        text = re.sub(r"<[^>]*>", " ", source)
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n[ \t]*", "\n", text)
    return text.strip()


def content_view(value: Any) -> dict[str, object]:
    """Return the bounded, text-only representation used by business APIs."""
    text = _plain_text(value)
    truncated = len(text) > MAX_DISPLAY_TEXT
    display_text = text[:MAX_DISPLAY_TEXT].rstrip()
    excerpt = display_text[:MAX_DISPLAY_EXCERPT].rstrip()
    if len(display_text) > MAX_DISPLAY_EXCERPT:
        excerpt = display_text[: max(0, MAX_DISPLAY_EXCERPT - 1)].rstrip() + "…"
    return {
        "display_text": display_text,
        "display_excerpt": excerpt,
        "content_format": "text/plain",
        "content_sanitized": True,
        "content_truncated": truncated,
    }


def full_content_view(value: Any) -> dict[str, object]:
    """Return the complete sanitized text for the original-content view.

    List endpoints use ``content_view`` to bound untrusted provider data. The
    detail view must instead be able to show the whole ingest snapshot, so this
    renderer keeps text/plain output without applying MAX_DISPLAY_TEXT.
    """
    text = _plain_text(value)
    excerpt = text[:MAX_DISPLAY_EXCERPT].rstrip()
    if len(text) > MAX_DISPLAY_EXCERPT:
        excerpt = text[: max(0, MAX_DISPLAY_EXCERPT - 1)].rstrip() + "…"
    return {
        "display_text": text,
        "display_excerpt": excerpt,
        "content_format": "text/plain",
        "content_sanitized": True,
        "content_truncated": False,
    }


def legacy_contact_view(raw_content: Any, provider: str | None) -> tuple[str | None, str | None]:
    """Best-effort contact recovery for rows created before contact columns.

    Only an email address found in a legacy provider header is considered a
    contact.  Message bodies are deliberately not interpreted as identities.
    """
    if not provider or not str(provider).lower().startswith(("gmail", "outlook")):
        return None, None
    source = "" if raw_content is None else str(raw_content)
    header = re.search(r"(?im)^\s*(?:from|sender)\s*:\s*(.+)$", source)
    candidate = header.group(1) if header else ""
    match = _EMAIL_RE.search(candidate)
    if not match:
        return None, None
    contact = match.group(0)
    nickname = candidate[: match.start()].strip().strip('"<')
    nickname = re.sub(r"\s+", " ", nickname).strip(" ,:;\"") or None
    return contact, nickname


__all__ = ["content_view", "legacy_contact_view"]
