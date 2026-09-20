"""Shared Pytest fixtures for OmniEdge Sentinel test suite."""

import sys
from pathlib import Path

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from datetime import datetime, timezone

from src.core.events import InMemoryEventBus
from src.core.models import APCandidate, RFMetrics, SocketProbeMetrics
from src.engine.handover import HandoverExecutor
from src.engine.mcda_engine import MCDARoamingEngine
from src.ml.anomaly_detector import LinkAnomalyDetector
from src.ml.mlops_tracker import MLOpsTracker
from src.storage.sqlite_repository import SQLiteTelemetryRepository


@pytest.fixture
def temp_db(tmp_path: Path) -> SQLiteTelemetryRepository:
    db_file = tmp_path / "test_telemetry.db"
    return SQLiteTelemetryRepository(db_path=str(db_file))


@pytest.fixture
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def mcda_engine() -> MCDARoamingEngine:
    return MCDARoamingEngine(
        deadband_pct=0.15,
        hysteresis_cycles=3,
        warmup_duration_sec=4.0,
    )


@pytest.fixture
def mock_handover() -> HandoverExecutor:
    return HandoverExecutor(mock_mode=True, warmup_duration_sec=0.1)


@pytest.fixture
def anomaly_detector(tmp_path: Path) -> LinkAnomalyDetector:
    model_file = tmp_path / "test_detector.joblib"
    return LinkAnomalyDetector(model_path=str(model_file))


@pytest.fixture
def mlops_tracker(tmp_path: Path) -> MLOpsTracker:
    reg_dir = tmp_path / "test_registry"
    return MLOpsTracker(registry_dir=str(reg_dir))


@pytest.fixture
def sample_rf_metrics() -> RFMetrics:
    return RFMetrics(
        ssid="Telyexpress_Solares",
        bssid="c0:25:2f:5e:7e:42",
        rssi_dbm=-52.0,
        signal_pct=87,
        channel=1,
        band="2.4 GHz",
        radio_type="802.11n",
        mcs_index=7,
        rx_rate_mbps=144.4,
        tx_rate_mbps=144.4,
        airtime_utilization_pct=34.0,
        connected_stations=11,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_candidates() -> list[APCandidate]:
    return [
        APCandidate(
            ssid="Telyexpress_Solares",
            bssid="c0:25:2f:5e:7e:42",
            rssi_dbm=-52.0,
            signal_pct=87,
            channel=1,
            band="2.4 GHz",
            airtime_utilization_pct=34.0,
            is_current=True,
        ),
        APCandidate(
            ssid="Telyexpress_Pablo",
            bssid="c0:25:2f:72:9e:4c",
            rssi_dbm=-71.0,
            signal_pct=72,
            channel=10,
            band="2.4 GHz",
            airtime_utilization_pct=22.0,
            is_current=False,
        ),
    ]


@pytest.fixture
def sample_probes() -> list[SocketProbeMetrics]:
    return [
        SocketProbeMetrics(
            target_name="gateway",
            target_ip="192.168.0.1",
            rtt_ms=2.4,
            jitter_ms=0.8,
            packet_loss_pct=0.0,
            tcp_handshake_ms=3.1,
            is_reachable=True,
        ),
        SocketProbeMetrics(
            target_name="cpe_outdoor",
            target_ip="192.168.150.1",
            rtt_ms=4.8,
            jitter_ms=1.2,
            packet_loss_pct=0.0,
            tcp_handshake_ms=6.2,
            is_reachable=True,
        ),
        SocketProbeMetrics(
            target_name="public_dns",
            target_ip="8.8.8.8",
            rtt_ms=28.5,
            jitter_ms=4.1,
            packet_loss_pct=0.0,
            tcp_handshake_ms=34.0,
            dns_resolution_ms=12.0,
            is_reachable=True,
        ),
    ]
