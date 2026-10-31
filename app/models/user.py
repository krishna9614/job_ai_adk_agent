import uuid
from datetime import datetime

from sqlalchemy import SmallInteger, String, func
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    auth_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    account_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )
    onboarding_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="not_started"
    )
    onboarding_step: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    profile: Mapped["UserProfile | None"] = relationship(  # noqa: F821
        back_populates="user", uselist=False, lazy="raise"
    )
