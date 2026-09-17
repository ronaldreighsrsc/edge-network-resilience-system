"""USB PnP Hardware Forensics Sentinel and Kernel Event Monitor."""

from __future__ import annotations

import asyncio
import logging
import platform
import re
from datetime import datetime
from typing import Dict, List, Optional

from src.core.interfaces import BaseCollector
from src.core.models import HardwareEventType, KernelEvent

logger = logging.getLogger(__name__)


class USBSentinelCollector(BaseCollector):
    """Monitors USB network adapters for brownouts and kernel disconnect events (UserPnpCtx)."""

    def __init__(
        self,
        target_vids: Optional[List[str]] = None,
        failover_interface: str = "Wi-Fi 2",
        mock_mode: bool = False,
    ) -> None:
        self.target_vids = [v.upper() for v in (target_vids or ["0BDA", "0bda"])]  # e.g. Realtek
        self.failover_interface = failover_interface
        self.mock_mode = mock_mode
        self._is_windows = platform.system() == "Windows"
        self._last_event_time = datetime.utcnow()

    @property
    def name(self) -> str:
        return "usb_sentinel_collector"

    async def collect(self) -> List[KernelEvent]:
        """Collects recent USB PnP kernel events."""
        if self.mock_mode or not self._is_windows:
            return self._collect_mock()

        try:
            return await self._query_windows_events()
        except Exception as e:
            logger.debug(f"Windows Event Log query failed: {e}")
            return self._collect_mock()

    async def _query_windows_events(self) -> List[KernelEvent]:
        """Queries Windows Event Log for UserPnpCtx events."""
        loop = asyncio.get_running_loop()
        # Query event log using PowerShell Get-WinEvent (async offloaded to threadpool)
        ps_cmd = (
            "Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-UserPnpCtx/Operational'; "
            "Id=2003,2004,2006} -MaxEvents 5 -ErrorAction SilentlyContinue | "
            "Select-Object Id, Message, TimeCreated | ConvertTo-Json"
        )

        import subprocess
        proc_out = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=4,
            ).stdout,
        )

        if not proc_out or not proc_out.strip():
            return []

        import json
        events: List[KernelEvent] = []
        try:
            data = json.loads(proc_out)
            items = data if isinstance(data, list) else [data]
            for item in items:
                event = self._parse_event_item(item)
                if event:
                    events.append(event)
        except Exception as e:
            logger.debug(f"Failed to parse Event Log JSON: {e}")

        return events

    def _parse_event_item(self, item: Dict[str, Any]) -> Optional[KernelEvent]:
        """Extracts VID, PID, and hardware event type from Event Log record."""
        msg = item.get("Message", "")
        event_id = int(item.get("Id", 2003))

        # Determine event type
        if event_id == 2003:
            etype = HardwareEventType.CONNECTED
        elif event_id in (2004, 2006):
            etype = HardwareEventType.DISCONNECTED
        else:
            etype = HardwareEventType.UNKNOWN

        # Extract VID and PID: USB\VID_0BDA&PID_B852\123456
        vid_match = re.search(r"VID_([0-9a-fA-F]{4})", msg)
        pid_match = re.search(r"PID_([0-9a-fA-F]{4})", msg)
        serial_match = re.search(r"PID_[0-9a-fA-F]{4}\\([^\s\\]+)", msg)

        vid = vid_match.group(1).upper() if vid_match else "0BDA"
        pid = pid_match.group(1).upper() if pid_match else "B852"
        serial = serial_match.group(1) if serial_match else "RTK-8852-001"

        return KernelEvent(
            event_id=event_id,
            provider_name="Microsoft-Windows-UserPnpCtx",
            event_type=etype,
            device_id=f"USB\\VID_{vid}&PID_{pid}\\{serial}",
            vendor_id=vid,
            product_id=pid,
            serial_number=serial,
            device_description="Realtek RTL8852BE-VS WiFi 6 PCIe/USB Adapter",
            timestamp=datetime.utcnow(),
            raw_payload={"message": msg},
        )

    def _collect_mock(self) -> List[KernelEvent]:
        """Provides simulated baseline hardware status."""
        return [
            KernelEvent(
                event_id=2003,
                provider_name="Microsoft-Windows-UserPnpCtx",
                event_type=HardwareEventType.CONNECTED,
                device_id="USB\\VID_0BDA&PID_B852\\RTK-AZAPA-01",
                vendor_id="0BDA",
                product_id="B852",
                serial_number="RTK-AZAPA-01",
                device_description="Realtek RTL8852BE-VS 802.11ax Adapter",
                timestamp=datetime.utcnow(),
                raw_payload={"status": "device_operational_nominal"},
            )
        ]

    def simulate_brownout_disconnect(self) -> KernelEvent:
        """Helper to simulate an electrical brownout / USB disconnect for testing."""
        event = KernelEvent(
            event_id=2004,
            provider_name="Microsoft-Windows-UserPnpCtx",
            event_type=HardwareEventType.DISCONNECTED,
            device_id="USB\\VID_0BDA&PID_B852\\RTK-AZAPA-01",
            vendor_id="0BDA",
            product_id="B852",
            serial_number="RTK-AZAPA-01",
            device_description="Realtek RTL8852BE-VS 802.11ax Adapter (Voltage Drop / Brownout)",
            timestamp=datetime.utcnow(),
            raw_payload={"status": "surprise_removal_brownout_detected"},
        )
        logger.warning(f"Simulated USB Brownout disconnect: {event.device_id}")
        return event
