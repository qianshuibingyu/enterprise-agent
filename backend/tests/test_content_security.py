from app.content_security import content_view, redact_contact_text


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


def test_redact_contact_text_masks_known_names_emails_and_common_phone_numbers():
    text = redact_contact_text(
        "Jane Doe called +1 (650) 253-0000; email JANE.DOE@example.com, ref 2024-01-01.",
        ("Jane Doe", "jane.doe@example.com"),
    )

    assert text == "[redacted] called [phone redacted]; email [email redacted], ref 2024-01-01."


def test_redact_contact_text_leaves_non_contact_digit_sequences_and_none_alone():
    assert redact_contact_text("Order 12345678, ref 20240101123456.") == "Order 12345678, ref 20240101123456."
    assert redact_contact_text(None) is None
