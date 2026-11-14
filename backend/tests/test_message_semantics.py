"""客户链路以清洗后的安全原文为主；撤回占位符不能当成「消息为空」。

回归用户截图：消息 #295 的正文是 `[empty WhatsApp message]`，中文概要却写成
「意图不明：消息内容为空」，状态还是「待处理」。这其实是客户双端删除/撤回的
协议消息，必须显示为「已撤回」，并且链路里首先展示的是安全原文而不是概要。
"""

from types import SimpleNamespace

from app.message_semantics import (
    CONTENT_STATE_HIDDEN,
    CONTENT_STATE_READY,
    CONTENT_STATE_REVOKED,
    REVOKED_DISPLAY_TEXT,
    content_state,
    inline_safe_text,
    is_provider_placeholder,
    is_recoverable_body,
    is_revoked_content,
    needs_body_repair,
    safe_content_view,
)
from app.models.business import Message
from app.models.overview import MessageOverview
from app.overview_service import ensure_message_overview
from tests.test_business_authorization import business_client, login  # noqa: F401

LEGACY_PLACEHOLDER = "[empty WhatsApp message]"
NEW_MARKER = "[WhatsApp message revoked]"


def test_revoke_placeholders_are_semantic_not_empty():
    for marker in (LEGACY_PLACEHOLDER, NEW_MARKER, NEW_MARKER.lower(), "  " + LEGACY_PLACEHOLDER + "  "):
        assert is_revoked_content(marker)
        assert content_state(marker) == CONTENT_STATE_REVOKED
        view = safe_content_view(marker)
        assert view["content_state"] == CONTENT_STATE_REVOKED
        assert view["display_text"] == REVOKED_DISPLAY_TEXT
        assert view["display_excerpt"] == REVOKED_DISPLAY_TEXT
        assert LEGACY_PLACEHOLDER not in str(view["display_text"])


def test_real_customer_text_keeps_safe_body_and_ready_state():
    view = safe_content_view("<b>报价</b><script>alert(1)</script> 含 [empty WhatsApp message] 这句话")
    assert view["content_state"] == CONTENT_STATE_READY
    assert "报价" in view["display_text"]
    assert "alert(1)" not in view["display_text"]  # active markup is stripped
    assert "[empty WhatsApp message]" in view["display_text"]
    assert content_state("") == CONTENT_STATE_READY


def test_stub_snapshots_can_be_repaired_by_a_real_provider_body():
    """撤回的含义是「原文不可恢复」：渠道仍留着客户原话就不能算撤回。"""
    for marker in (LEGACY_PLACEHOLDER, NEW_MARKER, "[non-text WhatsApp message]", "", "  "):
        assert is_provider_placeholder(marker)
        assert not is_recoverable_body(marker)
        assert needs_body_repair(marker, "Hola, quiero comprar mandos.")
        # 不能拿另一个占位符或空结果覆盖原快照。
        assert not needs_body_repair(marker, NEW_MARKER)
        assert not needs_body_repair(marker, "")

    assert is_recoverable_body("Hola, quiero comprar mandos.")
    assert not is_provider_placeholder("报价里写了 [empty WhatsApp message] 这句话")
    # 正常正文永远不会被回源结果覆盖。
    assert not needs_body_repair("客户原文", "另一段回源文本")


def test_inline_safe_text_is_bounded_and_flagged():
    text, truncated = inline_safe_text("长" * 10, limit=5)
    assert text == "长长长长长…"
    assert truncated is True
    text, truncated = inline_safe_text("短原文")
    assert text == "短原文"
    assert truncated is False
    assert inline_safe_text(LEGACY_PLACEHOLDER) == (REVOKED_DISPLAY_TEXT, False)


def test_overview_generation_skips_revoked_messages():
    message = SimpleNamespace(
        id=295,
        direction="inbound",
        handling_status="pending",
        test_only=False,
        raw_content=LEGACY_PLACEHOLDER,
        provider="whatsapp_web_baileys",
        overview=None,
    )
    # db is never touched: no LLM call, no "意图不明：消息内容为空" row.
    assert ensure_message_overview(None, message) is None
    assert message.overview is None


def test_inquiry_chain_leads_with_safe_text_and_marks_revoked(business_client):
    with business_client.testing_session() as db:
        message = db.get(Message, 1)
        message.raw_content = LEGACY_PLACEHOLDER
        db.add(MessageOverview(
            message_id=1,
            status="ready",
            overview_text="意图不明：消息内容为空，无法判断发件人意图或需执行的动作。",
        ))
        db.commit()

    login(business_client, "operator", "operator1")

    items = business_client.get("/api/messages").json()["items"]
    row = next(item for item in items if item["id"] == 1)
    assert row["content_state"] == CONTENT_STATE_REVOKED
    assert row["display_excerpt"] == REVOKED_DISPLAY_TEXT
    assert row["overview"] is None, "撤回消息不应再挂「消息内容为空」的中文概要"

    detail = business_client.get("/api/inquiries/1")
    assert detail.status_code == 200, detail.text
    linked = next(item for item in detail.json()["messages"] if item["id"] == 1)
    assert linked["content_state"] == CONTENT_STATE_REVOKED
    assert linked["safe_text"] == REVOKED_DISPLAY_TEXT
    assert linked["safe_text_truncated"] is False
    assert linked["overview_status"] == "not_applicable_revoked"
    assert linked["overview_text"] is None
    assert linked["safe_content_status"] == CONTENT_STATE_REVOKED
    assert "raw_content" not in linked

    content = business_client.get("/api/messages/1/content")
    assert content.status_code == 200, content.text
    body = content.json()
    assert body["content_state"] == CONTENT_STATE_REVOKED
    assert body["full_text"] == REVOKED_DISPLAY_TEXT
    assert LEGACY_PLACEHOLDER not in body["full_text"]


def test_normal_inquiry_message_exposes_safe_body_before_summary(business_client):
    with business_client.testing_session() as db:
        db.get(Message, 1).raw_content = "Hello, I need a quote for 500 smart locks."
        db.add(MessageOverview(message_id=1, status="ready", overview_text="产品询价：客户需要 500 把智能锁报价。"))
        db.commit()

    login(business_client, "operator", "operator1")
    linked = business_client.get("/api/inquiries/1").json()["messages"][0]
    assert linked["content_state"] == CONTENT_STATE_READY
    assert linked["safe_text"] == "Hello, I need a quote for 500 smart locks."
    assert linked["overview_text"] == "产品询价：客户需要 500 把智能锁报价。"


def test_admin_inquiry_view_is_redacted_and_keeps_masked_summary(business_client):
    with business_client.testing_session() as db:
        db.get(Message, 1).raw_content = "Hello, contact jane.doe@example.com or +1 (650) 253-0000."
        db.get(Message, 1).customer_contact = "Jane Doe <jane.doe@example.com>"
        db.get(Message, 1).normalized_customer_contact = "jane.doe@example.com"
        db.get(Message, 1).customer_nickname = "Jane Doe"
        db.add(MessageOverview(
            message_id=1,
            status="ready",
            overview_text="Jane Doe asked us to email jane.doe@example.com or call +1 (650) 253-0000.",
        ))
        db.commit()

    login(business_client, "admin", "adminpass1")
    detail = business_client.get("/api/inquiries/1")
    assert detail.status_code == 200, detail.text
    linked = detail.json()["messages"][0]
    assert linked["content_state"] == CONTENT_STATE_HIDDEN
    assert linked["safe_text"] is None
    assert linked["safe_content_status"] == CONTENT_STATE_READY
    assert linked["overview_status"] == "ready"
    assert linked["overview_text"] == "[redacted] asked us to email [email redacted] or call [phone redacted]."
    assert "Jane Doe" not in detail.text
    assert "jane.doe@example.com" not in detail.text
    assert "+1 (650) 253-0000" not in detail.text
    assert "external_message_id" not in linked
    assert "provider" not in linked
    assert "channel_account_external_id" not in linked
    assert "channel_account_id" not in linked
    assert "Hello" not in detail.text

    assert business_client.get("/api/messages/1").status_code == 403
    assert business_client.get("/api/messages/1/content").status_code == 403
    overview = business_client.get("/api/messages/1/overview")
    assert overview.status_code == 200
    assert "Jane Doe" not in overview.text
    assert "jane.doe@example.com" not in overview.text
    assert "+1 (650) 253-0000" not in overview.text
    assert "Hello" not in overview.text


def test_admin_message_list_and_overview_distinguish_revoked_from_missing_summary(business_client):
    with business_client.testing_session() as db:
        message = db.get(Message, 1)
        message.raw_content = LEGACY_PLACEHOLDER
        db.add(MessageOverview(
            message_id=1,
            status="ready",
            overview_text="意图不明：消息内容为空，无法判断发件人意图或需执行的动作。",
        ))
        db.commit()

    login(business_client, "admin", "adminpass1")
    listed = business_client.get("/api/messages?handling_status=all")
    assert listed.status_code == 200
    row = next(item for item in listed.json()["items"] if item["id"] == 1)
    assert row["safe_content_status"] == CONTENT_STATE_REVOKED
    assert row["overview_status"] == "not_applicable_revoked"
    assert row["overview"] is None
    assert LEGACY_PLACEHOLDER not in listed.text
    assert "意图不明" not in listed.text

    overview = business_client.get("/api/messages/1/overview")
    assert overview.status_code == 200
    assert overview.json() == {"message_id": 1, "overview": None}
