"""Stage 2 ORM mapping for command/ownership tables.

These models are not imported by startup. Consumers remain closed.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID as PyUUID
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class RuntimeSplitBase(DeclarativeBase):
    pass


class RuntimeInstance(RuntimeSplitBase):
    __tablename__ = "runtime_instances"

    id: Mapped[PyUUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    instance_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    process_role: Mapped[str] = mapped_column(String(32), nullable=False, default="all", server_default="all")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="starting", server_default="starting")
    hostname: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    pid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("process_role IN ('all', 'api', 'telegram_runtime')", name="check_runtime_instances_role"),
        CheckConstraint("status IN ('starting', 'ready', 'draining', 'stopped')", name="check_runtime_instances_status"),
        Index("idx_runtime_instances_heartbeat", "last_heartbeat_at"),
        Index("idx_runtime_instances_role_status", "process_role", "status"),
    )


class RuntimeCommand(RuntimeSplitBase):
    __tablename__ = "runtime_commands"

    id: Mapped[PyUUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    command_type: Mapped[str] = mapped_column(String(64), nullable=False)
    account_id: Mapped[Optional[PyUUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    conversation_id: Mapped[Optional[PyUUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    lease_owner: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    lease_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'leased', 'succeeded', 'failed', 'cancelled', 'expired')",
            name="check_runtime_commands_status",
        ),
        Index("idx_runtime_commands_idempotency", "idempotency_key", unique=True),
        Index("idx_runtime_commands_generation", "account_id", "generation"),
        Index("idx_runtime_commands_account_created", "account_id", "created_at"),
    )


class RuntimeEvent(RuntimeSplitBase):
    __tablename__ = "runtime_events"

    id: Mapped[PyUUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    command_id: Mapped[Optional[PyUUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    account_id: Mapped[Optional[PyUUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    generation: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    instance_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_runtime_events_command", "command_id", "created_at"),
        Index("idx_runtime_events_account_created", "account_id", "created_at"),
        Index("idx_runtime_events_type_created", "event_type", "created_at"),
    )


class TelegramAccountOwnership(RuntimeSplitBase):
    __tablename__ = "telegram_account_ownership"

    account_id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    owner: Mapped[str] = mapped_column(String(20), nullable=False, default="legacy", server_default="legacy")
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1")
    owner_instance_id: Mapped[Optional[PyUUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    lease_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    switch_status: Mapped[str] = mapped_column(String(20), nullable=False, default="stable", server_default="stable")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("owner IN ('legacy', 'runtime')", name="check_telegram_account_ownership_owner"),
        CheckConstraint(
            "switch_status IN ('stable', 'draining', 'switching')",
            name="check_telegram_account_ownership_switch",
        ),
        Index("idx_telegram_account_ownership_owner_generation", "owner", "generation"),
        Index("idx_telegram_account_ownership_instance", "owner_instance_id"),
    )
