import hashlib
import hmac
import os


class CredentialError(ValueError):
    pass


class CredentialReferenceService:
    """Keep only references/digests in this layer; never persist a raw long-lived token."""

    def __init__(self, secret: str | None = None):
        self._secret = (secret or os.environ.get("CREDENTIAL_REFERENCE_SECRET"))
        if not self._secret:
            raise CredentialError("credential reference secret is not configured")

    def reference_for(self, *, token: str | None = None, reference: str | None = None) -> str:
        if token is not None:
            raise CredentialError("明文长期 token 不允许保存")
        if not reference or len(reference) > 512:
            raise CredentialError("credential reference is required")
        digest = hmac.new(self._secret.encode(), reference.encode(), hashlib.sha256).hexdigest()
        return f"ref:{digest}"

    def redacted(self, value: str | None) -> str | None:
        if value is None:
            return None
        return "[redacted]"
