"""MTProto channel adapter wiring Telethon NewMessage into inbound_queue."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from services.inbound.envelope import StandardInboundEnvelope
from services.mtproto.newmessage_inbound import (
    INBOUND_QUEUE_STREAM,
    PLATFORM,
    MtprotoNewMessageAdapter,
    enqueue_new_message,
)

NewMessageEventFactory = Callable[..., Any]
NewMessageHandler = Callable[[Any], Awaitable["MtprotoInboundResult"]]


@dataclass(frozen=True)
class MtprotoInboundResult:
    """Result returned by the registered MTProto inbound handler."""

    queue_id: Optional[str]
    envelope: StandardInboundEnvelope

    @property
    def enqueued(self) -> bool:
        return self.queue_id is not None


class MtprotoChannelAdapter:
    """P1-14 Telethon adapter from raw NewMessage events to inbound_queue."""

    def __init__(
        self,
        *,
        account_id: str,
        redis: Any,
        stream: str = INBOUND_QUEUE_STREAM,
        maxlen: int = 100_000,
    ) -> None:
        if not account_id:
            raise ValueError("account_id is required")
        self.account_id = account_id
        self.redis = redis
        self.stream = stream
        self.maxlen = maxlen
        self._normalizer = MtprotoNewMessageAdapter(account_id=account_id)

    @property
    def platform(self) -> str:
        return PLATFORM

    async def normalize(self, raw_event: Any) -> StandardInboundEnvelope:
        return await self._normalizer.normalize(raw_event)

    async def handle_new_message(self, raw_event: Any) -> MtprotoInboundResult:
        queue_id, envelope = await enqueue_new_message(
            self.redis,
            raw_event,
            account_id=self.account_id,
            stream=self.stream,
            maxlen=self.maxlen,
        )
        return MtprotoInboundResult(queue_id=queue_id, envelope=envelope)

    def build_handler(self) -> NewMessageHandler:
        async def _handler(raw_event: Any) -> MtprotoInboundResult:
            return await self.handle_new_message(raw_event)

        return _handler

    def register_new_message_handler(
        self,
        client: Any,
        *,
        event_factory: Optional[NewMessageEventFactory] = None,
    ) -> NewMessageHandler:
        """Register a Telethon NewMessage listener on the provided client."""
        handler = self.build_handler()
        factory = event_factory or _telethon_new_message_factory()
        client.add_event_handler(handler, factory(incoming=True))
        return handler


def _telethon_new_message_factory() -> NewMessageEventFactory:
    try:
        from telethon import events
    except ImportError as exc:
        raise RuntimeError("telethon is required to register MTProto NewMessage handlers") from exc
    return events.NewMessage


def register_mtproto_newmessage_listener(
    client: Any,
    redis: Any,
    *,
    account_id: str,
    stream: str = INBOUND_QUEUE_STREAM,
    maxlen: int = 100_000,
    event_factory: Optional[NewMessageEventFactory] = None,
) -> NewMessageHandler:
    """Convenience entry point used by MTProto account startup code."""
    adapter = MtprotoChannelAdapter(
        account_id=account_id,
        redis=redis,
        stream=stream,
        maxlen=maxlen,
    )
    return adapter.register_new_message_handler(client, event_factory=event_factory)
