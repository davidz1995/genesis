import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Protocol

from genesis.models import SubtitleEvent


class SubtitleBus(Protocol):
    async def publish(self, event: SubtitleEvent) -> None: ...

    def subscribe(self, session_id: str) -> AsyncIterator[SubtitleEvent]: ...


class InProcessBus:
    """Bus en memoria. La interfaz es la de SubtitleBus, reemplazable por Redis."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[SubtitleEvent]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def publish(self, event: SubtitleEvent) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(event.session_id, ()))
        for queue in queues:
            await queue.put(event)

    async def subscribe(self, session_id: str) -> AsyncIterator[SubtitleEvent]:
        queue: asyncio.Queue[SubtitleEvent] = asyncio.Queue()
        async with self._lock:
            self._subscribers[session_id].add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                self._subscribers[session_id].discard(queue)
                if not self._subscribers[session_id]:
                    del self._subscribers[session_id]
