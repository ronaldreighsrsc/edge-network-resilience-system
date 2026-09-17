"""Unit and integration tests for Edge Telemetry Collectors."""

import pytest
from unittest.mock import AsyncMock, patch

from src.collectors.dns_watchdog import DNSWatchdogCollector
from src.collectors.rf_collector import RFTelemetryCollector, signal_pct_to_dbm
from src.collectors.socket_probe import SocketProbeCollector
from src.collectors.ssdp_discovery import SSDPDiscoveryCollector
from src.collectors.usb_sentinel import USBSentinelCollector
from src.core.models import HardwareEventType, IoTDevice


# --- RF Collector Tests ---

def test_signal_pct_to_dbm_mapping():
    assert signal_pct_to_dbm(100) == -50.0
    assert signal_pct_to_dbm(0) == -100.0
    assert signal_pct_to_dbm(-10) == -100.0
    assert signal_pct_to_dbm(110) == -50.0
    assert signal_pct_to_dbm(87) == -56.5


def test_rf_collector_parse_interfaces():
    collector = RFTelemetryCollector()
    sample_interfaces = """
There is 1 interface on the system: 

    Name                   : Wi-Fi
    Description            : Realtek RTL8852BE-VS WiFi 6 802.11ax PCIe Adapter
    GUID                   : 8e5d0a68-dfc9-4b6e-8219-482a5c53b211
    State                  : connected
    SSID                   : Telyexpress_Solares
    BSSID                  : c0:25:2f:5e:7e:42
    Network type           : Infrastructure
    Radio type             : 802.11n
    Authentication         : WPA2-Personal
    Cipher                 : CCMP
    Connection mode        : Profile
    Band                   : 2.4 GHz
    Channel                : 1
    Receive rate (Mbps)    : 144.4
    Transmit rate (Mbps)   : 144.4
    Signal                 : 87% 
    Profile                : Telyexpress_Solares 
"""
    res = collector._parse_interfaces(sample_interfaces)
    assert res["ssid"] == "Telyexpress_Solares"
    assert res["bssid"] == "c0:25:2f:5e:7e:42"
    assert res["signal"] == 87
    assert res["channel"] == 1
    assert res["rx_rate"] == 144.4


def test_rf_collector_parse_networks():
    collector = RFTelemetryCollector()
    sample_networks = """
SSID 1 : Telyexpress_Solares
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP 
    BSSID 1                 : c0:25:2f:5e:7e:42
         Signal             : 87%  
         Radio type         : 802.11n
         Channel            : 1 
         Band               : 2.4 GHz
         Channel Utilization: 87 (34 %)
SSID 2 : Telyexpress_Pablo
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP 
    BSSID 1                 : c0:25:2f:72:9e:4c
         Signal             : 72%  
         Radio type         : 802.11n
         Channel            : 10 
         Band               : 2.4 GHz
         Channel Utilization: 56 (22 %)
"""
    candidates = collector._parse_networks(sample_networks, current_bssid="c0:25:2f:5e:7e:42")
    assert len(candidates) == 2
    assert candidates[0].ssid == "Telyexpress_Solares"
    assert candidates[0].is_current is True
    assert candidates[0].channel == 1
    assert candidates[0].airtime_utilization_pct == 34.0

    assert candidates[1].ssid == "Telyexpress_Pablo"
    assert candidates[1].is_current is False
    assert candidates[1].channel == 10
    assert candidates[1].airtime_utilization_pct == 22.0


def test_rf_collector_mock():
    collector = RFTelemetryCollector()
    rf, candidates = collector._collect_mock()
    assert "Solares" in rf.ssid
    assert len(candidates) == 2


# --- Socket Probe Tests ---

@pytest.mark.asyncio
async def test_socket_probe_mock():
    collector = SocketProbeCollector(mock_mode=True)
    probes = await collector.collect()
    assert len(probes) == 3
    names = [p.target_name for p in probes]
    assert "gateway" in names
    assert "cpe_outdoor" in names
    assert "public_dns" in names


# --- SSDP Discovery Tests ---

def test_ssdp_parse_response():
    collector = SSDPDiscoveryCollector()
    sample_response = (
        "HTTP/1.1 200 OK\r\n"
        "LOCATION: http://192.168.0.45:7236/desc.xml\r\n"
        "SERVER: Linux/4.19 UPnP/1.0 MiracastSink/2.0\r\n"
        "ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n"
        "USN: uuid:test-device-01::urn:schemas-upnp-org:device:MediaRenderer:1\r\n\r\n"
    )
    device = collector._parse_ssdp_response(sample_response, "192.168.0.45", 1900)
    assert device is not None
    assert device.ip_address == "192.168.0.45"
    assert device.usn == "uuid:test-device-01::urn:schemas-upnp-org:device:MediaRenderer:1"
    assert "MiracastSink" in (device.server_header or "")


@pytest.mark.asyncio
async def test_ssdp_ghost_session_detection():
    collector = SSDPDiscoveryCollector(probe_ports=[7236])
    device = IoTDevice(
        ip_address="127.0.0.1",
        port=1900,
        usn="uuid:ghost-01",
        st="urn:schemas-upnp-org:device:Printer:1",
    )
    # Port 7236 is not open on localhost, so it must be identified as ghost session
    await collector._audit_ghost_session(device)
    assert device.is_ghost_session is True
    assert len(device.open_ports) == 0


# --- DNS Watchdog Tests ---

@pytest.mark.asyncio
async def test_dns_watchdog_nominal_standard():
    watchdog = DNSWatchdogCollector(consecutive_failure_threshold=2)
    with patch.object(watchdog, "_resolve_standard", AsyncMock(return_value=(12.0, True, "142.250.190.46"))):
        res = await watchdog.collect()
        assert res["dns_healthy"] is True
        assert res["doh_active"] is False
        assert res["provider"] == "System-ISP"


@pytest.mark.asyncio
async def test_dns_watchdog_failover_to_doh():
    watchdog = DNSWatchdogCollector(consecutive_failure_threshold=2)
    # Simulate standard DNS failing twice
    with patch.object(watchdog, "_resolve_standard", AsyncMock(return_value=(2000.0, False, None))):
        with patch.object(watchdog, "_resolve_doh", AsyncMock(return_value=(25.0, True, "1.1.1.1"))):
            # Failure 1
            res1 = await watchdog.collect()
            assert not watchdog.is_doh_active

            # Failure 2: threshold exceeded -> failover to DoH!
            res2 = await watchdog.collect()
            assert watchdog.is_doh_active
            assert res2["doh_active"] is True
            assert res2["provider"] == "DoH-Cloudflare"


# --- USB Sentinel Tests ---

def test_usb_sentinel_parse_event():
    collector = USBSentinelCollector()
    item = {
        "Id": 2004,
        "Message": "Device USB\\VID_0BDA&PID_B852\\12345 was removed from the system.",
        "TimeCreated": "2026-09-16T12:00:00Z",
    }
    event = collector._parse_event_item(item)
    assert event is not None
    assert event.event_type == HardwareEventType.DISCONNECTED
    assert event.vendor_id == "0BDA"
    assert event.product_id == "B852"
    assert event.serial_number == "12345"


def test_usb_sentinel_simulate_brownout():
    collector = USBSentinelCollector()
    event = collector.simulate_brownout_disconnect()
    assert event.event_type == HardwareEventType.DISCONNECTED
    assert "Brownout" in (event.device_description or "")


@pytest.mark.asyncio
async def test_socket_probe_live_mocked():
    collector = SocketProbeCollector(mock_mode=False, targets={"gateway": "192.168.0.1"})
    with patch.object(collector, "_ping_sample", AsyncMock(return_value=2.5)):
        with patch("asyncio.open_connection", AsyncMock(return_value=(AsyncMock(), AsyncMock()))):
            probes = await collector.collect()
            assert len(probes) == 1
            assert probes[0].target_name == "gateway"
            assert probes[0].is_reachable is True
            assert probes[0].rtt_ms == 2.5


@pytest.mark.asyncio
async def test_socket_probe_ping_sample_parsing():
    collector = SocketProbeCollector()
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc_mock = AsyncMock()
        proc_mock.communicate.return_value = (b"Reply from 192.168.0.1: bytes=32 time=4.5ms TTL=64", b"")
        proc_mock.returncode = 0
        mock_exec.return_value = proc_mock
        rtt = await collector._ping_sample("192.168.0.1")
        assert rtt == 4.5


@pytest.mark.asyncio
async def test_dns_watchdog_standard_resolution():
    watchdog = DNSWatchdogCollector()
    with patch("socket.gethostbyname", return_value="142.250.190.46"):
        t, success, ip = await watchdog._resolve_standard("google.com")
        assert success is True
        assert ip == "142.250.190.46"


@pytest.mark.asyncio
async def test_dns_watchdog_doh_resolution():
    from unittest.mock import MagicMock
    watchdog = DNSWatchdogCollector()
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {"Answer": [{"data": "1.1.1.1"}]}

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=fake_response)):
        t, success, ip = await watchdog._resolve_doh("cloudflare.com")
        assert success is True
        assert ip == "1.1.1.1"


def test_ssdp_send_msearch_mocked():
    collector = SSDPDiscoveryCollector(listen_timeout_sec=0.1)
    with patch("socket.socket") as mock_sock_cls:
        mock_sock = mock_sock_cls.return_value
        import socket
        mock_sock.recvfrom.side_effect = socket.timeout
        results = collector._send_msearch()
        assert results == []


@pytest.mark.asyncio
async def test_usb_sentinel_windows_query_mocked():
    collector = USBSentinelCollector(mock_mode=False)
    collector._is_windows = True
    sample_json = '[{"Id": 2003, "Message": "Device USB\\\\VID_0BDA&PID_B852\\\\123 connected.", "TimeCreated": "2026-09-16T10:00:00Z"}]'
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = sample_json
        events = await collector._query_windows_events()
        assert len(events) == 1
        assert events[0].event_id == 2003
        assert events[0].vendor_id == "0BDA"


@pytest.mark.asyncio
async def test_handover_executor_live_and_warmup():
    from src.engine.handover import HandoverExecutor
    executor = HandoverExecutor(mock_mode=False, warmup_duration_sec=0.1)
    executor._is_windows = True
    executor._has_netsh = True

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Connection request was completed successfully."
        mock_run.return_value.stderr = ""
        success = await executor.switch_network("Telyexpress_Pablo")
        assert success is True

        warmup_success = await executor.warm_up_connection(gateway_ip="192.168.0.1", duration_sec=0.1)
        assert warmup_success is True
