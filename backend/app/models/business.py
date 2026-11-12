from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.overview import MessageOverview


class ChannelAccount(Base):
    __tablename__ = "channel_accounts"
    __table_args__ = (
        UniqueConstraint(
            "id", "channel_type", "owner_user_id",
            name="uq_channel_accounts_id_type_owner",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    channel_type: Mapped[str] = mapped_column(String(32), index=True)
    external_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    credential_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    gmail_credential_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    outlook_credential_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    gmail_watch_history_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gmail_watch_expiration: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    grants: Mapped[list["ChannelGrant"]] = relationship(
        back_populates="channel_account", cascade="all, delete-orphan"
    )
    inquiries: Mapped[list["Inquiry"]] = relationship(back_populates="source_channel_account", passive_deletes=True)


class ChannelGrant(Base):
    __tablename__ = "channel_grants"
    __table_args__ = (
        PrimaryKeyConstraint(
            "channel_account_id",
            "channel_type",
            "owner_user_id",
            name="pk_channel_grants",
        ),
        ForeignKeyConstraint(
            ["channel_account_id", "channel_type", "owner_user_id"],
            [
                "channel_accounts.id",
                "channel_accounts.channel_type",
                "channel_accounts.owner_user_id",
            ],
            name="fk_channel_grants_account_scope",
            ondelete="CASCADE",
        ),
    )

    channel_account_id: Mapped[int] = mapped_column(Integer)
    channel_type: Mapped[str] = mapped_column(String(32))
    owner_user_id: Mapped[int] = mapped_column(Integer)

    channel_account: Mapped[ChannelAccount] = relationship(back_populates="grants")


class Inquiry(Base):
    __tablename__ = "inquiries"
    __table_args__ = (
        CheckConstraint("status IN ('new', 'assigned')", name="ck_inquiries_status"),
        CheckConstraint("business_type IS NULL OR business_type IN ('inquiry', 'after_sales')", name="ck_inquiries_business_type"),
        CheckConstraint("contact_identity_state IN ('certain', 'forwarded', 'identity_uncertain', 'needs_manual_review', 'unsupported')", name="ck_inquiries_contact_identity_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_contact: Mapped[str] = mapped_column(String(255), index=True)
    normalized_customer_contact: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    contact_identity_state: Mapped[str] = mapped_column(String(32), nullable=False, default="needs_manual_review", index=True)
    contact_identity_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    customer_nickname: Mapped[str] = mapped_column(String(255))
    raw_message: Mapped[str] = mapped_column(Text)
    source_channel_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("channel_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)
    business_type: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    handling_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    assigned_sales_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    source_channel_account: Mapped[ChannelAccount | None] = relationship(back_populates="inquiries")
    attachments: Mapped[list["InquiryAttachment"]] = relationship(
        back_populates="inquiry", cascade="all, delete-orphan"
    )
    notifications: Mapped[list["InternalNotification"]] = relationship(
        back_populates="inquiry", cascade="all, delete-orphan"
    )
    events: Mapped[list["InquiryEvent"]] = relationship(
        back_populates="inquiry", cascade="all, delete-orphan"
    )
    message_links: Mapped[list["InquiryMessage"]] = relationship(
        back_populates="inquiry", cascade="all, delete-orphan", order_by="InquiryMessage.position"
    )


class InquiryEvent(Base):
    __tablename__ = "inquiry_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('inquiry_created', 'inquiry_transferred', 'inquiry_processed', 'inquiry_ignored', 'inquiry_reactivated', 'inquiry_message_linked', 'manual_link')",
            name="ck_inquiry_events_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inquiry_id: Mapped[int] = mapped_column(
        ForeignKey("inquiries.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    target_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    inquiry: Mapped[Inquiry] = relationship(back_populates="events")


class InquiryAttachment(Base):
    __tablename__ = "inquiry_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inquiry_id: Mapped[int] = mapped_column(ForeignKey("inquiries.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_reference: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    inquiry: Mapped[Inquiry] = relationship(back_populates="attachments")


class InternalNotification(Base):
    __tablename__ = "internal_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inquiry_id: Mapped[int] = mapped_column(ForeignKey("inquiries.id", ondelete="CASCADE"), index=True)
    notification_type: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)

    inquiry: Mapped[Inquiry] = relationship(back_populates="notifications")


class InquiryMessage(Base):
    """A link from one inquiry to one source message; message data stays canonical."""

    __tablename__ = "inquiry_messages"
    __table_args__ = (
        PrimaryKeyConstraint("inquiry_id", "message_id", name="pk_inquiry_messages"),
        ForeignKeyConstraint(
            ["inquiry_id"], ["inquiries.id"],
            name="fk_inquiry_messages_inquiry_id_inquiries",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["message_id"], ["messages.id"],
            name="fk_inquiry_messages_message_id_messages",
            ondelete="CASCADE",
        ),
        CheckConstraint("position > 0", name="ck_inquiry_messages_position_positive"),
        UniqueConstraint("message_id", name="uq_inquiry_messages_message_id"),
        UniqueConstraint("inquiry_id", "position", name="uq_inquiry_messages_position"),
    )
    inquiry_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    link_source: Mapped[str] = mapped_column(String(32), nullable=False, default="inbound_match")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    inquiry: Mapped[Inquiry] = relationship(back_populates="message_links")
    message: Mapped["Message"] = relationship(back_populates="inquiry_link")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_handling_occurred_id", "handling_status", "occurred_at", "id"),
        Index("ix_messages_account_handling_occurred_id", "channel_account_id", "handling_status", "occurred_at", "id"),
        CheckConstraint("direction IN ('inbound', 'outbound')", name="ck_messages_direction"),
        CheckConstraint("status IN ('received', 'processed', 'failed')", name="ck_messages_status"),
        CheckConstraint("handling_status IN ('pending', 'processed', 'ignored')", name="ck_messages_handling_status"),
        CheckConstraint("link_state IN ('pending', 'linked', 'unmatched', 'manual_review', 'not_linkable')", name="ck_messages_link_state"),
        CheckConstraint("contact_identity_state IN ('certain', 'forwarded', 'identity_uncertain', 'needs_manual_review', 'unsupported')", name="ck_messages_contact_identity_state"),
        UniqueConstraint(
            "channel_account_id",
            "provider",
            "external_message_id",
            name="uq_messages_account_provider_external_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_account_id: Mapped[int] = mapped_column(
        ForeignKey("channel_accounts.id"), index=True
    )
    provider: Mapped[str] = mapped_column(String(64), index=True)
    external_message_id: Mapped[str] = mapped_column(String(512))
    direction: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    handling_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_content: Mapped[str] = mapped_column(Text)
    customer_contact: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    normalized_customer_contact: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    contact_identity_state: Mapped[str] = mapped_column(String(32), nullable=False, default="certain", index=True)
    contact_identity_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    original_sender_contact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_website_form: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    customer_nickname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_web_link: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    test_only: Mapped[bool] = mapped_column(default=False, nullable=False)
    link_state: Mapped[str] = mapped_column(String(24), default="pending", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    channel_account: Mapped[ChannelAccount] = relationship()
    inquiry_link: Mapped[InquiryMessage | None] = relationship(
        back_populates="message", uselist=False, cascade="all, delete-orphan", passive_deletes=True
    )
    attachments: Mapped[list["MessageAttachment"]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )
    overview: Mapped["MessageOverview | None"] = relationship(
        back_populates="message", uselist=False, cascade="all, delete-orphan"
    )


class MessageAttachment(Base):
    __tablename__ = "message_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_reference: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    message: Mapped[Message] = relationship(back_populates="attachments")


class OperationLog(Base):
    __tablename__ = "operation_logs"
    __table_args__ = (
        CheckConstraint("result IN ('success', 'failure', 'timeout')", name="ck_operation_logs_result"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    actor_name: Mapped[str] = mapped_column(String(64))
    operation_name: Mapped[str] = mapped_column(String(64), index=True)
    object_type: Mapped[str] = mapped_column(String(32))
    object_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[str] = mapped_column(String(16), index=True)
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class WhatsAppGroupBinding(Base):
    """Operator-confirmed mapping: one WhatsApp group JID -> one customer phone.

    This table is deliberately isolated from the inquiry-linking pipeline.
    Creating or changing a binding only writes here (plus OperationLog) and
    must never INSERT/UPDATE/DELETE messages, inquiries or inquiry_messages.
    """

    __tablename__ = "whatsapp_group_bindings"
    __table_args__ = (
        UniqueConstraint("group_jid", name="uq_whatsapp_group_bindings_group_jid"),
        CheckConstraint("normalized_phone LIKE '+%'", name="ck_whatsapp_group_bindings_phone_e164"),
        CheckConstraint("group_jid LIKE '%@g.us'", name="ck_whatsapp_group_bindings_group_jid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_jid: Mapped[str] = mapped_column(String(255), nullable=False)
    # Account that first made the group visible, used for authorization filtering.
    # Nullable to stay compatible with historical rows.
    channel_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("channel_accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    normalized_phone: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    raw_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bound_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# Register the one-to-one derived overview model whenever business models load.
from app.models.overview import MessageOverview  # noqa: E402,F401
