from app.business_routes import OUTLOOK_WEB_HOSTS, _whatsapp_phone
from app.provider_links import (
    outlook_account_is_personal,
    outlook_inbox_url,
    outlook_web_link,
)


def test_outlook_web_link_allowlist_includes_microsoft_365_message_host():
    assert "outlook.office365.com" in OUTLOOK_WEB_HOSTS
    assert "outlook.live.com" in OUTLOOK_WEB_HOSTS


def test_whatsapp_phone_normalizes_only_safe_personal_phone_values():
    assert _whatsapp_phone("+86 138-1234-5678") == "8613812345678"
    assert _whatsapp_phone("8613812345678@s.whatsapp.net") == "8613812345678"
    assert _whatsapp_phone("8613812345678:12@s.whatsapp.net") == "8613812345678"
    assert _whatsapp_phone("12345-67890@g.us") is None
    assert _whatsapp_phone("123456789@lid") is None


def test_outlook_links_are_only_exposed_for_microsoft_mail_hosts():
    assert outlook_web_link("https://outlook.live.com/owa/?ItemID=x") == (
        "https://outlook.live.com/owa/?ItemID=x"
    )
    assert outlook_web_link("https://outlook.office.com/mail/id/x") is not None
    assert outlook_web_link("http://outlook.live.com/owa/") is None
    assert outlook_web_link("https://outlook.live.com.evil.example/owa/") is None
    assert outlook_web_link("javascript:alert(1)") is None
    assert outlook_web_link(None) is None


def test_personal_mailboxes_never_use_the_work_or_school_inbox_host():
    # Microsoft personal account subjects are 16 hex characters, work/school
    # subjects are GUIDs.
    assert outlook_account_is_personal(external_account_id="1ee714b1593489d8") is True
    assert outlook_account_is_personal(
        external_account_id="d3330d76-5b81-4678-b659-15b4ce66993e"
    ) is False
    assert outlook_account_is_personal(
        external_account_id=None,
        address="someone@hotmail.com",
    ) is True
    assert outlook_inbox_url(personal=True) == "https://outlook.live.com/mail/0/"
    assert outlook_inbox_url(personal=False) == "https://outlook.office.com/mail/"
