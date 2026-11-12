"""Provider deep-link policy for the "去渠道处理" actions.

Two failures are prevented here:

* A message without a provider-issued link used to fall back to a generic
  inbox page, so the user never reached the email that produced the row.
* The fallback inbox page used one Microsoft host for every mailbox. Personal
  Microsoft accounts are only served by ``outlook.live.com``; the
  ``outlook.office.com`` host belongs to work/school mailboxes and answers a
  personal account with a sign-in and account-picker page. That made every
  click look like "又要重新授权登录" even though the stored OAuth credential was
  valid.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

OUTLOOK_WEB_HOSTS = {
    "outlook.office.com",
    "outlook.office365.com",
    "outlook.live.com",
}

OUTLOOK_PERSONAL_INBOX = "https://outlook.live.com/mail/0/"
OUTLOOK_WORK_INBOX = "https://outlook.office.com/mail/"

# Microsoft personal accounts (MSA) expose a 16-character hex Graph id, while
# work/school accounts expose a GUID. The mailbox subject is the only account
# discriminator persisted on ChannelAccount, so it drives the fallback host.
_PERSONAL_ACCOUNT_ID = re.compile(r"[0-9a-f]{16}")
_PERSONAL_MAIL_DOMAINS = ("outlook.com", "hotmail.com", "live.com", "msn.com")


def outlook_web_link(value: str | None) -> str | None:
    """Return the link only when it is an https URL on a Microsoft mail host."""
    if not value:
        return None
    candidate = value.strip()
    parsed = urlparse(candidate)
    if parsed.scheme != "https" or parsed.hostname not in OUTLOOK_WEB_HOSTS:
        return None
    return candidate


def outlook_account_is_personal(
    *,
    external_account_id: str | None,
    address: str | None = None,
) -> bool:
    """Decide which Outlook web host can serve this mailbox."""
    if address and "@" in address:
        return address.rsplit("@", 1)[1].strip().lower() in _PERSONAL_MAIL_DOMAINS
    subject = (external_account_id or "").strip().lower()
    return bool(subject) and _PERSONAL_ACCOUNT_ID.fullmatch(subject) is not None


def outlook_inbox_url(*, personal: bool) -> str:
    return OUTLOOK_PERSONAL_INBOX if personal else OUTLOOK_WORK_INBOX
