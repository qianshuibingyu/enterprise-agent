import hashlib
from dataclasses import dataclass


class CredentialError(ValueError):
    pass


@dataclass(frozen=True)
class CredentialReference:
    reference: str
    redacted: str


class CredentialStore:
    """Non-persistent boundary for tests; rejects long-lived plaintext tokens."""

    def __init__(self) -> None:
        self._references: dict[tuple[int, str], CredentialReference] = {}

    def put(self, *, user_id: int, channel_account_id: int, credential: str) -> CredentialReference:
        if not credential or len(credential) < 8:
            raise CredentialError("credential is invalid")
        digest = hashlib.sha256(credential.encode()).hexdigest()
        reference = CredentialReference(
            reference=f"credential-ref:{digest[:16]}",
            redacted=f"…{digest[-8:]}",
        )
        self._references[(user_id, str(channel_account_id))] = reference
        return reference

    def get_reference(self, *, user_id: int, channel_account_id: int) -> CredentialReference | None:
        return self._references.get((user_id, str(channel_account_id)))
