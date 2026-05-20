"""Channel adapter contract for inbound_queue (C-04 / P1-14)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from services.inbound.envelope import StandardInboundEnvelope, validate_against_schema_spec


class AdapterError(ValueError):
    """Normalization or validation failed."""


@runtime_checkable
class ChannelAdapter(Protocol):
    """P1-14 implementations: Telethon MTProto, Bot webhook bridge, H5/App mock."""

    @property
    def platform(self) -> str:
        """Primary platform id this adapter emits (e.g. telegram_real_user)."""

    async def normalize(self, raw_event: Any) -> StandardInboundEnvelope:
        """Map provider-specific event to StandardInboundEnvelope."""

    def validate_envelope(self, envelope: StandardInboundEnvelope) -> None:
        """JSON Schema + pydantic checks before enqueue."""
        issues = validate_against_schema_spec(envelope.model_dump(mode="json"))
        if issues:
            raise AdapterError("; ".join(issues))


async def enqueue_standard_inbound(
    redis,
    stream: str,
    envelope: StandardInboundEnvelope,
    *,
    maxlen: int = 100_000,
) -> str:
    """XADD helper for P1-06 / P1-16 (reference; not wired in runtime yet)."""
    fields = envelope.to_queue_fields()
    return await redis.xadd(stream, fields, maxlen=maxlen)  # type: ignore[no-any-return]
