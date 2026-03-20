from datetime import UTC, datetime
from uuid import UUID, uuid7

from sqlalchemy import CheckConstraint, Column, DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class Pdf(SQLModel, table=True):
    __tablename__ = 'pdfs'  # type: ignore
    __table_args__ = (
        CheckConstraint('status = UPPER(status)', name='pdfs_status_uppercase_check'),
        CheckConstraint(
            "status IN ('QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED')",
            name='pdfs_status_check',
        ),
        Index('pdfs_status_created_at_idx', 'status', text('created_at DESC')),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    data: dict[str, object] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
    status: str = Field(
        default='QUEUED',
        sa_column=Column(String, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text('NOW()'),
        ),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text('NOW()'),
        ),
    )
