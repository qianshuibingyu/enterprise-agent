from app.content_security import content_view


def test_content_view_returns_plain_text_and_drops_active_html_content():
    result = content_view(
        '<p>Hello <strong>world</strong></p><script>alert(1)</script>'
        '<a href="javascript:alert(2)" onclick="alert(3)">safe label</a>'
        '<iframe src="https://tracker.invalid">hidden</iframe>'
    )

    assert result["content_format"] == "text/plain"
    assert result["content_sanitized"] is True
    assert "alert" not in result["display_text"]
    assert "hidden" not in result["display_text"]
    assert "Hello" in result["display_text"]
    assert "world" in result["display_text"]
    assert "safe label" in result["display_text"]


def test_content_view_handles_empty_and_none_values():
    assert content_view(None)["display_text"] == ""
    assert content_view("<div></div>")["display_excerpt"] == ""


def test_content_view_truncates_display_text_and_excerpt_stably():
    result = content_view("x" * 12_100)

    assert len(result["display_text"]) == 12_000
    assert len(result["display_excerpt"]) == 280
    assert result["content_truncated"] is True
    assert result["display_excerpt"].endswith("…")


def test_content_view_degrades_malformed_markup_without_returning_markup():
    result = content_view("<p>before <b>broken & text")

    assert result["content_format"] == "text/plain"
    assert "<p>" not in result["display_text"]
    assert "<b>" not in result["display_text"]
    assert "before" in result["display_text"]
