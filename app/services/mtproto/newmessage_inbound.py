"""MTProto NewMessage listener bridge for inbound_queue (P1-10)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from services.inbound.adapter_protocol import ChannelAdapter, enqueue_standard_inbound
from services.inbound.envelope import InboundMetadata, StandardInboundEnvelope
from services.user_level_service import user_level_service

INBOUND_QUEUE_STREAM = "inbound_queue"
PLATFORM = "telegram_real_user"
TELEGRAM_MESSAGE_DEDUPE_TTL_SECONDS = 3600


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


def telegram_message_dedupe_key(user_id: str, message_id: str) -> str:
    """Redis idempotency key for Telegram real-user inbound messages."""
    if not user_id:
        raise ValueError("user_id is required")
    if not message_id:
        raise ValueError("message_id is required")
    return f"telegram_msg:{user_id}:{message_id}"


async def claim_telegram_message_once(
    redis: Any,
    *,
    user_id: str,
    message_id: str,
    ttl_seconds: int = TELEGRAM_MESSAGE_DEDUPE_TTL_SECONDS,
) -> bool:
    """Return True only for the first sighting within the TTL window."""
    key = telegram_message_dedupe_key(user_id, message_id)
    claimed = await redis.set(key, "1", ex=ttl_seconds, nx=True)
    return bool(claimed)


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
) -> tuple[str | None, StandardInboundEnvelope]:
    """Normalize a Telethon NewMessage event and enqueue it to Redis Stream."""
    adapter = MtprotoNewMessageAdapter(account_id=account_id)
    envelope = await adapter.normalize(raw_event)
    message_id = envelope.metadata.telegram_message_id
    if not message_id:
        raise ValueError("telegram_message_id is required for inbound dedupe")
    claimed = await claim_telegram_message_once(
        redis,
        user_id=envelope.external_user_id,
        message_id=message_id,
    )
    if not claimed:
        return None, envelope

    # P2-12: Integrate user level calculation into inbound pipeline
    try:
        envelope_dict = envelope.model_dump(mode="json")
        enriched_envelope_dict = await user_level_service.enrich_inbound_envelope_with_level(
            envelope_dict
        )
        # Update envelope with enriched metadata
        envelope = StandardInboundEnvelope(**enriched_envelope_dict)
        logger.info(
            f"User level integrated for {envelope.external_user_id}: "
            f"level={envelope.metadata.user_level}, route={envelope.metadata.chat_route}"
        )
    except Exception as e:
        logger.error(f"Error integrating user level, using original envelope: {e}")
        # Continue with original envelope if level calculation fails

    queue_id = await enqueue_standard_inbound(redis, stream, envelope, maxlen=maxlen)
    return queue_id, envelope
