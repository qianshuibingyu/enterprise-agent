import pytest

from app.document_processing import (
    CHUNK_OVERLAP_CHARS,
    MAX_CHUNK_CHARS,
    DocumentInput,
    DocumentProcessingError,
    process_document,
)


def doc(content: str, *, fmt: str = "text/plain", **overrides) -> DocumentInput:
    values = {
        "document_id": "doc-1",
        "title": "Product Guide",
        "source_type": "product",
        "format": fmt,
        "content": content,
        "visibility_scope": "department:operations",
        "reply_eligible": True,
        "uploader_id": 7,
        "test_only": True,
    }
    values.update(overrides)
    return DocumentInput(**values)


def test_plain_text_produces_deterministic_chunk_and_source_metadata():
    document = doc("  Product A  \n\n Details and pricing. ")

    first = process_document(document)
    second = process_document(document)

    assert len(first) == 2
    assert first == second
    assert [chunk.chunk_text for chunk in first] == ["Product A", "Details and pricing."]
    assert first[0].document_version == first[0].content_hash
    assert len(first[0].content_hash) == 64
    assert len(first[0].chunk_hash) == 64
    assert first[0].source_locator["ranges"][0]["block_index"] == 0
    assert first[1].source_locator["ranges"][0]["block_index"] == 1
    assert first[0].visibility_scope == "department:operations"
    assert first[0].reply_eligible is True
    assert first[0].test_only is True


def test_html_removes_active_content_and_preserves_heading_path():
    chunks = process_document(doc(
        "<h1>Catalog</h1><p>Products available.</p><script>bad()</script>"
        "<iframe src='https://tracker.invalid'>tracker text</iframe>",
        fmt="text/html",
    ))

    assert [chunk.chunk_text for chunk in chunks] == ["Catalog", "Products available."]
    assert chunks[1].source_locator["heading_path"] == ["Catalog"]
    assert all("bad" not in chunk.chunk_text and "tracker" not in chunk.chunk_text for chunk in chunks)


def test_markdown_preserves_heading_and_list_provenance_without_markup():
    chunks = process_document(doc(
        "# Returns\n\nRead the **return policy**.\n\n- Contact support",
        fmt="text/markdown",
    ))

    assert [chunk.chunk_text for chunk in chunks] == ["Returns", "Read the return policy.", "Contact support"]
    assert chunks[1].source_locator["heading_path"] == ["Returns"]
    assert chunks[2].source_locator["heading_path"] == ["Returns"]
    assert "**" not in "".join(chunk.chunk_text for chunk in chunks)


def test_long_paragraph_is_split_with_bounded_overlap_and_repeatable_hashes():
    source = "x" * (MAX_CHUNK_CHARS * 2 + 137)
    chunks = process_document(doc(source))

    assert len(chunks) == 3
    assert all(len(chunk.chunk_text) <= MAX_CHUNK_CHARS for chunk in chunks)
    assert chunks[0].chunk_text[-CHUNK_OVERLAP_CHARS:] == chunks[1].chunk_text[:CHUNK_OVERLAP_CHARS]
    assert chunks[1].chunk_text[-CHUNK_OVERLAP_CHARS:] == chunks[2].chunk_text[:CHUNK_OVERLAP_CHARS]
    assert [chunk.chunk_hash for chunk in chunks] == [chunk.chunk_hash for chunk in process_document(doc(source))]
    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2]


def test_rejects_unconfirmed_customer_sources_and_bad_scope():
    with pytest.raises(DocumentProcessingError, match="source type"):
        process_document(doc("text", source_type="customer"))
    with pytest.raises(DocumentProcessingError, match="visibility scope"):
        process_document(doc("text", visibility_scope=""))


def test_rejects_unsupported_formats_and_empty_or_oversized_documents():
    with pytest.raises(DocumentProcessingError, match="unsupported"):
        process_document(doc("binary placeholder", fmt="application/pdf"))
    with pytest.raises(DocumentProcessingError, match="empty"):
        process_document(doc(" \n "))
    with pytest.raises(DocumentProcessingError, match="input limit"):
        process_document(doc("x" * 1_000_001))


def test_markdown_removes_embedded_dangerous_html_before_chunking():
    chunks = process_document(doc(
        "Visible text\n\n<script>secret-script</script><iframe>tracker</iframe><b>safe bold</b>",
        fmt="text/markdown",
    ))

    all_text = "\\n".join(chunk.chunk_text for chunk in chunks)
    assert "Visible text" in all_text
    assert "safe bold" in all_text
    assert "secret-script" not in all_text
    assert "tracker" not in all_text
    assert "<b>" not in all_text


def test_unclosed_markdown_fence_content_is_not_indexed_as_document_text():
    chunks = process_document(doc("Intro paragraph\n\n```html\n<script>do-not-index</script>" , fmt="text/markdown"))

    assert [chunk.chunk_text for chunk in chunks] == ["Intro paragraph"]
