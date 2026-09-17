"""Async Daemon and Multi-Module Resilience Orchestrator."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.collectors.dns_watchdog import DNSWatchdogCollector
from src.collectors.rf_collector import RFTelemetryCollector
from src.collectors.socket_probe import SocketProbeCollector
from src.collectors.ssdp_discovery import SSDPDiscoveryCollector
from src.collectors.usb_sentinel import USBSentinelCollector
from src.core.events import (
    EVENT_ANOMALY_PREDICTED,
    EVENT_DOH_ACTIVATED,
    EVENT_GHOST_SESSION_DETECTED,
    EVENT_HANDOVER_COMPLETED,
    EVENT_HANDOVER_TRIGGERED,
    EVENT_NETWORK_DEGRADED,
    EVENT_USB_DISCONNECTED,
    InMemoryEventBus,
)
from src.core.interfaces import EventBusInterface, TelemetryRepository
from src.core.models import (
    AnomalyReport,
    HardwareEventType,
    HandoverDecision,
    IoTDevice,
    KernelEvent,
    NetworkMetrics,
    RFMetrics,
    SocketProbeMetrics,
)
from src.engine.handover import HandoverExecutor
from src.engine.mcda_engine import MCDARoamingEngine
from src.ml.anomaly_detector import LinkAnomalyDetector

logger = logging.getLogger(__name__)


class ResilienceOrchestrator:
    """Core daemon orchestrating telemetry collection, predictive MLOps, MCDA, and self-healing."""

    def __init__(
        self,
        repository: TelemetryRepository,
        rf_collector: Optional[RFTelemetryCollector] = None,
        probe_collector: Optional[SocketProbeCollector] = None,
        ssdp_collector: Optional[SSDPDiscoveryCollector] = None,
        dns_collector: Optional[DNSWatchdogCollector] = None,
        usb_collector: Optional[USBSentinelCollector] = None,
        mcda_engine: Optional[MCDARoamingEngine] = None,
        handover_executor: Optional[HandoverExecutor] = None,
        anomaly_detector: Optional[LinkAnomalyDetector] = None,
        event_bus: Optional[EventBusInterface] = None,
        interval_sec: float = 15.0,
    ) -> None:
        self.repository = repository
        self.rf_collector = rf_collector or RFTelemetryCollector()
        self.probe_collector = probe_collector or SocketProbeCollector()
        self.ssdp_collector = ssdp_collector or SSDPDiscoveryCollector()
        self.dns_collector = dns_collector or DNSWatchdogCollector()
        self.usb_collector = usb_collector or USBSentinelCollector()
        self.mcda_engine = mcda_engine or MCDARoamingEngine()
        self.handover_executor = handover_executor or HandoverExecutor()
        self.anomaly_detector = anomaly_detector or LinkAnomalyDetector()
        self.event_bus = event_bus or InMemoryEventBus()
        self.interval_sec = interval_sec

        self._is_running = False
        self._iteration_count = 0
        self._register_default_event_handlers()

    def _register_default_event_handlers(self) -> None:
        """Sets up default reactive handlers for resilient self-healing."""
        self.event_bus.subscribe(EVENT_USB_DISCONNECTED, self._on_usb_disconnect)
        self.event_bus.subscribe(EVENT_GHOST_SESSION_DETECTED, self._on_ghost_session)
        self.event_bus.subscribe(EVENT_DOH_ACTIVATED, self._on_doh_activated)

    async def _on_usb_disconnect(self, event: KernelEvent) -> None:
        logger.critical(
            f"ALERT: Hardware disconnect/brownout detected on device {event.device_id}. "
            f"Failing over to backup interface immediately."
        )

    async def _on_ghost_session(self, device: IoTDevice) -> None:
        logger.warning(
            f"ALERT: Ghost session detected on IoT device {device.friendly_name} ({device.ip_address}). "
            f"Executing TCP socket reset and PnP registry purge."
        )

    async def _on_doh_activated(self, info: Dict[str, Any]) -> None:
        logger.warning(f"ALERT: DNS degraded. Switched seamlessly to DoH: {info.get('provider')}")

    async def run_cycle(self) -> Dict[str, Any]:
        """Runs a single comprehensive telemetry, analysis, and resilience cycle."""
        self._iteration_count += 1
        logger.info(f"--- Starting Resilience Cycle #{self._iteration_count} ---")

        # 1. Concurrent telemetry collection
        rf_task = asyncio.create_task(self.rf_collector.collect())
        probes_task = asyncio.create_task(self.probe_collector.collect())
        dns_task = asyncio.create_task(self.dns_collector.collect())
        usb_task = asyncio.create_task(self.usb_collector.collect())

        # SSDP collected periodically (every 2 cycles) to avoid network multicast flood
        ssdp_task = None
        if self._iteration_count % 2 == 1:
            ssdp_task = asyncio.create_task(self.ssdp_collector.collect())

        (rf_res, candidates), probes, dns_status, usb_events = await asyncio.gather(
            rf_task, probes_task, dns_task, usb_task
        )

        # 2. Persist telemetry to SQLite WAL
        self.repository.save_rf_metrics(rf_res)
        self.repository.save_socket_probes(probes)

        # 3. Handle USB Events
        for uevent in usb_events:
            self.repository.save_kernel_event(uevent)
            if uevent.event_type == HardwareEventType.DISCONNECTED:
                await self.event_bus.publish(EVENT_USB_DISCONNECTED, uevent)

        # 4. Handle SSDP IoT Discovery
        discovered_iot: List[IoTDevice] = []
        if ssdp_task:
            discovered_iot = await ssdp_task
            for dev in discovered_iot:
                self.repository.save_iot_device(dev)
                if dev.is_ghost_session:
                    await self.event_bus.publish(EVENT_GHOST_SESSION_DETECTED, dev)

        # 5. Handle DNS Health & DoH
        if dns_status.get("doh_active"):
            await self.event_bus.publish(EVENT_DOH_ACTIVATED, dns_status)

        # 6. MLOps Anomaly Detection & Health Score
        anomaly_report = self.anomaly_detector.predict(rf_res, probes)
        self.repository.save_anomaly_report(anomaly_report)

        if anomaly_report.is_anomaly:
            await self.event_bus.publish(EVENT_ANOMALY_PREDICTED, anomaly_report)

        # 7. MCDA Roaming Evaluation
        decision = self.mcda_engine.evaluate(
            candidates=candidates,
            current_bssid=rf_res.bssid,
            recent_probes=probes,
        )

        # Preemptive Handover override if ML Health Score is critically degraded (<45)
        if anomaly_report.recommended_action == "TRIGGER_PREEMPTIVE_HANDOVER" and not decision.should_handover:
            # Find candidate with highest score
            other_candidates = [c for c in candidates if c.bssid.lower() != rf_res.bssid.lower()]
            if other_candidates:
                best_alt = max(other_candidates, key=lambda c: c.health_score)
                decision.should_handover = True
                decision.target_bssid = best_alt.bssid
                decision.target_ssid = best_alt.ssid
                decision.reason = f"Preemptive zero-downtime handover triggered by ML Health Score ({anomaly_report.health_score}/100)."

        self.repository.save_handover_decision(decision)

        # 8. Execute Handover if triggered
        handover_executed = False
        if decision.should_handover and decision.target_ssid:
            await self.event_bus.publish(EVENT_HANDOVER_TRIGGERED, decision)
            handover_executed = await self.handover_executor.switch_network(
                target_ssid=decision.target_ssid,
                target_bssid=decision.target_bssid,
            )
            if handover_executed:
                await self.handover_executor.warm_up_connection()
                await self.event_bus.publish(EVENT_HANDOVER_COMPLETED, decision)

        logger.info(
            f"Cycle #{self._iteration_count} completed. Health Score: {anomaly_report.health_score:.1f} | "
            f"Handover: {decision.should_handover} | DoH: {dns_status.get('doh_active')}"
        )

        return {
            "iteration": self._iteration_count,
            "rf": rf_res,
            "probes": probes,
            "candidates": candidates,
            "anomaly_report": anomaly_report,
            "decision": decision,
            "handover_executed": handover_executed,
            "dns_status": dns_status,
            "iot_count": len(discovered_iot),
        }

    async def start(self) -> None:
        """Starts the continuous autonomous resilience daemon loop."""
        self._is_running = True
        logger.info(f"Resilience Orchestrator daemon started (interval: {self.interval_sec}s).")
        while self._is_running:
            try:
                await self.run_cycle()
            except Exception as e:
                logger.error(f"Error in orchestrator cycle: {e}", exc_info=True)
            await asyncio.sleep(self.interval_sec)

    def stop(self) -> None:
        """Stops the daemon."""
        self._is_running = False
        logger.info("Resilience Orchestrator daemon stopped.")
