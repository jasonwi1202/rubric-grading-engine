"""ContactInquiry ORM model.

Stores inbound school/district purchase inquiries submitted through the
pricing page form.  No student PII is collected or stored here.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class ContactInquiry(Base):
    """A school or district purchase inquiry submitted from the pricing page."""

    __tablename__ = "contact_inquiries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    school_name: Mapped[str] = mapped_column(String(300), nullable=False)
    district: Mapped[str | None] = mapped_column(String(300), nullable=True)
    estimated_teachers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # IP address of the submitter — stored for rate-limit auditing only.
    # This is not student PII.
    submitter_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
