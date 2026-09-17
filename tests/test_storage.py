"""Integration and concurrency tests for SQLite WAL Telemetry Repository."""

import threading
from datetime import datetime
from src.core.models import (
    AnomalyReport,
    HardwareEventType,
    HandoverDecision,
    IoTDevice,
    KernelEvent,
    RFMetrics,
    SocketProbeMetrics,
)
from src.storage.sqlite_repository import SQLiteTelemetryRepository


def test_sqlite_wal_pragmas(temp_db):
    with temp_db._get_connection() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        sync_mode = conn.execute("PRAGMA synchronous;").fetchone()[0]
        assert journal_mode.lower() == "wal"
        assert sync_mode == 1  # 1 = NORMAL


def test_rf_metrics_crud(temp_db, sample_rf_metrics):
    row_id = temp_db.save_rf_metrics(sample_rf_metrics)
    assert row_id > 0

    records = temp_db.get_recent_rf_metrics(limit=10)
    assert len(records) == 1
    assert records[0].ssid == "Telyexpress_Solares"
    assert records[0].bssid == "c0:25:2f:5e:7e:42"
    assert records[0].rssi_dbm == -52.0
    assert records[0].signal_pct == 87


def test_socket_probes_crud(temp_db, sample_probes):
    temp_db.save_socket_probes(sample_probes)
    probes = temp_db.get_recent_probes(limit=10)
    assert len(probes) == 3
    targets = {p.target_name for p in probes}
    assert "gateway" in targets
    assert "public_dns" in targets


def test_iot_device_upsert(temp_db):
    dev1 = IoTDevice(
        ip_address="192.168.0.45",
        port=1900,
        usn="uuid:test-01",
        st="upnp:rootdevice",
        friendly_name="Display-Original",
        is_ghost_session=False,
    )
    temp_db.save_iot_device(dev1)

    # Upsert with new name and ghost session state
    dev2 = IoTDevice(
        ip_address="192.168.0.45",
        port=1900,
        usn="uuid:test-01",
        st="upnp:rootdevice",
        friendly_name="Display-Updated",
        is_ghost_session=True,
    )
    temp_db.save_iot_device(dev2)

    devices = temp_db.get_iot_devices()
    assert len(devices) == 1
    assert devices[0].friendly_name == "Display-Updated"
    assert devices[0].is_ghost_session is True


def test_kernel_events_crud(temp_db):
    kevent = KernelEvent(
        event_id=2004,
        provider_name="Microsoft-Windows-UserPnpCtx",
        event_type=HardwareEventType.DISCONNECTED,
        device_id="USB\\VID_0BDA&PID_B852\\12345",
        vendor_id="0BDA",
        product_id="B852",
        serial_number="12345",
        device_description="Realtek RTL8852BE-VS",
    )
    temp_db.save_kernel_event(kevent)

    events = temp_db.get_kernel_events(limit=5)
    assert len(events) == 1
    assert events[0].event_type == HardwareEventType.DISCONNECTED
    assert events[0].vendor_id == "0BDA"


def test_anomaly_reports_crud(temp_db):
    report = AnomalyReport(
        is_anomaly=True,
        anomaly_score=0.75,
        health_score=35.0,
        contributing_factors={"rssi_dbm": -93.0},
        recommended_action="TRIGGER_PREEMPTIVE_HANDOVER",
    )
    temp_db.save_anomaly_report(report)

    anomalies = temp_db.get_recent_anomalies(limit=5)
    assert len(anomalies) == 1
    assert anomalies[0].is_anomaly is True
    assert anomalies[0].health_score == 35.0
    assert anomalies[0].contributing_factors["rssi_dbm"] == -93.0


def test_handover_decisions_crud(temp_db):
    decision = HandoverDecision(
        should_handover=True,
        current_bssid="c0:25:2f:5e:7e:42",
        target_bssid="c0:25:2f:72:9e:4c",
        target_ssid="Telyexpress_Pablo",
        current_score=45.0,
        target_score=82.0,
        score_margin_pct=82.2,
        consecutive_cycles=3,
        in_deadband=False,
        in_warmup=False,
        reason="Hysteresis criteria fulfilled",
    )
    temp_db.save_handover_decision(decision)

    history = temp_db.get_handover_history(limit=5)
    assert len(history) == 1
    assert history[0].should_handover is True
    assert history[0].target_ssid == "Telyexpress_Pablo"


def test_concurrent_wal_access(temp_db, sample_rf_metrics):
    """Simulates simultaneous concurrent writes and reads from multiple threads."""
    errors = []

    def writer():
        try:
            for i in range(25):
                sample_rf_metrics.signal_pct = 80 + (i % 20)
                temp_db.save_rf_metrics(sample_rf_metrics)
        except Exception as e:
            errors.append(e)

    def reader():
        try:
            for _ in range(25):
                temp_db.get_recent_rf_metrics(limit=10)
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=writer),
        threading.Thread(target=writer),
        threading.Thread(target=reader),
        threading.Thread(target=reader),
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Encountered concurrency errors: {errors}"
