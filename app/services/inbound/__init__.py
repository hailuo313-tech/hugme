"""Inbound schema and channel adapters (C-04 / P1-13+)."""

from services.inbound.adapter_protocol import AdapterError, ChannelAdapter, enqueue_standard_inbound
from services.inbound.envelope import (
    StandardInboundEnvelope,
    from_legacy_http_inbound,
    load_schema_spec,
    validate_against_schema_spec,
)

__all__ = [
    "AdapterError",
    "ChannelAdapter",
    "StandardInboundEnvelope",
    "enqueue_standard_inbound",
    "from_legacy_http_inbound",
    "load_schema_spec",
    "validate_against_schema_spec",
]
