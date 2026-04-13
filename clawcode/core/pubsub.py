"""Core event system for pubsub pattern.

This module provides a generic, async event broker implementation
that allows components to subscribe to and publish events.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Generic,
    Protocol,
    TypeVar,
)

T = TypeVar("T")


class EventType(str, Enum):
    """Event type enumeration."""

    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    ERROR = "error"


@dataclass(frozen=True)
class Event(Generic[T]):
    """Generic event wrapper.

    Args:
        type: The event type
        payload: The event payload
        timestamp: Unix timestamp when event was created
    """

    type: EventType
    payload: T
    timestamp: float = field(default_factory=lambda: __import__("time").time())

    def __post_init__(self) -> None:
        # Ensure timestamp is set correctly for frozen dataclass
        if self.timestamp == 0:
            object.__setattr__(self, "timestamp", __import__("time").time())


type EventHandler[T] = Callable[[Event[T]], Awaitable[None]]
type EventFilter[T] = Callable[[Event[T]], bool]


class Broker(Generic[T]):
    """Async event broker for pubsub pattern.

    The broker manages event subscriptions and distributes events
    to all registered subscribers asynchronously.

    Example:
        broker = Broker[Message]()

        @broker.subscribe
        async def handle_message(event: Event[Message]) -> None:
            print(f"Got message: {event.payload}")

        await broker.publish(EventType.CREATED, message)
    """

    def __init__(
        self,
        max_queue_size: int = 1000,
        max_buffer_size: int = 100,
    ) -> None:
        """Initialize the broker.

        Args:
            max_queue_size: Maximum size for internal event queue
            max_buffer_size: Maximum events to buffer per subscriber
        """
        self._subscribers: dict[EventHandler[T], asyncio.Queue[Event[T]]] = {}
        self._filters: dict[EventHandler[T], list[EventFilter[T]]] = {}
        self._queue: asyncio.Queue[Event[T] | None] = asyncio.Queue(
            maxsize=max_queue_size
        )
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._max_buffer_size = max_buffer_size
        self._notify: asyncio.Event = asyncio.Event()

    def subscribe(
        self,
        handler: EventHandler[T] | None = None,
        *,
        filter: EventFilter[T] | None = None,
    ) -> Callable[[EventHandler[T]], EventHandler[T]] | None:
        """Subscribe to events from this broker.

        Can be used as a decorator or directly.

        Args:
            handler: The event handler function
            filter: Optional filter to selectively receive events

        Returns:
            If used as decorator (handler is None), returns the decorator function.
            Otherwise, returns None.

        Example:
            @broker.subscribe
            async def handler(event: Event[T]) -> None:
                ...

            # Or with filter
            @broker.subscribe(filter=lambda e: e.payload.is_important)
            async def handler(event: Event[T]) -> None:
                ...
        """

        def decorator(handler: EventHandler[T]) -> EventHandler[T]:
            self._subscribers[handler] = asyncio.Queue(
                maxsize=self._max_buffer_size
            )
            if filter:
                self._filters[handler] = [filter]
            else:
                self._filters[handler] = []
            return handler

        if handler is not None:
            return decorator(handler)
        return decorator

    def unsubscribe(self, handler: EventHandler[T]) -> None:
        """Unsubscribe a handler from events.

        Args:
            handler: The handler to unsubscribe
        """
        self._subscribers.pop(handler, None)
        self._filters.pop(handler, None)

    async def publish(self, event_type: EventType, payload: T) -> int:
        """Publish an event to all subscribers.

        Args:
            event_type: The type of event
            payload: The event payload

        Returns:
            Number of subscribers the event was published to
        """
        event = Event(type=event_type, payload=payload)

        count = 0
        for handler, queue in self._subscribers.items():
            # Apply filters
            if any(f(event) for f in self._filters[handler]):
                try:
                    queue.put_nowait(event)
                    count += 1
                except asyncio.QueueFull:
                    pass

        if count > 0:
            self._notify.set()

        return count

    async def start(self) -> None:
        """Start the event processing loop."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._process_events())

    async def stop(self) -> None:
        """Stop the event processing loop."""
        if not self._running:
            return

        self._running = False
        # Signal the processing loop to stop
        await self._queue.put(None)

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _process_events(self) -> None:
        """Process events from subscriber queues, driven by asyncio.Event."""
        tasks: set[asyncio.Task[None]] = set()

        try:
            while self._running:
                await self._notify.wait()
                self._notify.clear()

                for handler, queue in self._subscribers.items():
                    while not queue.empty():
                        event = queue.get_nowait()
                        if event is not None:
                            task = asyncio.create_task(handler(event))
                            tasks.add(task)
                            task.add_done_callback(tasks.discard)

        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def get_subscriber_count(self) -> int:
        """Get the number of active subscribers.

        Returns:
            Number of subscribers
        """
        return len(self._subscribers)

    def clear(self) -> None:
        """Clear all subscribers."""
        self._subscribers.clear()
        self._filters.clear()


class Subscriber(Protocol[T]):
    """Protocol for event subscribers."""

    async def on_event(self, event: Event[T]) -> None: ...


class AppEvents:
    """Unified event bus aggregating session, message, permission, and logging channels.

    Use this in app initialization so screens and services subscribe to a single
    event surface. Brokers are created lazily or passed in.
    """

    def __init__(
        self,
        session_broker: Broker[Any] | None = None,
        message_broker: Broker[Any] | None = None,
    ) -> None:
        self.session = session_broker or Broker()
        self.message = message_broker or Broker()
