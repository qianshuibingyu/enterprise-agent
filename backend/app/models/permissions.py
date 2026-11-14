from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserCapabilityGrant(Base):
    __tablename__ = "user_capability_grants"
    __table_args__ = (
        UniqueConstraint("user_id", "capability", name="uq_user_capability_grant"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    capability: Mapped[str] = mapped_column(String(64), index=True)
    granted_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserDepartmentGrant(Base):
    __tablename__ = "user_department_grants"
    __table_args__ = (
        UniqueConstraint("user_id", "department", name="uq_user_department_grant"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    department: Mapped[str] = mapped_column(String(64), index=True)
    granted_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ManagerPermissionGrant(Base):
    """A narrowly scoped permission a manager grants to one employee."""
    __tablename__ = "manager_permission_grants"
    __table_args__ = (
        UniqueConstraint("manager_user_id", "target_user_id", "department", "permission", name="uq_manager_permission_grant"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manager_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    target_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    department: Mapped[str] = mapped_column(String(64), index=True)
    permission: Mapped[str] = mapped_column(String(64), index=True)
    granted_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserChannelPreauthorization(Base):
    __tablename__ = "user_channel_preauthorizations"
    __table_args__ = (
        UniqueConstraint("user_id", "channel_type", name="uq_user_channel_preauthorization"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel_type: Mapped[str] = mapped_column(String(32))
    granted_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


