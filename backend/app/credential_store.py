"""Server-side credential reference boundary.

This is an injectable interface for production KMS/Vault integration. The
in-memory implementation is test-only and never exposes a credential to the
frontend or logs.
"""

from dataclasses import dataclass
import hashlib


class CredentialStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredCredential:
    reference: str
    provider: str
    external_account_id: str


class InMemoryCredentialStore:
    """Test-only store; replace with KMS/Vault-backed implementation in prod."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def put(self, *, provider: str, external_account_id: str, secret: str) -> StoredCredential:
        if not secret:
            raise CredentialStoreError("credential is empty")
        digest = hashlib.sha256(f"{provider}:{external_account_id}:{secret}".encode()).hexdigest()
        reference = f"credential-ref:{digest[:24]}"
        self._values[reference] = secret
        return StoredCredential(reference, provider, external_account_id)

    def get_for_test(self, reference: str) -> str | None:
        return self._values.get(reference)
