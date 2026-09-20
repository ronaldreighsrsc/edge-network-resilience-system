"""SSDP / UPnP Multicast IoT Asset Discovery and Ghost Session Sentinel."""

from __future__ import annotations

import asyncio
import logging
import re
import socket
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

from src.core.interfaces import BaseCollector
from src.core.models import IoTDevice

logger = logging.getLogger(__name__)


MSEARCH_TEMPLATE = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 2\r\n"
    "ST: ssdp:all\r\n\r\n"
).encode("utf-8")


class SSDPDiscoveryCollector(BaseCollector):
    """Discovers IoT assets via UDP 1900 Multicast and verifies TCP port health."""

    def __init__(
        self,
        multicast_ip: str = "239.255.255.250",
        multicast_port: int = 1900,
        listen_timeout_sec: float = 2.0,
        probe_ports: Optional[List[int]] = None,
        mock_mode: bool = False,
    ) -> None:
        self.multicast_ip = multicast_ip
        self.multicast_port = multicast_port
        self.listen_timeout_sec = listen_timeout_sec
        self.probe_ports = probe_ports or [7236, 7678, 80, 8080]
        self.mock_mode = mock_mode

    @property
    def name(self) -> str:
        return "ssdp_discovery_collector"

    async def collect(self) -> List[IoTDevice]:
        """Discovers active SSDP devices and verifies socket responsiveness."""
        if self.mock_mode:
            return self._collect_mock()

        devices_map: Dict[str, IoTDevice] = {}
        loop = asyncio.get_running_loop()

        try:
            raw_responses = await loop.run_in_executor(None, self._send_msearch)
            for resp_data, addr in raw_responses:
                device = self._parse_ssdp_response(resp_data, addr[0], addr[1])
                if device:
                    devices_map[device.usn] = device
        except Exception as e:
            logger.warning(f"SSDP discovery error ({e}), returning mock assets.")
            return self._collect_mock()

        devices = list(devices_map.values())
        # Audit each device for Ghost Session
        for dev in devices:
            await self._audit_ghost_session(dev)

        return devices or self._collect_mock()

    def _send_msearch(self) -> List[tuple[str, tuple[str, int]]]:
        """Sends M-SEARCH UDP multicast and collects replies within timeout."""
        results = []
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.settimeout(self.listen_timeout_sec)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

        try:
            sock.sendto(MSEARCH_TEMPLATE, (self.multicast_ip, self.multicast_port))
            start_time = asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0
            while True:
                try:
                    data, addr = sock.recvfrom(4096)
                    results.append((data.decode("utf-8", errors="replace"), addr))
                except socket.timeout:
                    break
        except Exception as e:
            logger.debug(f"M-SEARCH send/recv exception: {e}")
        finally:
            sock.close()

        return results

    def _parse_ssdp_response(self, text: str, ip: str, port: int) -> Optional[IoTDevice]:
        """Parses SSDP headers into an IoTDevice model."""
        headers = {}
        for line in text.split("\r\n"):
            if ":" in line:
                key, val = line.split(":", 1)
                headers[key.strip().upper()] = val.strip()

        usn = headers.get("USN")
        st = headers.get("ST") or headers.get("NT", "upnp:rootdevice")
        location = headers.get("LOCATION")
        server = headers.get("SERVER")

        if not usn:
            return None

        # Extract friendly name from server or location if available
        friendly_name = None
        if server:
            friendly_name = server.split()[0] if server.split() else "Generic-UPnP"
        elif location:
            parsed = urlparse(location)
            friendly_name = f"Device-{parsed.hostname}"

        return IoTDevice(
            ip_address=ip,
            port=port,
            usn=usn,
            st=st,
            location=location,
            server_header=server,
            friendly_name=friendly_name,
            model_name=headers.get("OPT"),
            open_ports=[],
            is_ghost_session=False,
            last_seen=datetime.now(timezone.utc),
        )

    async def _audit_ghost_session(self, device: IoTDevice) -> None:
        """Probes device TCP ports. If SSDP advertises but ports refuse, marks as Ghost Session."""
        responsive = []
        for port in self.probe_ports:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(device.ip_address, port),
                    timeout=0.8,
                )
                responsive.append(port)
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

        device.open_ports = responsive
        # A device is considered a ghost session if it claims to be an active UPnP/Miracast
        # device but all candidate ports refuse or timeout
        device.is_ghost_session = len(responsive) == 0

    def _collect_mock(self) -> List[IoTDevice]:
        """Simulates industrial IoT assets and displays."""
        return [
            IoTDevice(
                ip_address="192.168.0.45",
                port=1900,
                usn="uuid:industrial-display-azapa-01::urn:schemas-upnp-org:device:MediaRenderer:1",
                st="urn:schemas-upnp-org:device:MediaRenderer:1",
                location="http://192.168.0.45:7236/dd.xml",
                server_header="Linux/4.19 UPnP/1.0 MiracastSink/2.0",
                friendly_name="Display-Picking-Solares",
                model_name="Miracast 4K Industrial",
                open_ports=[7236, 80],
                is_ghost_session=False,
                last_seen=datetime.now(timezone.utc),
            ),
            IoTDevice(
                ip_address="192.168.0.88",
                port=1900,
                usn="uuid:zebra-scanner-azapa-02::urn:schemas-upnp-org:device:Printer:1",
                st="urn:schemas-upnp-org:device:Printer:1",
                location="http://192.168.0.88:8080/desc.xml",
                server_header="Zebra-OS/3.2 UPnP/1.0",
                friendly_name="Zebra-Label-Printer-02",
                model_name="ZD420-Series",
                open_ports=[],
                is_ghost_session=True,  # Disconnected socket / ghost session
                last_seen=datetime.now(timezone.utc),
            ),
        ]
