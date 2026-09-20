"""DNS Watchdog and Hot Failover to DNS-over-HTTPS (DoH)."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import httpx

from src.core.interfaces import BaseCollector

logger = logging.getLogger(__name__)


class DNSWatchdogCollector(BaseCollector):
    """Monitors standard DNS resolution and fails over to DoH (Cloudflare/Google) upon failure."""

    def __init__(
        self,
        test_domains: Optional[List[str]] = None,
        timeout_sec: float = 2.0,
        consecutive_failure_threshold: int = 2,
        primary_doh_url: str = "https://1.1.1.1/dns-query",
        secondary_doh_url: str = "https://8.8.8.8/resolve",
        mock_mode: bool = False,
    ) -> None:
        self.test_domains = test_domains or ["google.com", "cloudflare.com", "github.com"]
        self.timeout_sec = timeout_sec
        self.consecutive_failure_threshold = consecutive_failure_threshold
        self.primary_doh_url = primary_doh_url
        self.secondary_doh_url = secondary_doh_url
        self.mock_mode = mock_mode

        self._failure_count = 0
        self._doh_active = False

    @property
    def name(self) -> str:
        return "dns_watchdog_collector"

    @property
    def is_doh_active(self) -> bool:
        return self._doh_active

    async def collect(self) -> Dict[str, Any]:
        """Resolves canary domains, tracks failure count, and activates DoH if required."""
        if self.mock_mode:
            return {
                "dns_healthy": True,
                "doh_active": self._doh_active,
                "avg_resolution_ms": 14.2,
                "failure_count": 0,
                "provider": "DoH-Cloudflare" if self._doh_active else "System-ISP",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        domain = self.test_domains[0]
        resolution_time, success, resolved_ip = await self._resolve_standard(domain)

        if not success:
            self._failure_count += 1
            logger.warning(
                f"Standard DNS lookup failed for {domain} (consecutive failures: {self._failure_count})"
            )
            if self._failure_count >= self.consecutive_failure_threshold:
                if not self._doh_active:
                    logger.error(
                        "DNS failure threshold exceeded! Activating zero-downtime DNS-over-HTTPS (DoH) failover."
                    )
                    self._doh_active = True

                # Test resolution via DoH
                doh_time, doh_success, doh_ip = await self._resolve_doh(domain)
                return {
                    "dns_healthy": doh_success,
                    "doh_active": True,
                    "avg_resolution_ms": doh_time,
                    "resolved_ip": doh_ip,
                    "failure_count": self._failure_count,
                    "provider": "DoH-Cloudflare",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
        else:
            if self._failure_count > 0:
                logger.info(f"Standard DNS recovered. Resetting failure counter from {self._failure_count} to 0.")
                self._failure_count = 0
                self._doh_active = False

            return {
                "dns_healthy": True,
                "doh_active": False,
                "avg_resolution_ms": resolution_time,
                "resolved_ip": resolved_ip,
                "failure_count": 0,
                "provider": "System-ISP",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def _resolve_standard(self, hostname: str) -> Tuple[float, bool, Optional[str]]:
        """Performs standard OS DNS resolution via gethostbyname."""
        loop = asyncio.get_running_loop()
        start = time.perf_counter()
        try:
            ip = await asyncio.wait_for(
                loop.run_in_executor(None, socket.gethostbyname, hostname),
                timeout=self.timeout_sec,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return round(elapsed_ms, 2), True, ip
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return round(elapsed_ms, 2), False, None

    async def _resolve_doh(self, hostname: str) -> Tuple[float, bool, Optional[str]]:
        """Performs DNS-over-HTTPS resolution against Cloudflare or Google DoH endpoints."""
        start = time.perf_counter()
        headers = {"Accept": "application/dns-json"}
        params = {"name": hostname, "type": "A"}

        # Try Cloudflare first, then fallback to Google
        endpoints = [self.primary_doh_url, self.secondary_doh_url]
        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            for url in endpoints:
                try:
                    resp = await client.get(url, params=params, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        answers = data.get("Answer", [])
                        if answers:
                            ip = answers[0].get("data")
                            elapsed_ms = (time.perf_counter() - start) * 1000.0
                            return round(elapsed_ms, 2), True, ip
                except Exception as e:
                    logger.debug(f"DoH query to {url} failed: {e}")

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return round(elapsed_ms, 2), False, None
