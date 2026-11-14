"""Re-identify stored WhatsApp contacts that were never normalized to E.164.

Baileys hands a direct chat over as bare international digits (``46735037108``)
because it strips the ``@s.whatsapp.net`` JID suffix. The previous normalizer
only trusted values that already started with ``+``, so every WhatsApp one-to-one
message was stored as ``needs_manual_review``: no customer chain was created, the
inbox asked an operator to confirm an attribution that the exact phone number had
already decided, and the group-binding contact picker (which lists confirmed
phone numbers) came back empty.

The repair applies the same deterministic rule as ingestion: a complete
international number identifies exactly one contact. Only unlinked inbound
messages are linked. Group chats (no phone number), LID-only chats and anything
else that is not an exact number stay a manual operator decision.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contact_identity import normalize_whatsapp
from app.message_ingestion import (
    RELINKABLE_INQUIRY_HANDLING_STATUSES,
    _link_inbound_message_to_inquiry,
)
from app.models.business import ChannelAccount, Inquiry, Message


def repair_whatsapp_contact_identity(db: Session) -> dict[str, int]:
    """Normalize stored WhatsApp contacts and link the unambiguous ones.

    Idempotent: rows that already hold a confirmed identity are not selected,
    and a message that already belongs to a chain is never re-linked.
    """
    stats = {"scanned": 0, "confirmed": 0, "linked": 0, "inquiries_created": 0}
    messages = db.scalars(
        select(Message)
        .join(ChannelAccount, ChannelAccount.id == Message.channel_account_id)
        .where(
            ChannelAccount.channel_type == "whatsapp",
            ChannelAccount.status != "revoked",
            ChannelAccount.history_access_revoked_at.is_(None),
            Message.is_website_form.is_(False),
            Message.customer_contact.is_not(None),
            Message.contact_identity_state != "certain",
        )
        .order_by(Message.occurred_at, Message.id)
    ).all()
    for message in messages:
        stats["scanned"] += 1
        identity = normalize_whatsapp(message.customer_contact, assume_international=True)
        if identity.state != "certain" or not identity.normalized:
            continue
        if message.contact_identity_kind not in (None, "whatsapp"):
            continue
        message.contact_identity_state = "certain"
        message.contact_identity_kind = "whatsapp"
        message.normalized_customer_contact = identity.normalized
        stats["confirmed"] += 1
        if message.direction != "inbound" or message.inquiry_link is not None:
            continue
        if message.link_state == "linked":
            continue
        same_contact = select(Inquiry.id).where(
            Inquiry.normalized_customer_contact == identity.normalized,
            Inquiry.contact_identity_kind == "whatsapp",
        )
        open_chain = db.scalar(
            same_contact.where(
                Inquiry.handling_status.in_(RELINKABLE_INQUIRY_HANDLING_STATUSES)
            )
        )
        if open_chain is None and db.scalar(same_contact) is not None:
            # The only chain for this contact was processed and ignored by an
            # operator. Silently creating a second chain would undo that
            # decision, so this message stays a manual review item.
            continue
        _link_inbound_message_to_inquiry(db, message)
        if message.inquiry_link is not None:
            stats["linked"] += 1
            if open_chain is None:
                stats["inquiries_created"] += 1
    db.flush()
    return stats
