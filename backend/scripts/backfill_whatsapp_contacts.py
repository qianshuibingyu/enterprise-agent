"""Repair WhatsApp rows whose contact is a privacy LID instead of a phone.

WhatsApp now delivers direct chats under ``<id>@lid``. A LID is not a phone
number, so a row stored with it cannot build a chat deep link and the console
could only open the WhatsApp root. New inbound messages resolve the LID while
they are captured; this script repairs the rows that were stored before that
resolution existed.

Usage (inside the backend container):

    python scripts/backfill_whatsapp_contacts.py           # report only
    python scripts/backfill_whatsapp_contacts.py --apply   # write the phones
"""

import argparse
import sys

from sqlalchemy import select

import app.models.user  # noqa: F401 - registers the users table for the FK graph
from app.database import SessionLocal
from app.models.business import ChannelAccount, Message
from app.whatsapp_adapter import (
    HttpWhatsAppAdapterClient,
    WhatsAppAdapterConfigurationError,
    WhatsAppAdapterUnavailableError,
)


def lid_from(value: str | None) -> str | None:
    candidate = (value or "").strip()
    return candidate if candidate.endswith("@lid") else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist resolved phones")
    args = parser.parse_args()

    db = SessionLocal()
    resolved = unresolved = 0
    try:
        adapter = HttpWhatsAppAdapterClient()
        rows = db.scalars(
            select(Message).where(Message.customer_contact.like("%@lid"))
        ).all()
        for message in rows:
            account = db.get(ChannelAccount, message.channel_account_id)
            if account is None or account.channel_type != "whatsapp":
                continue
            lid = lid_from(message.customer_contact)
            if lid is None:
                continue
            try:
                phone = adapter.resolve_lid_phone(
                    channel_account_id=account.id,
                    lid=lid,
                )
            except (WhatsAppAdapterConfigurationError, WhatsAppAdapterUnavailableError) as exc:
                print(f"adapter unavailable: {exc}", file=sys.stderr)
                break
            if phone is None:
                unresolved += 1
                print(f"message {message.id}: {lid} has no phone mapping")
                continue
            resolved += 1
            print(f"message {message.id}: {lid} -> {phone}")
            if args.apply:
                message.customer_contact = phone
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(
            f"resolved={resolved} unresolved={unresolved} applied={args.apply}"
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
