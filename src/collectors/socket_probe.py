"""Socket and Transport Layer (L3/L4) Probe Collector."""

from __future__ import annotations

import asyncio
import logging
import platform
import socket
import time
from datetime import datetime
from typing import Dict, List, Optional

from src.core.interfaces import BaseCollector
from src.core.models import SocketProbeMetrics

logger = logging.getLogger(__name__)


class SocketProbeCollector(BaseCollector):
    """Probes transport and routing paths concurrently to Gateway, CPE, and Public DNS."""

    def __init__(
        self,
        targets: Optional[Dict[str, str]] = None,
        probe_timeout_sec: float = 1.5,
        mock_mode: bool = False,
    ) -> None:
        self.targets = targets or {
            "gateway": "192.168.0.1",
            "cpe_outdoor": "192.168.150.1",
            "public_dns": "8.8.8.8",
        }
        self.probe_timeout_sec = probe_timeout_sec
        self.mock_mode = mock_mode
        self._previous_rtt: Dict[str, float] = {}

    @property
    def name(self) -> str:
        return "socket_probe_collector"

    async def collect(self) -> List[SocketProbeMetrics]:
        """Probes all configured endpoints concurrently."""
        if self.mock_mode:
            return self._collect_mock()

        tasks = [
            self._probe_target(name, ip)
            for name, ip in self.targets.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        probes: List[SocketProbeMetrics] = []
        for r in results:
            if isinstance(r, SocketProbeMetrics):
                probes.append(r)
            elif isinstance(r, Exception):
                logger.error(f"Error during socket probe: {r}")

        return probes

    async def _probe_target(self, name: str, ip: str) -> SocketProbeMetrics:
        """Measures RTT, jitter, packet loss and TCP handshake latency."""
        port = 53 if name == "public_dns" else 80
        sample_count = 3
        rtts: List[float] = []
        tcp_handshake_ms: Optional[float] = None

        # 1. Measure TCP handshake latency
        start_tcp = time.perf_counter()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=self.probe_timeout_sec,
            )
            tcp_handshake_ms = (time.perf_counter() - start_tcp) * 1000.0
            writer.close()
            await writer.wait_closed()
        except Exception:
            tcp_handshake_ms = None

        # 2. Measure ICMP / Ping samples for RTT & Jitter
        for _ in range(sample_count):
            sample_rtt = await self._ping_sample(ip)
            if sample_rtt is not None:
                rtts.append(sample_rtt)
            await asyncio.sleep(0.05)

        loss_pct = ((sample_count - len(rtts)) / sample_count) * 100.0
        avg_rtt = sum(rtts) / len(rtts) if rtts else 999.0

        # Calculate RFC 3550 style jitter
        last_rtt = self._previous_rtt.get(name, avg_rtt)
        jitter_ms = abs(avg_rtt - last_rtt)
        self._previous_rtt[name] = avg_rtt

        is_reachable = len(rtts) > 0 or (tcp_handshake_ms is not None)

        return SocketProbeMetrics(
            target_name=name,
            target_ip=ip,
            rtt_ms=round(avg_rtt, 2),
            jitter_ms=round(jitter_ms, 2),
            packet_loss_pct=round(loss_pct, 1),
            tcp_handshake_ms=round(tcp_handshake_ms, 2) if tcp_handshake_ms else None,
            is_reachable=is_reachable,
            timestamp=datetime.utcnow(),
        )

    async def _ping_sample(self, ip: str) -> Optional[float]:
        """Executes a single ping measurement asynchronously."""
        loop = asyncio.get_running_loop()
        is_win = platform.system() == "Windows"
        cmd = ["ping", "-n" if is_win else "-c", "1", "-w" if is_win else "-W", "1000", ip]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self.probe_timeout_sec)
            out_str = stdout.decode("latin-1", errors="replace")

            # Parse ping time
            import re
            match = re.search(r"(?:time|tiempo)[=<]([\d.]+)\s*ms", out_str, re.IGNORECASE)
            if match:
                return float(match.group(1))
            elif proc.returncode == 0:
                return 5.0
            return None
        except Exception:
            return None

    def _collect_mock(self) -> List[SocketProbeMetrics]:
        """Generates realistic Azapa probe metrics for tests."""
        return [
            SocketProbeMetrics(
                target_name="gateway",
                target_ip="192.168.0.1",
                rtt_ms=2.4,
                jitter_ms=0.8,
                packet_loss_pct=0.0,
                tcp_handshake_ms=3.1,
                is_reachable=True,
                timestamp=datetime.utcnow(),
            ),
            SocketProbeMetrics(
                target_name="cpe_outdoor",
                target_ip="192.168.150.1",
                rtt_ms=4.8,
                jitter_ms=1.2,
                packet_loss_pct=0.0,
                tcp_handshake_ms=6.2,
                is_reachable=True,
                timestamp=datetime.utcnow(),
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
                timestamp=datetime.utcnow(),
            ),
        ]
