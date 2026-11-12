"""Provider-neutral, in-memory document cleaning and deterministic chunking.

This module does not upload, persist, authorize, embed, or retrieve documents.
Callers must perform access control before passing a document here.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
import re
import unicodedata
from typing import Any, Literal


DocumentFormat = Literal["text/plain", "text/markdown", "text/html"]
DocumentSourceType = Literal["product", "public"]
MAX_CHUNK_CHARS = 1_200
CHUNK_OVERLAP_CHARS = 100
MAX_DOCUMENT_CHARS = 1_000_000
MAX_TITLE_CHARS = 512
CLEANING_VERSION = "text-clean-v1"
CHUNKING_VERSION = "paragraph-1200-overlap-100-v1"


class DocumentProcessingError(ValueError):
    """Input is unsupported, invalid, or exceeds the processing limit."""


@dataclass(frozen=True)
class DocumentInput:
    document_id: str
    title: str
    source_type: DocumentSourceType
    format: DocumentFormat
    content: str
    # Opaque authorization metadata assigned by the caller after authorization.
    visibility_scope: str
    reply_eligible: bool
    uploader_id: int
    test_only: bool = False


@dataclass(frozen=True)
class KnowledgeChunk:
    document_id: str
    document_title: str
    document_version: str
    content_hash: str
    chunk_index: int
    chunk_text: str
    chunk_hash: str
    source_locator: dict[str, Any]
    source_type: DocumentSourceType
    visibility_scope: str
    reply_eligible: bool
    uploader_id: int
    cleaning_version: str
    chunking_version: str
    test_only: bool


@dataclass(frozen=True)
class _Block:
    text: str
    block_index: int
    heading_path: tuple[str, ...]
    kind: str


_DANGEROUS_TAGS = frozenset(
    {"script", "style", "iframe", "frame", "object", "embed", "form", "svg", "math", "template"}
)
_BLOCK_TAGS = frozenset(
    {"address", "article", "blockquote", "br", "dd", "div", "dl", "dt", "figcaption", "h1", "h2", "h3", "h4", "h5", "h6", "li", "ol", "p", "pre", "section", "table", "td", "th", "tr", "ul"}
)
_MD_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_MD_LIST = re.compile(r"^\s{0,3}(?:[-+*]|\d+[.)])\s+(.*)$")
_MD_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_INLINE_CODE = re.compile(r"`+([^`]+)`+")
_MD_EMPHASIS = re.compile(r"(?<!\\)[*_~]{1,3}([^*_~]+)[*_~]{1,3}")


def _remove_controls(text: str) -> str:
    return "".join(
        character
        for character in text
        if character in "\n\t" or unicodedata.category(character) not in {"Cc", "Cf", "Cs"}
    )


def _normalize_block(text: str) -> str:
    text = _remove_controls(text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


class _MarkdownHTMLSanitizer(HTMLParser):
    """Remove HTML tags and active subtrees before Markdown tokenization."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignore_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.lower()
        if tag in _DANGEROUS_TAGS:
            self.ignore_depth += 1
        elif not self.ignore_depth and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _DANGEROUS_TAGS:
            self.ignore_depth = max(0, self.ignore_depth - 1)
        elif not self.ignore_depth and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignore_depth:
            self.parts.append(data)


def _sanitize_markdown_html(source: str) -> str:
    parser = _MarkdownHTMLSanitizer()
    try:
        parser.feed(source)
        parser.close()
    except Exception as exc:
        raise DocumentProcessingError("Markdown HTML sanitization failed") from exc
    return "".join(parser.parts)


class _HTMLBlockExtractor(HTMLParser):
    """Extract text blocks while discarding active/embedded HTML subtrees."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[_Block] = []
        self.current: list[str] = []
        self.current_kind = "text"
        self.ignore_depth = 0
        self.heading_stack: list[tuple[int, str]] = []

    def _flush(self) -> None:
        text = _normalize_block("".join(self.current))
        self.current = []
        if not text:
            return
        if self.current_kind.startswith("h") and self.current_kind[1:].isdigit():
            level = int(self.current_kind[1:])
            self.heading_stack = [(depth, heading) for depth, heading in self.heading_stack if depth < level]
            self.heading_stack.append((level, text))
            path = tuple(heading for _, heading in self.heading_stack)
        else:
            path = tuple(heading for _, heading in self.heading_stack)
        self.blocks.append(_Block(text, len(self.blocks), path, self.current_kind))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.lower()
        if tag in _DANGEROUS_TAGS:
            self._flush()
            self.ignore_depth += 1
            return
        if self.ignore_depth:
            return
        if tag in _BLOCK_TAGS:
            self._flush()
            self.current_kind = tag

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _DANGEROUS_TAGS:
            self.ignore_depth = max(0, self.ignore_depth - 1)
            return
        if self.ignore_depth:
            return
        if tag in _BLOCK_TAGS:
            self._flush()
            self.current_kind = "text"

    def handle_data(self, data: str) -> None:
        if not self.ignore_depth:
            self.current.append(data)

    def handle_comment(self, data: str) -> None:
        del data

    def finish(self) -> list[_Block]:
        self.close()
        self._flush()
        return self.blocks


def _html_blocks(source: str) -> list[_Block]:
    parser = _HTMLBlockExtractor()
    try:
        parser.feed(source)
        return parser.finish()
    except Exception as exc:  # malformed HTML fails closed; no raw markup fallback
        raise DocumentProcessingError("HTML parsing failed") from exc


def _plain_or_markdown_blocks(source: str, *, markdown: bool) -> list[_Block]:
    source = _remove_controls(source).replace("\r\n", "\n").replace("\r", "\n")
    if markdown:
        source = _sanitize_markdown_html(source)
    if not markdown:
        paragraphs = re.split(r"\n\s*\n+", source)
        return [
            _Block(cleaned, index, (), "paragraph")
            for index, item in enumerate(paragraphs)
            if (cleaned := _normalize_block(item))
        ]

    blocks: list[_Block] = []
    heading_stack: list[tuple[int, str]] = []
    paragraph: list[str] = []
    fence_marker: str | None = None

    def flush(kind: str = "paragraph") -> None:
        if not paragraph:
            return
        text = _normalize_block("\n".join(paragraph))
        paragraph.clear()
        if text:
            blocks.append(_Block(text, len(blocks), tuple(h for _, h in heading_stack), kind))

    for line in source.split("\n"):
        stripped = line.lstrip()
        if fence_marker is not None:
            if stripped.startswith(fence_marker):
                fence_marker = None
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            flush()
            fence_marker = stripped[:3]
            continue
        if not line.strip():
            flush()
            continue
        heading = _MD_HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            title = _normalize_block(heading.group(2))
            heading_stack = [(depth, value) for depth, value in heading_stack if depth < level]
            if title:
                heading_stack.append((level, title))
                blocks.append(_Block(title, len(blocks), tuple(h for _, h in heading_stack), "heading"))
            continue
        list_item = _MD_LIST.match(line)
        quote = _MD_QUOTE.match(line)
        if list_item or quote:
            flush()
            line = list_item.group(1) if list_item else quote.group(1)
            paragraph.append(line)
            flush("list_item" if list_item else "quote")
            continue
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            flush()
            continue
        line = _MD_IMAGE.sub(r"\1", line)
        line = _MD_LINK.sub(r"\1", line)
        line = _MD_INLINE_CODE.sub(r"\1", line)
        line = _MD_EMPHASIS.sub(r"\1", line)
        paragraph.append(line)
    flush()
    return blocks


def _parse_blocks(document: DocumentInput) -> list[_Block]:
    if not isinstance(document.content, str):
        raise DocumentProcessingError("content must be a string")
    if not document.content.strip():
        raise DocumentProcessingError("document is empty")
    if len(document.content) > MAX_DOCUMENT_CHARS:
        raise DocumentProcessingError("document exceeds input limit")
    if document.format == "text/html":
        return _html_blocks(document.content)
    if document.format == "text/markdown":
        return _plain_or_markdown_blocks(document.content, markdown=True)
    if document.format == "text/plain":
        return _plain_or_markdown_blocks(document.content, markdown=False)
    raise DocumentProcessingError("unsupported document format")


def _split_long_block(block: _Block) -> list[tuple[str, int, int]]:
    text = block.text
    if len(text) <= MAX_CHUNK_CHARS:
        return [(text, 0, len(text))]
    result: list[tuple[str, int, int]] = []
    start = 0
    while start < len(text):
        end = min(start + MAX_CHUNK_CHARS, len(text))
        piece = text[start:end].strip()
        if piece:
            leading = len(text[start:end]) - len(text[start:end].lstrip())
            result.append((piece, start + leading, start + leading + len(piece)))
        if end == len(text):
            break
        start = max(start + 1, end - CHUNK_OVERLAP_CHARS)
    return result


def process_document(document: DocumentInput) -> list[KnowledgeChunk]:
    """Clean and deterministically chunk one pre-authorized text document.

    Only current first-batch source kinds (product/public) and UTF-8-decoded
    plain text, Markdown, and HTML are accepted. The caller owns upload auth,
    persistence, ACL enforcement, deletion, and revocation behavior.
    """
    if not isinstance(document.document_id, str) or not document.document_id.strip():
        raise DocumentProcessingError("document_id is required")
    if not isinstance(document.title, str) or not document.title.strip() or len(document.title) > MAX_TITLE_CHARS:
        raise DocumentProcessingError("document title is invalid")
    if document.source_type not in {"product", "public"}:
        raise DocumentProcessingError("document source type is not enabled")
    if not isinstance(document.visibility_scope, str) or not document.visibility_scope.strip():
        raise DocumentProcessingError("authorized visibility scope is required")
    if type(document.reply_eligible) is not bool or type(document.test_only) is not bool:
        raise DocumentProcessingError("reply_eligible and test_only must be booleans")
    if not isinstance(document.uploader_id, int) or document.uploader_id <= 0:
        raise DocumentProcessingError("authorized uploader id is required")

    blocks = _parse_blocks(document)
    canonical = "\n\n".join(block.text for block in blocks)
    if not canonical:
        raise DocumentProcessingError("document has no safe text")
    version = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    pending: list[tuple[str, list[_Block], list[dict[str, int | str]]]] = []

    # Preserve original paragraph/block boundaries. Only split a single
    # oversized block; do not combine unrelated short paragraphs into one chunk.
    for block in blocks:
        for piece, start, end in _split_long_block(block):
            pending.append((
                piece,
                [block],
                [{"block_index": block.block_index, "start_char": start, "end_char": end, "kind": block.kind}],
            ))

    chunks: list[KnowledgeChunk] = []
    for index, (text, used_blocks, ranges) in enumerate(pending):
        heading_path = list(used_blocks[-1].heading_path) if used_blocks else []
        locator = {
            "kind": "html_blocks" if document.format == "text/html" else "text_blocks",
            "heading_path": heading_path,
            "ranges": ranges,
        }
        chunk_hash = hashlib.sha256(
            f"{document.document_id}\0{version}\0{index}\0{text}".encode("utf-8")
        ).hexdigest()
        chunks.append(KnowledgeChunk(
            document_id=document.document_id,
            document_title=document.title,
            document_version=version,
            content_hash=version,
            chunk_index=index,
            chunk_text=text,
            chunk_hash=chunk_hash,
            source_locator=locator,
            source_type=document.source_type,
            visibility_scope=document.visibility_scope,
            reply_eligible=document.reply_eligible,
            uploader_id=document.uploader_id,
            cleaning_version=CLEANING_VERSION,
            chunking_version=CHUNKING_VERSION,
            test_only=document.test_only,
        ))
    return chunks


__all__ = [
    "CHUNK_OVERLAP_CHARS",
    "CLEANING_VERSION",
    "DocumentFormat",
    "DocumentInput",
    "DocumentProcessingError",
    "DocumentSourceType",
    "KnowledgeChunk",
    "MAX_CHUNK_CHARS",
    "MAX_DOCUMENT_CHARS",
    "process_document",
]
