"""Standard inbound envelope (P1-13 / C-04) aligned with docs/schema_spec.json."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationInfo, field_validator

Platform = Literal["telegram_real_user", "telegram", "web", "app"]
MessageType = Literal[
    "text",
    "image",
    "audio",
    "voice",
    "document",
    "video",
    "sticker",
    "other",
]


class InboundMetadata(BaseModel):
    telegram_message_id: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    raw_update_id: Optional[str] = None

    model_config = {"extra": "allow"}


class StandardInboundEnvelope(BaseModel):
    platform: Platform
    external_user_id: str = Field(min_length=1, max_length=128)
    message_type: MessageType = "text"
    content: str = Field(max_length=8000)
    trace_id: str = Field(min_length=8, max_length=64)
    account_id: Optional[str] = Field(default=None, max_length=64)
    sender_phone: Optional[str] = None
    metadata: InboundMetadata = Field(default_factory=InboundMetadata)
    received_at: Optional[str] = None

    @field_validator("sender_phone")
    @classmethod
    def _phone_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        digits = v.lstrip("+")
        if not digits.isdigit() or not (6 <= len(digits) <= 20):
            raise ValueError("sender_phone must be 6-20 digits (optional leading +)")
        return v

    @field_validator("account_id")
    @classmethod
    def _mtproto_requires_account(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        platform = info.data.get("platform")
        if platform == "telegram_real_user" and not v:
            raise ValueError("account_id is required when platform is telegram_real_user")
        return v

    def to_queue_fields(self) -> dict[str, str]:
        """Flatten for Redis Stream XADD (string values)."""
        payload = self.model_dump(mode="json")
        payload["metadata"] = json.dumps(payload.get("metadata") or {}, ensure_ascii=False)
        return {k: str(v) for k, v in payload.items() if v is not None}


def schema_spec_path() -> Path:
    candidates = []
    if os.environ.get("SCHEMA_SPEC_PATH"):
        candidates.append(Path(os.environ["SCHEMA_SPEC_PATH"]))
    candidates.extend(
        [
            Path("/srv/ops-docs/schema_spec.json"),
            Path(__file__).resolve().parents[2] / "docs" / "schema_spec.json",
            Path(__file__).resolve().parents[3] / "docs" / "schema_spec.json",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def load_schema_spec() -> dict[str, Any]:
    return json.loads(schema_spec_path().read_text(encoding="utf-8"))


def validate_against_schema_spec(data: dict[str, Any]) -> list[str]:
    """Return issue strings; empty list means valid."""
    try:
        import jsonschema
    except ImportError as exc:
        return [f"jsonschema not installed: {exc}"]

    schema = load_schema_spec()
    validator = jsonschema.Draft202012Validator(schema)
    return [f"{'.'.join(str(p) for p in e.path) or '$'}: {e.message}" for e in validator.iter_errors(data)]


def from_legacy_http_inbound(
    *,
    channel: str,
    external_user_id: str,
    message_type: str,
    content: str,
    trace_id: str,
    metadata: Optional[dict[str, Any]] = None,
    account_id: Optional[str] = None,
    sender_phone: Optional[str] = None,
    received_at: Optional[str] = None,
) -> StandardInboundEnvelope:
    """Map D1-2 InboundMessageRequest (channel) to standard envelope (platform)."""
    allowed = {"telegram", "web", "app"}
    if channel not in allowed:
        raise ValueError(f"unsupported channel for envelope mapping: {channel}")
    _allowed_msg = {"text", "image", "audio", "voice", "document", "video", "sticker", "other"}
    return StandardInboundEnvelope(
        platform=channel,  # type: ignore[arg-type]
        external_user_id=external_user_id,
        message_type=message_type if message_type in _allowed_msg else "other",  # type: ignore[arg-type]
        content=content,
        trace_id=trace_id,
        account_id=account_id,
        sender_phone=sender_phone,
        metadata=InboundMetadata.model_validate(metadata or {}),
        received_at=received_at,
    )
