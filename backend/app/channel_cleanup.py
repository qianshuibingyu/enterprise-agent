"""Removal of revoked / superseded channel account shells.

A "撤销本地连接" used to leave a ``status=revoked`` row behind forever. That
dead shell then blocked re-authorization (the account picker returned it by
lowest id) and blocked ownership transfer (it looked like a duplicate channel).
Revoking a freshly created, empty shell should actually remove the shell.
Accounts that still hold messages or inquiries are kept as revoked archives so
business history is never silently destroyed; the administrator can restore
those explicitly from the employee page.
"""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.business import (
    ChannelAccount,
    ChannelGrant,
    Inquiry,
    Message,
    WhatsAppGroupBinding,
)


def purge_channel_shell(db: Session, account: ChannelAccount) -> bool:
    """Delete an account shell when no business history references it.

    Returns ``True`` when the row was removed together with its grants and
    group bindings, ``False`` when it must be preserved as a revoked archive.
    Callers must not touch ``account`` after a ``True`` result.
    """
    db.flush()
    message_count = db.scalar(
        select(func.count()).select_from(Message)
        .where(Message.channel_account_id == account.id)
    ) or 0
    inquiry_count = db.scalar(
        select(func.count()).select_from(Inquiry)
        .where(Inquiry.source_channel_account_id == account.id)
    ) or 0
    if message_count or inquiry_count:
        return False
    # channel_grants has a composite FK to the account; remove children first
    # so this works on PostgreSQL as well as on SQLite test databases.
    db.execute(delete(ChannelGrant).where(ChannelGrant.channel_account_id == account.id))
    db.execute(
        delete(WhatsAppGroupBinding)
        .where(WhatsAppGroupBinding.channel_account_id == account.id)
    )
    db.execute(delete(ChannelAccount).where(ChannelAccount.id == account.id))
    return True
