"""Pub-Sub event bus and concrete domain events for decoupled resilience reactions."""

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List
from src.core.interfaces import EventBusInterface

logger = logging.getLogger(__name__)


# Event Names
EVENT_NETWORK_DEGRADED = "network.degraded"
EVENT_HANDOVER_TRIGGERED = "handover.triggered"
EVENT_HANDOVER_COMPLETED = "handover.completed"
EVENT_USB_DISCONNECTED = "hardware.usb.disconnected"
EVENT_USB_CONNECTED = "hardware.usb.connected"
EVENT_DNS_FAILED = "dns.resolution.failed"
EVENT_DOH_ACTIVATED = "dns.doh.activated"
EVENT_GHOST_SESSION_DETECTED = "iot.ghost_session.detected"
EVENT_ANOMALY_PREDICTED = "ml.anomaly.predicted"


class InMemoryEventBus(EventBusInterface):
    """Asynchronous in-memory Pub-Sub event bus."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable[[Any], Coroutine[Any, Any, None]]]] = {}

    def subscribe(self, event_type: str, handler: Callable[[Any], Coroutine[Any, Any, None]]) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
        logger.debug(f"Subscribed handler {handler.__name__} to event {event_type}")

    async def publish(self, event_type: str, payload: Any) -> None:
        handlers = self._subscribers.get(event_type, [])
        if not handlers:
            logger.debug(f"No handlers registered for event {event_type}")
            return

        logger.info(f"Publishing event {event_type} to {len(handlers)} handlers")
        tasks = []
        for handler in handlers:
            try:
                tasks.append(asyncio.create_task(handler(payload)))
            except Exception as e:
                logger.error(f"Error dispatching event {event_type} to {handler}: {e}")

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
