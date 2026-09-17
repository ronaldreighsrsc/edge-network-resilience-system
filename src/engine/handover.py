"""Physical Wi-Fi Handover and Network Reassociation Executor."""

from __future__ import annotations

import asyncio
import logging
import platform
import shutil
import subprocess
import time
from typing import Optional

from src.core.interfaces import HandoverExecutorInterface

logger = logging.getLogger(__name__)


class HandoverExecutor(HandoverExecutorInterface):
    """Executes network roaming transitions via Windows netsh or mock simulation."""

    def __init__(
        self,
        interface_name: Optional[str] = None,
        warmup_duration_sec: float = 4.0,
        mock_mode: bool = False,
    ) -> None:
        self.interface_name = interface_name
        self.warmup_duration_sec = warmup_duration_sec
        self.mock_mode = mock_mode
        self._is_windows = platform.system() == "Windows"
        self._has_netsh = bool(shutil.which("netsh"))

    async def switch_network(self, target_ssid: str, target_bssid: Optional[str] = None) -> bool:
        """Initiates network switch to target SSID/BSSID."""
        logger.info(f"Initiating network handover towards SSID: {target_ssid} (BSSID: {target_bssid or 'Any'})")

        if self.mock_mode or not (self._is_windows and self._has_netsh):
            await asyncio.sleep(0.3)
            logger.info(f"[Mock] Handover to {target_ssid} succeeded.")
            return True

        loop = asyncio.get_running_loop()
        cmd = ["netsh", "wlan", "connect", f"name={target_ssid}"]
        if self.interface_name:
            cmd.append(f"interface={self.interface_name}")

        try:
            res = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=8,
                ),
            )
            if res.returncode == 0 and "successfully" in res.stdout.lower():
                logger.info(f"netsh connection order to {target_ssid} completed successfully.")
                return True
            else:
                logger.warning(f"netsh connect output: {res.stdout.strip()} {res.stderr.strip()}")
                return "completed successfully" in res.stdout.lower() or res.returncode == 0
        except Exception as e:
            logger.error(f"Failed to execute netsh connection command: {e}")
            return False

    async def warm_up_connection(self, gateway_ip: str = "192.168.0.1", duration_sec: Optional[float] = None) -> bool:
        """Post-handover stabilization: populates ARP table and stabilizes physical link."""
        duration = duration_sec if duration_sec is not None else self.warmup_duration_sec
        logger.info(f"Entering warm-up buffer for {duration} seconds (probing gateway {gateway_ip})...")

        start_time = time.time()
        # Send non-blocking discard pings to prime ARP and TCP stacks
        while (time.time() - start_time) < duration:
            try:
                # Discard ping
                if self._is_windows and shutil.which("ping"):
                    subprocess.run(
                        ["ping", "-n", "1", "-w", "500", gateway_ip],
                        capture_output=True,
                        timeout=1,
                    )
            except Exception:
                pass
            await asyncio.sleep(1.0)

        logger.info("Warm-up phase completed. Network link primed and stabilized.")
        return True
