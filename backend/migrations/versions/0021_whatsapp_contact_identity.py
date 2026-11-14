"""Normalize stored WhatsApp contacts handed over without the E.164 prefix.

The Baileys adapter extracts the JID user part, so a direct chat arrives as bare
international digits (``46735037108``). The normalizer only trusted values that
already started with ``+``, which left every WhatsApp one-to-one message in
``needs_manual_review``: no customer chain was created and the inbox asked an
operator to confirm an attribution the exact phone number had already decided.

This revision re-runs the deterministic identity rule over the stored rows and
links the unambiguous inbound messages. It never guesses: group chats, LID-only
chats and non-numeric contacts keep their manual review state.
"""

from alembic import op
from sqlalchemy.orm import Session

from app.identity_repair import repair_whatsapp_contact_identity

revision = "0021_whatsapp_contact_identity"
down_revision = "0020_user_capability_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The repair session joins the migration's own connection/transaction, so
    # alembic commits the repaired rows together with the revision bump.
    session = Session(bind=op.get_bind())
    repair_whatsapp_contact_identity(session)
    session.flush()


def downgrade() -> None:
    # Identity normalization and the customer chains it created are business
    # data; they are not undone by a schema downgrade.
    pass
