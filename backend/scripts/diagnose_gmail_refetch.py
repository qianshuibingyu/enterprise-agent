"""Diagnose the Gmail refetch path without printing secrets or message bodies."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow `python scripts/diagnose_gmail_refetch.py` from the backend directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database import SessionLocal
from app.gmail_client import GmailApiClient, GmailConfigurationError
from app.gmail_credentials import GmailCredentialError, decrypt_refresh_token
from app.models.business import ChannelAccount, Message


def status(name: str, value: str) -> None:
    print(f"{name}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--message-id", type=int, required=True)
    args = parser.parse_args()

    print("Gmail refetch diagnostic")
    for name in (
        "GMAIL_ENABLED",
        "GMAIL_CLIENT_ID",
        "GMAIL_CLIENT_SECRET",
        "GMAIL_CREDENTIAL_ENCRYPTION_KEY",
        "GMAIL_USER_ID",
        "POSTGRES_USER",
        "POSTGRES_DB",
        "DB_HOST",
    ):
        value = os.environ.get(name)
        if not value:
            status(name, "MISSING")
        elif name in {"GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_CREDENTIAL_ENCRYPTION_KEY"}:
            status(name, f"SET length={len(value)}")
        else:
            status(name, "SET")

    try:
        with SessionLocal() as db:
            message = db.scalar(
                select(Message)
                .where(Message.id == args.message_id)
            )
            if message is None:
                status("database.message", "FAIL not found")
                return 2

            account = db.scalar(
                select(ChannelAccount).where(ChannelAccount.id == message.channel_account_id)
            )
            status("database.connection", "OK")
            status("message.provider", message.provider)
            status("message.external_id", "SET" if message.external_message_id else "MISSING")
            status("message.cached_content", "SET" if message.raw_content else "EMPTY")
            if account is None:
                status("database.channel_account", "FAIL not found")
                return 2
            status("account.channel_type", account.channel_type)
            status("account.status", account.status)
            status(
                "account.gmail_credential_ciphertext",
                f"SET length={len(account.gmail_credential_ciphertext)}"
                if account.gmail_credential_ciphertext else "MISSING",
            )

            if message.provider not in {"gmail_api_pubsub", "gmail_pubsub", "gmail"}:
                status("provider.selection", "FAIL unsupported provider")
                return 3
            if not account.gmail_credential_ciphertext:
                status("provider.selection", "FAIL missing account credential")
                return 3

            try:
                refresh_token = decrypt_refresh_token(account.gmail_credential_ciphertext)
                status("credential.decrypt", f"OK length={len(refresh_token)}")
            except GmailCredentialError as exc:
                status("credential.decrypt", f"FAIL {type(exc).__name__}: {exc}")
                return 4

            try:
                client = GmailApiClient(refresh_token=refresh_token)
                status("gmail.client", "OK")
            except GmailConfigurationError as exc:
                status("gmail.client", f"FAIL {type(exc).__name__}: {exc}")
                return 5

            try:
                fetched = client.fetch_message(
                    account_id=account.id,
                    message_id=message.external_message_id,
                )
                raw_content = fetched.get("raw_content") if isinstance(fetched, dict) else None
                status("gmail.api.fetch", "OK")
                status("gmail.api.content", f"SET length={len(raw_content)}" if isinstance(raw_content, str) else "EMPTY")
                return 0 if isinstance(raw_content, str) and raw_content.strip() else 6
            except Exception as exc:  # diagnostic boundary: print only safe type/message
                status("gmail.api.fetch", f"FAIL {type(exc).__name__}: {exc}")
                return 6
    except Exception as exc:
        status("database.connection", f"FAIL {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
