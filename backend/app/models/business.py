from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


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
    inquiries: Mapped[list["Inquiry"]] = relationship(back_populates="source_channel_account")


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
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_contact: Mapped[str] = mapped_column(String(255))
    customer_nickname: Mapped[str] = mapped_column(String(255))
    raw_message: Mapped[str] = mapped_column(Text)
    source_channel_account_id: Mapped[int] = mapped_column(
        ForeignKey("channel_accounts.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)
    handling_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    assigned_sales_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    source_channel_account: Mapped[ChannelAccount] = relationship(back_populates="inquiries")
    attachments: Mapped[list["InquiryAttachment"]] = relationship(
        back_populates="inquiry", cascade="all, delete-orphan"
    )
    notifications: Mapped[list["InternalNotification"]] = relationship(
        back_populates="inquiry", cascade="all, delete-orphan"
    )
    events: Mapped[list["InquiryEvent"]] = relationship(
        back_populates="inquiry", cascade="all, delete-orphan"
    )


class InquiryEvent(Base):
    __tablename__ = "inquiry_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('inquiry_created', 'inquiry_transferred', 'inquiry_processed', 'inquiry_ignored')",
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


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("direction IN ('inbound', 'outbound')", name="ck_messages_direction"),
        CheckConstraint("status IN ('received', 'processed', 'failed')", name="ck_messages_status"),
        CheckConstraint("handling_status IN ('pending', 'processed', 'ignored')", name="ck_messages_handling_status"),
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
    customer_nickname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_web_link: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    channel_account: Mapped[ChannelAccount] = relationship()
    attachments: Mapped[list["MessageAttachment"]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
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
