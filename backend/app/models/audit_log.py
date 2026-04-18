"""AuditLog ORM model.

Append-only record of every consequential action.  This table must NEVER be
updated or deleted — insert only.  See ``docs/architecture/data-model.md``
for the full action catalog and SOC 2 requirements.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class AuditLog(Base):
    """An immutable audit log entry.  INSERT-only — never UPDATE or DELETE."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    # Nullable — system-generated events (e.g., score_clamped) may have no
    # acting teacher.  Auth events (login, logout) reference the teacher that
    # performed the action; signup events have no teacher yet.
    teacher_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    # e.g. "grade", "criterion_score", "essay", "auth", "export", "user"
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Nullable — some events (login_failure, account_created) do not reference
    # a specific application entity with a UUID.
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    # See action catalog in docs/architecture/data-model.md#auditlog
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    # State before and after the change — NULL for events without a state delta.
    before_value: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    after_value: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    # Client IP for auth and data-access events.
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    # Extra free-form metadata that doesn't fit before/after (e.g. user-agent).
    metadata_: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
