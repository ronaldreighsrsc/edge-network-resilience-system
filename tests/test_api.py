"""API endpoint tests using FastAPI TestClient."""

import pytest
from starlette.testclient import TestClient

from src.api.app import create_app
from src.core.models import RFMetrics, SocketProbeMetrics


@pytest.fixture
def client(temp_db, mcda_engine, mock_handover, anomaly_detector, mlops_tracker):
    # Pre-populate sample telemetry in temp_db
    rf = RFMetrics(
        ssid="Telyexpress_Solares",
        bssid="c0:25:2f:5e:7e:42",
        rssi_dbm=-52.0,
        signal_pct=87,
        channel=1,
        band="2.4 GHz",
        radio_type="802.11n",
        rx_rate_mbps=144.4,
        tx_rate_mbps=144.4,
        airtime_utilization_pct=34.0,
        connected_stations=11,
    )
    temp_db.save_rf_metrics(rf)
    probes = [
        SocketProbeMetrics(target_name="gateway", target_ip="192.168.0.1", rtt_ms=2.4, jitter_ms=0.8, packet_loss_pct=0.0),
        SocketProbeMetrics(target_name="public_dns", target_ip="8.8.8.8", rtt_ms=28.5, jitter_ms=4.1, packet_loss_pct=0.0),
    ]
    temp_db.save_socket_probes(probes)

    app = create_app(
        repo=temp_db,
        mcda=mcda_engine,
        handover_exec=mock_handover,
        detector=anomaly_detector,
        tracker=mlops_tracker,
    )
    return TestClient(app)


def test_root_endpoint(client):
    res = client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ONLINE"


def test_health_endpoint(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert "health_score" in data
    assert data["current_ssid"] == "Telyexpress_Solares"


def test_current_metrics_endpoint(client):
    res = client.get("/api/metrics/current")
    assert res.status_code == 200
    data = res.json()
    assert data["rf"]["ssid"] == "Telyexpress_Solares"
    assert len(data["probes"]) == 2


def test_rf_history_endpoint(client):
    res = client.get("/api/metrics/history/rf?limit=10")
    assert res.status_code == 200
    assert len(res.json()) >= 1


def test_candidates_endpoint(client):
    res = client.get("/api/candidates")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    ssids = {c["ssid"] for c in data}
    assert "Telyexpress_Solares" in ssids
    assert "Telyexpress_Pablo" in ssids


def test_handover_trigger_endpoint(client):
    payload = {
        "target_ssid": "Telyexpress_Pablo",
        "target_bssid": "c0:25:2f:72:9e:4c",
        "force": True,
    }
    res = client.post("/api/handover/trigger", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["target_ssid"] == "Telyexpress_Pablo"


def test_iot_devices_endpoint(client):
    res = client.get("/api/iot/devices")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_usb_events_endpoint(client):
    res = client.get("/api/forensics/usb")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_mlops_runs_endpoint(client):
    res = client.get("/api/mlops/runs")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
