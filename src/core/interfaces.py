"""Abstract interfaces and protocols adhering to Dependency Inversion (DIP) and SOLID."""

from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine, Dict, List, Optional
from src.core.models import (
    APCandidate,
    AnomalyReport,
    HandoverDecision,
    IoTDevice,
    KernelEvent,
    NetworkMetrics,
    RFMetrics,
    SocketProbeMetrics,
)


class BaseCollector(ABC):
    """Abstract collector for Edge telemetry gathering."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Collector identifier."""
        pass

    @abstractmethod
    async def collect(self) -> Any:
        """Collect telemetry data asynchronously."""
        pass


class TelemetryRepository(ABC):
    """Abstract persistence repository for Edge metrics storage."""

    @abstractmethod
    def initialize(self) -> None:
        """Initialize database schema, indexes and pragmas."""
        pass

    @abstractmethod
    def save_rf_metrics(self, metrics: RFMetrics) -> int:
        """Store RF physical and link telemetry."""
        pass

    @abstractmethod
    def save_socket_probes(self, probes: List[SocketProbeMetrics]) -> None:
        """Store socket and network transport latency metrics."""
        pass

    @abstractmethod
    def save_iot_device(self, device: IoTDevice) -> None:
        """Store or update discovered UPnP/SSDP device."""
        pass

    @abstractmethod
    def save_kernel_event(self, event: KernelEvent) -> None:
        """Store USB or PnP hardware event."""
        pass

    @abstractmethod
    def save_anomaly_report(self, report: AnomalyReport) -> None:
        """Store MLOps health and anomaly detection report."""
        pass

    @abstractmethod
    def save_handover_decision(self, decision: HandoverDecision) -> None:
        """Store MCDA roaming evaluation and execution result."""
        pass

    @abstractmethod
    def get_recent_rf_metrics(self, limit: int = 100) -> List[RFMetrics]:
        """Retrieve recent RF records."""
        pass

    @abstractmethod
    def get_recent_probes(self, limit: int = 100) -> List[SocketProbeMetrics]:
        """Retrieve recent socket probe latency records."""
        pass

    @abstractmethod
    def get_recent_anomalies(self, limit: int = 100) -> List[AnomalyReport]:
        """Retrieve recent anomaly records."""
        pass

    @abstractmethod
    def get_iot_devices(self) -> List[IoTDevice]:
        """Retrieve all active discovered IoT assets."""
        pass

    @abstractmethod
    def get_kernel_events(self, limit: int = 50) -> List[KernelEvent]:
        """Retrieve forensic hardware events."""
        pass

    @abstractmethod
    def get_handover_history(self, limit: int = 50) -> List[HandoverDecision]:
        """Retrieve handover event history."""
        pass


class DecisionStrategy(ABC):
    """Strategy pattern interface for network roaming decisions."""

    @abstractmethod
    def evaluate(
        self,
        candidates: List[APCandidate],
        current_bssid: str,
        recent_probes: Optional[List[SocketProbeMetrics]] = None,
    ) -> HandoverDecision:
        """Evaluate AP candidates and return roaming decision."""
        pass


class HandoverExecutorInterface(ABC):
    """Interface for physical Wi-Fi roaming handover execution."""

    @abstractmethod
    async def switch_network(self, target_ssid: str, target_bssid: Optional[str] = None) -> bool:
        """Perform zero-loss network transition."""
        pass

    @abstractmethod
    async def warm_up_connection(self, gateway_ip: str, duration_sec: float = 4.0) -> bool:
        """Stabilize link and populate ARP table post-handover."""
        pass


class EventBusInterface(ABC):
    """Pub-Sub event bus interface for decoupled cross-module communication."""

    @abstractmethod
    def subscribe(self, event_type: str, handler: Callable[[Any], Coroutine[Any, Any, None]]) -> None:
        """Register an async handler for a given event type."""
        pass

    @abstractmethod
    async def publish(self, event_type: str, payload: Any) -> None:
        """Publish an event to all registered handlers."""
        pass
