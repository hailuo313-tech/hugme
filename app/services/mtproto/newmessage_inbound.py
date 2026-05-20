"""MTProto NewMessage listener bridge for inbound_queue (P1-10)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from services.inbound.adapter_protocol import ChannelAdapter, enqueue_standard_inbound
from services.inbound.envelope import InboundMetadata, StandardInboundEnvelope

INBOUND_QUEUE_STREAM = "inbound_queue"
PLATFORM = "telegram_real_user"


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _isoformat(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return _as_str(value)


def _from_id_user_id(from_id: Any) -> Optional[str]:
    return _as_str(getattr(from_id, "user_id", None))


def _sender_phone(sender: Any) -> Optional[str]:
    phone = getattr(sender, "phone", None)
    if phone is None:
        return None
    phone_text = str(phone)
    if phone_text.startswith("+"):
        return phone_text
    return f"+{phone_text}" if phone_text.isdigit() else phone_text


def _message_type(message: Any) -> str:
    if getattr(message, "voice", None):
        return "voice"

    document = getattr(message, "document", None)
    mime_type = getattr(document, "mime_type", "") or getattr(message, "mime_type", "")
    if str(mime_type).startswith("audio/ogg"):
        return "voice"

    if getattr(message, "photo", None):
        return "image"

    if getattr(message, "audio", None):
        return "audio"

    if document is not None:
        return "document"

    return "text"


def _message_content(message: Any, message_type: str) -> str:
    text = getattr(message, "raw_text", None) or getattr(message, "text", None) or getattr(message, "message", None)
    if text:
        return str(text)
    if message_type == "image":
        return "[photo]"
    if message_type == "voice":
        return "[voice]"
    return ""


def _trace_id(message_id: Optional[str]) -> str:
    suffix = message_id or uuid4().hex[:8]
    return f"tg-real-{suffix}-{uuid4().hex[:12]}"


class MtprotoNewMessageAdapter(ChannelAdapter):
    """Normalize Telethon NewMessage events to the standard inbound envelope."""

    def __init__(self, *, account_id: str) -> None:
        if not account_id:
            raise ValueError("account_id is required")
        self.account_id = account_id

    @property
    def platform(self) -> str:
        return PLATFORM

    async def normalize(self, raw_event: Any) -> StandardInboundEnvelope:
        message = getattr(raw_event, "message", raw_event)
        sender = None
        if hasattr(raw_event, "get_sender"):
            sender = await raw_event.get_sender()

        sender_id = (
            _as_str(getattr(message, "sender_id", None))
            or _as_str(getattr(raw_event, "sender_id", None))
            or _from_id_user_id(getattr(message, "from_id", None))
        )
        if not sender_id:
            raise ValueError("NewMessage event has no sender id")

        message_id = _as_str(getattr(message, "id", None) or getattr(raw_event, "id", None))
        chat_id = _as_str(getattr(message, "chat_id", None) or getattr(raw_event, "chat_id", None))
        msg_type = _message_type(message)

        envelope = StandardInboundEnvelope(
            platform=PLATFORM,
            external_user_id=f"tg_{sender_id}",
            message_type=msg_type,  # type: ignore[arg-type]
            content=_message_content(message, msg_type),
            trace_id=_trace_id(message_id),
            account_id=self.account_id,
            sender_phone=_sender_phone(sender),
            metadata=InboundMetadata(
                telegram_message_id=message_id,
                telegram_chat_id=chat_id,
                idempotency_key=f"{self.account_id}:{chat_id or sender_id}:{message_id or uuid4().hex}",
                raw_update_id=_as_str(getattr(raw_event, "original_update", None)),
                media_kind=msg_type if msg_type != "text" else None,
            ),
            received_at=_isoformat(getattr(message, "date", None)),
        )
        self.validate_envelope(envelope)
        return envelope


async def enqueue_new_message(
    redis: Any,
    raw_event: Any,
    *,
    account_id: str,
    stream: str = INBOUND_QUEUE_STREAM,
    maxlen: int = 100_000,
) -> tuple[str, StandardInboundEnvelope]:
    """Normalize a Telethon NewMessage event and enqueue it to Redis Stream."""
    adapter = MtprotoNewMessageAdapter(account_id=account_id)
    envelope = await adapter.normalize(raw_event)
    queue_id = await enqueue_standard_inbound(redis, stream, envelope, maxlen=maxlen)
    return queue_id, envelope
