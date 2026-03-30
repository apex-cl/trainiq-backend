import uuid
from datetime import datetime, date, timezone
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, Date, Integer, Float, JSON, Boolean
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    avatar_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    height_cm: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    preferred_language: Mapped[str] = mapped_column(String, default="de")

    notification_settings: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    marketing_consent: Mapped[bool] = mapped_column(Boolean, default=False)

    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_token: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    verification_expires: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    two_factor_secret: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    two_factor_backup_codes: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    subscription_tier: Mapped[Optional[str]] = mapped_column(String, default="free")

    keycloak_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    subscription_expires: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def age(self) -> Optional[int]:
        if self.birth_date:
            today = date.today()
            return (
                today.year
                - self.birth_date.year
                - (
                    (today.month, today.day)
                    < (self.birth_date.month, self.birth_date.day)
                )
            )
        return None
