import uuid
from datetime import datetime

from sqlalchemy import CHAR, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class UserProfile(Base):
    """Maps the v1 subset of ``jobai.user_profiles``; other columns are left untouched."""

    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    preferred_name: Mapped[str | None] = mapped_column(String(100))
    phone_country_code: Mapped[str | None] = mapped_column(String(8))
    phone_number: Mapped[str | None] = mapped_column(String(30))
    city: Mapped[str | None] = mapped_column(String(120))
    state_province: Mapped[str | None] = mapped_column(String(120))
    country_code: Mapped[str | None] = mapped_column(CHAR(2))
    professional_headline: Mapped[str | None] = mapped_column(String(250))
    professional_summary: Mapped[str | None] = mapped_column(Text)
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    github_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="profile", lazy="raise")  # noqa: F821
