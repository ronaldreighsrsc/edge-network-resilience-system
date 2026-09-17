"""RF Physical (L1) and Data Link (L2) Collector for Wi-Fi Telemetry."""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import shutil
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.core.interfaces import BaseCollector
from src.core.models import APCandidate, RFMetrics

logger = logging.getLogger(__name__)


def signal_pct_to_dbm(signal_pct: int) -> float:
    """Converts Windows signal percentage (0-100%) to dBm."""
    if signal_pct <= 0:
        return -100.0
    if signal_pct >= 100:
        return -50.0
    # Standard linear mapping: 0% -> -100 dBm, 100% -> -50 dBm
    return round((signal_pct / 2.0) - 100.0, 1)


class RFTelemetryCollector(BaseCollector):
    """Collects Wi-Fi RF telemetry using netsh on Windows or mock fallback for edge/testing."""

    def __init__(
        self,
        target_interface: Optional[str] = None,
        mock_candidates: Optional[List[APCandidate]] = None,
    ) -> None:
        self._target_interface = target_interface
        self._mock_candidates = mock_candidates
        self._is_windows = platform.system() == "Windows"
        self._has_netsh = bool(shutil.which("netsh"))

    @property
    def name(self) -> str:
        return "rf_telemetry_collector"

    async def collect(self) -> Tuple[RFMetrics, List[APCandidate]]:
        """Collects active RF metrics and visible candidate APs."""
        if self._mock_candidates:
            return self._collect_mock()

        if self._is_windows and self._has_netsh:
            try:
                return await self._collect_windows()
            except Exception as e:
                logger.warning(f"Windows netsh extraction failed ({e}), falling back to mock provider.")
                return self._collect_mock()
        else:
            return self._collect_mock()

    def _collect_mock(self) -> Tuple[RFMetrics, List[APCandidate]]:
        """Simulates Azapa live telemetry for tests and non-Windows deployments."""
        active_rf = RFMetrics(
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
            timestamp=datetime.utcnow(),
        )

        candidates = [
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
        return active_rf, candidates

    async def _collect_windows(self) -> Tuple[RFMetrics, List[APCandidate]]:
        """Executes netsh commands concurrently and parses BSSIDs and active interface."""
        loop = asyncio.get_running_loop()

        # Run commands in thread pool to avoid blocking async loop
        interfaces_out = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=5,
            ).stdout,
        )

        networks_out = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["netsh", "wlan", "show", "networks", "mode=bssid"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=5,
            ).stdout,
        )

        active_info = self._parse_interfaces(interfaces_out)
        candidates = self._parse_networks(networks_out, active_info.get("bssid", ""))

        # Build active RFMetrics
        active_signal = active_info.get("signal", 80)
        active_rf = RFMetrics(
            ssid=active_info.get("ssid", "Unknown_SSID"),
            bssid=active_info.get("bssid", "00:00:00:00:00:00"),
            rssi_dbm=signal_pct_to_dbm(active_signal),
            signal_pct=active_signal,
            channel=active_info.get("channel", 1),
            band=active_info.get("band", "2.4 GHz"),
            radio_type=active_info.get("radio_type", "802.11ax"),
            rx_rate_mbps=float(active_info.get("rx_rate", 144.0)),
            tx_rate_mbps=float(active_info.get("tx_rate", 144.0)),
            airtime_utilization_pct=float(active_info.get("airtime", 25.0)),
            connected_stations=active_info.get("stations", 5),
            timestamp=datetime.utcnow(),
        )

        return active_rf, candidates

    def _parse_interfaces(self, text: str) -> Dict[str, Any]:
        """Parses `netsh wlan show interfaces`."""
        res: Dict[str, Any] = {
            "ssid": "",
            "bssid": "",
            "signal": 0,
            "channel": 1,
            "rx_rate": 0.0,
            "tx_rate": 0.0,
            "radio_type": "802.11n",
            "band": "2.4 GHz",
        }
        for line in text.splitlines():
            line = line.strip()
            if m := re.match(r"^SSID\s*:\s*(.+)$", line):
                res["ssid"] = m.group(1).strip()
            elif m := re.match(r"^BSSID\s*:\s*([0-9a-fA-F:]{17})", line):
                res["bssid"] = m.group(1).strip().lower()
            elif m := re.match(r"^Signal\s*:\s*(\d+)%", line):
                res["signal"] = int(m.group(1))
            elif m := re.match(r"^Channel\s*:\s*(\d+)", line):
                res["channel"] = int(m.group(1))
            elif m := re.match(r"^Receive rate \(Mbps\)\s*:\s*([\d.]+)", line):
                res["rx_rate"] = float(m.group(1))
            elif m := re.match(r"^Transmit rate \(Mbps\)\s*:\s*([\d.]+)", line):
                res["tx_rate"] = float(m.group(1))
            elif m := re.match(r"^Radio type\s*:\s*(.+)$", line):
                res["radio_type"] = m.group(1).strip()
            elif m := re.match(r"^Band\s*:\s*(.+)$", line):
                res["band"] = m.group(1).strip()
        return res

    def _parse_networks(self, text: str, current_bssid: str) -> List[APCandidate]:
        """Parses `netsh wlan show networks mode=bssid`."""
        candidates: List[APCandidate] = []
        current_ssid = ""
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if m := re.match(r"^SSID\s+\d+\s*:\s*(.*)$", line):
                current_ssid = m.group(1).strip() or "Hidden_Network"
            elif m := re.match(r"^BSSID\s+\d+\s*:\s*([0-9a-fA-F:]{17})", line):
                bssid = m.group(1).strip().lower()
                signal = 50
                channel = 1
                band = "2.4 GHz"
                airtime = 25.0

                # Read subsequent BSSID attributes
                j = i + 1
                while j < len(lines) and not re.match(r"^(SSID|BSSID)\s+\d+\s*:", lines[j].strip()):
                    sub = lines[j].strip()
                    if sm := re.match(r"^Signal\s*:\s*(\d+)%", sub):
                        signal = int(sm.group(1))
                    elif cm := re.match(r"^Channel\s*:\s*(\d+)", sub):
                        channel = int(cm.group(1))
                        if channel > 14:
                            band = "5 GHz"
                    elif bm := re.match(r"^Band\s*:\s*(.+)$", sub):
                        band = bm.group(1).strip()
                    elif um := re.match(r"^Channel Utilization\s*:\s*\d+\s*\((\d+)\s*%\)", sub):
                        airtime = float(um.group(1))
                    j += 1

                candidates.append(
                    APCandidate(
                        ssid=current_ssid,
                        bssid=bssid,
                        rssi_dbm=signal_pct_to_dbm(signal),
                        signal_pct=signal,
                        channel=channel,
                        band=band,
                        airtime_utilization_pct=airtime,
                        is_current=(bssid == current_bssid.lower()),
                    )
                )
            i += 1

        return candidates
