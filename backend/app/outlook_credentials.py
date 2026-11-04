"""Server-side encrypted storage for delegated Outlook refresh tokens."""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


class OutlookCredentialError(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = os.environ.get("OUTLOOK_CREDENTIAL_ENCRYPTION_KEY", "")
    if not key:
        raise OutlookCredentialError("Outlook credential encryption is not configured")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise OutlookCredentialError("Outlook credential encryption is misconfigured") from exc


def encrypt_refresh_token(refresh_token: str) -> str:
    if not refresh_token:
        raise OutlookCredentialError("Outlook refresh token is empty")
    return _fernet().encrypt(refresh_token.encode("utf-8")).decode("ascii")


def decrypt_refresh_token(ciphertext: str) -> str:
    if not ciphertext:
        raise OutlookCredentialError("Outlook credential is missing")
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeEncodeError, UnicodeDecodeError, ValueError) as exc:
        raise OutlookCredentialError("Outlook credential cannot be decrypted") from exc
