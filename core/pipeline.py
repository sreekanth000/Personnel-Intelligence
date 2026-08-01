from abc import ABC, abstractmethod
import asyncio
from typing import Callable, Awaitable
from core.models import PipelineEvent


# Abstract interfaces for the event-driven pipeline
class EventBus(ABC):
    @abstractmethod
    async def publish(self, topic: str, event: PipelineEvent):
        pass

    @abstractmethod
    async def subscribe(
        self, topic: str, handler: Callable[[PipelineEvent], Awaitable[None]]
    ):
        pass


# A simple asyncio-based implementation for v1
class AsyncQueueEventBus(EventBus):
    def __init__(self):
        self._queues = {}
        self._handlers = {}

    async def publish(self, topic: str, event: PipelineEvent):
        if topic not in self._queues:
            self._queues[topic] = asyncio.Queue()
        await self._queues[topic].put(event)

    async def subscribe(
        self, topic: str, handler: Callable[[PipelineEvent], Awaitable[None]]
    ):
        if topic not in self._handlers:
            self._handlers[topic] = []
        self._handlers[topic].append(handler)

        # Start a worker task if not already running for this topic
        # In a real system, you'd manage these tasks more carefully
        asyncio.create_task(self._worker(topic))

    async def _worker(self, topic: str):
        if topic not in self._queues:
            self._queues[topic] = asyncio.Queue()
        while True:
            event = await self._queues[topic].get()
            for handler in self._handlers.get(topic, []):
                try:
                    await handler(event)
                except Exception as e:
                    print(f"Error handling event {event.id} on topic {topic}: {e}")
            self._queues[topic].task_done()


class PipelineComponent(ABC):
    def __init__(self, bus: EventBus):
        self.bus = bus

    @abstractmethod
    async def process(self, event: PipelineEvent) -> None:
        """Process an incoming event. Subclasses must implement this."""
        pass
