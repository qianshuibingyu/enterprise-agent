from datetime import datetime, timezone

from app.contact_identity import normalize_email, normalize_whatsapp
from app.message_ingestion import map_provider_message


def test_email_identity_extracts_address_and_casefolds_only():
    result = normalize_email('  "Support Team" <Support+tag@Example.COM>  ')
    assert result.raw == '  "Support Team" <Support+tag@Example.COM>  '
    assert result.normalized == "support+tag@example.com"
    assert result.state == "certain"
    assert result.kind == "email"


def test_email_aliases_and_shared_addresses_are_not_folded_together():
    support = normalize_email("support@example.com")
    sales = normalize_email("sales@example.com")
    tagged = normalize_email("support+tag@example.com")
    assert len({support.normalized, sales.normalized, tagged.normalized}) == 3


def test_malformed_email_needs_manual_review():
    result = normalize_email("not-an-address")
    assert result.normalized is None
    assert result.state == "needs_manual_review"


def test_whatsapp_e164_and_personal_jid_are_normalized_by_library():
    formatted = normalize_whatsapp("+1 (650) 253-0000")
    jid = normalize_whatsapp("16502530000@s.whatsapp.net")
    assert formatted.normalized == "+16502530000"
    assert jid.normalized == formatted.normalized
    assert jid.raw == "16502530000@s.whatsapp.net"


def test_whatsapp_without_country_code_and_non_personal_jids_do_not_guess():
    local = normalize_whatsapp("6502530000")
    group = normalize_whatsapp("16502530000@g.us")
    lid = normalize_whatsapp("12345@lid")
    assert local.normalized is None
    assert local.state == "needs_manual_review"
    assert group.state == lid.state == "unsupported"
    assert group.normalized is lid.normalized is None


def test_forwarded_sender_with_trusted_original_matches_original_but_keeps_sender_raw():
    mapped = map_provider_message(
        channel_account_id=10,
        provider="gmail_api_pubsub",
        message={
            "external_message_id": "forwarded-2",
            "direction": "inbound",
            "status": "received",
            "occurred_at": datetime.now(timezone.utc),
            "raw_content": "forwarded body",
            "customer_contact": "forwarder@example.com",
            "original_sender_contact": "Original Person <Customer+Tag@Example.com>",
            "contact_identity_kind": "email",
            "contact_forwarded": True,
        },
    )
    assert mapped.customer_contact == "forwarder@example.com"
    assert mapped.original_sender_contact == "Original Person <Customer+Tag@Example.com>"
    assert mapped.normalized_customer_contact == "customer+tag@example.com"
    assert mapped.contact_identity_state == "forwarded"


def test_forwarded_sender_without_trusted_original_is_uncertain():
    mapped = map_provider_message(
        channel_account_id=10,
        provider="gmail_api_pubsub",
        message={
            "external_message_id": "forwarded-1",
            "direction": "inbound",
            "status": "received",
            "occurred_at": datetime.now(timezone.utc),
            "raw_content": "forwarded body",
            "customer_contact": "forwarder@example.com",
            "contact_identity_kind": "email",
            "contact_forwarded": True,
        },
    )
    assert mapped.customer_contact == "forwarder@example.com"
    assert mapped.normalized_customer_contact == "forwarder@example.com"
    assert mapped.contact_identity_state == "identity_uncertain"
    assert mapped.original_sender_contact is None
