"""Integration tests for Resilience Orchestrator and event-driven self-healing."""

import pytest
from unittest.mock import AsyncMock

from src.collectors.dns_watchdog import DNSWatchdogCollector
from src.collectors.rf_collector import RFTelemetryCollector
from src.collectors.socket_probe import SocketProbeCollector
from src.collectors.ssdp_discovery import SSDPDiscoveryCollector
from src.collectors.usb_sentinel import USBSentinelCollector
from src.core.events import InMemoryEventBus
from src.core.models import APCandidate, RFMetrics
from src.engine.handover import HandoverExecutor
from src.engine.mcda_engine import MCDARoamingEngine
from src.engine.orchestrator import ResilienceOrchestrator
from src.ml.anomaly_detector import LinkAnomalyDetector


@pytest.mark.asyncio
async def test_orchestrator_single_cycle(temp_db, mcda_engine, mock_handover, anomaly_detector):
    bus = InMemoryEventBus()

    orchestrator = ResilienceOrchestrator(
        repository=temp_db,
        rf_collector=RFTelemetryCollector(),
        probe_collector=SocketProbeCollector(mock_mode=True),
        ssdp_collector=SSDPDiscoveryCollector(mock_mode=True),
        dns_collector=DNSWatchdogCollector(mock_mode=True),
        usb_collector=USBSentinelCollector(mock_mode=True),
        mcda_engine=mcda_engine,
        handover_executor=mock_handover,
        anomaly_detector=anomaly_detector,
        event_bus=bus,
    )

    result = await orchestrator.run_cycle()
    assert result["iteration"] == 1
    assert result["rf"] is not None
    assert len(result["probes"]) == 3
    assert result["anomaly_report"] is not None
    assert result["decision"] is not None

    # Check persistence
    saved_rf = temp_db.get_recent_rf_metrics(limit=1)
    assert len(saved_rf) == 1
    saved_probes = temp_db.get_recent_probes(limit=5)
    assert len(saved_probes) == 3


@pytest.mark.asyncio
async def test_orchestrator_preemptive_handover_on_critical_ml_health(temp_db, mock_handover):
    bus = InMemoryEventBus()
    mcda = MCDARoamingEngine()
    detector = LinkAnomalyDetector()

    # Create collectors with candidates where current AP is degraded
    candidates = [
        APCandidate(ssid="Solares", bssid="c0:25:2f:5e:7e:42", rssi_dbm=-95.0, signal_pct=10, channel=1, band="2.4 GHz", airtime_utilization_pct=90.0, is_current=True),
        APCandidate(ssid="Pablo", bssid="c0:25:2f:72:9e:4c", rssi_dbm=-65.0, signal_pct=72, channel=10, band="2.4 GHz", airtime_utilization_pct=25.0, is_current=False),
    ]
    rf_degraded = RFMetrics(
        ssid="Solares",
        bssid="c0:25:2f:5e:7e:42",
        rssi_dbm=-95.0,
        signal_pct=10,
        airtime_utilization_pct=90.0,
    )

    rf_mock = RFTelemetryCollector()
    rf_mock.collect = AsyncMock(return_value=(rf_degraded, candidates))

    orchestrator = ResilienceOrchestrator(
        repository=temp_db,
        rf_collector=rf_mock,
        probe_collector=SocketProbeCollector(mock_mode=True),
        ssdp_collector=SSDPDiscoveryCollector(mock_mode=True),
        dns_collector=DNSWatchdogCollector(mock_mode=True),
        usb_collector=USBSentinelCollector(mock_mode=True),
        mcda_engine=mcda,
        handover_executor=mock_handover,
        anomaly_detector=detector,
        event_bus=bus,
    )

    result = await orchestrator.run_cycle()
    # When health score is critically degraded, preemptive zero-downtime handover should trigger
    assert result["decision"].should_handover is True
    assert result["decision"].target_ssid == "Pablo"
    assert result["handover_executed"] is True
