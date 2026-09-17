"""Simulated Live CLI Demonstration of OmniEdge Sentinel Resilience Cycles."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.collectors.dns_watchdog import DNSWatchdogCollector
from src.collectors.rf_collector import RFTelemetryCollector
from src.collectors.socket_probe import SocketProbeCollector
from src.collectors.ssdp_discovery import SSDPDiscoveryCollector
from src.collectors.usb_sentinel import USBSentinelCollector
from src.core.models import APCandidate, RFMetrics
from src.engine.handover import HandoverExecutor
from src.engine.mcda_engine import MCDARoamingEngine
from src.engine.orchestrator import ResilienceOrchestrator
from src.ml.anomaly_detector import LinkAnomalyDetector
from src.storage.sqlite_repository import SQLiteTelemetryRepository

console = Console()


async def run_live_simulation():
    console.print(
        Panel.fit(
            "[bold cyan]🛡️ OMNIEDGE SENTINEL: LIVE EDGE RESILIENCE SIMULATION[/bold cyan]\n"
            "[dim]Azapa Valley Real Field Scenario: Sticky Client Mitigation & MCDA Hysteresis[/dim]",
            border_style="cyan",
        )
    )

    repo = SQLiteTelemetryRepository(db_path="data/telemetry_demo.db")
    mcda = MCDARoamingEngine(deadband_pct=0.15, hysteresis_cycles=3, warmup_duration_sec=2.0)
    executor = HandoverExecutor(mock_mode=True, warmup_duration_sec=2.0)
    detector = LinkAnomalyDetector()

    orchestrator = ResilienceOrchestrator(
        repository=repo,
        rf_collector=RFTelemetryCollector(mock_candidates=[]),
        probe_collector=SocketProbeCollector(mock_mode=True),
        ssdp_collector=SSDPDiscoveryCollector(mock_mode=True),
        dns_collector=DNSWatchdogCollector(mock_mode=True),
        usb_collector=USBSentinelCollector(mock_mode=True),
        mcda_engine=mcda,
        handover_executor=executor,
        anomaly_detector=detector,
    )

    scenarios = [
        {
            "name": "Ciclo 1: Estado Nominal en Telyexpress_Solares",
            "active_bssid": "c0:25:2f:5e:7e:42",
            "candidates": [
                APCandidate(ssid="Telyexpress_Solares", bssid="c0:25:2f:5e:7e:42", rssi_dbm=-52.0, signal_pct=87, channel=1, band="2.4 GHz", airtime_utilization_pct=34.0, is_current=True),
                APCandidate(ssid="Telyexpress_Pablo", bssid="c0:25:2f:72:9e:4c", rssi_dbm=-71.0, signal_pct=72, channel=10, band="2.4 GHz", airtime_utilization_pct=22.0, is_current=False),
            ],
        },
        {
            "name": "Ciclo 2: Atenuación Física Forzada (-93 dBm en Solares)",
            "active_bssid": "c0:25:2f:5e:7e:42",
            "candidates": [
                APCandidate(ssid="Telyexpress_Solares", bssid="c0:25:2f:5e:7e:42", rssi_dbm=-93.0, signal_pct=14, channel=1, band="2.4 GHz", airtime_utilization_pct=80.0, is_current=True),
                APCandidate(ssid="Telyexpress_Pablo", bssid="c0:25:2f:72:9e:4c", rssi_dbm=-68.0, signal_pct=75, channel=10, band="2.4 GHz", airtime_utilization_pct=20.0, is_current=False),
            ],
        },
        {
            "name": "Ciclo 3: Degradación Sostenida (Ciclo 2 de Histéresis)",
            "active_bssid": "c0:25:2f:5e:7e:42",
            "candidates": [
                APCandidate(ssid="Telyexpress_Solares", bssid="c0:25:2f:5e:7e:42", rssi_dbm=-92.0, signal_pct=16, channel=1, band="2.4 GHz", airtime_utilization_pct=78.0, is_current=True),
                APCandidate(ssid="Telyexpress_Pablo", bssid="c0:25:2f:72:9e:4c", rssi_dbm=-67.0, signal_pct=76, channel=10, band="2.4 GHz", airtime_utilization_pct=19.0, is_current=False),
            ],
        },
        {
            "name": "Ciclo 4: Umbral Alcanzado (3/3 Ciclos) -> HANDOVER EJECUTADO",
            "active_bssid": "c0:25:2f:5e:7e:42",
            "candidates": [
                APCandidate(ssid="Telyexpress_Solares", bssid="c0:25:2f:5e:7e:42", rssi_dbm=-94.0, signal_pct=12, channel=1, band="2.4 GHz", airtime_utilization_pct=82.0, is_current=True),
                APCandidate(ssid="Telyexpress_Pablo", bssid="c0:25:2f:72:9e:4c", rssi_dbm=-66.0, signal_pct=78, channel=10, band="2.4 GHz", airtime_utilization_pct=18.0, is_current=False),
            ],
        },
    ]

    for step, sc in enumerate(scenarios, start=1):
        console.print(f"\n[bold yellow]▶ {sc['name']}[/bold yellow]")
        probes = await orchestrator.probe_collector.collect()
        decision = mcda.evaluate(
            candidates=sc["candidates"],
            current_bssid=sc["active_bssid"],
            recent_probes=probes,
        )

        table = Table(title=f"Evaluación MCDA - Paso {step}", style="dim")
        table.add_column("SSID", style="cyan")
        table.add_column("BSSID")
        table.add_column("RSSI (dBm)", justify="right")
        table.add_column("Airtime", justify="right")
        table.add_column("Score MCDA", justify="right", style="bold green")

        for c in sc["candidates"]:
            table.add_row(
                c.ssid,
                c.bssid,
                f"{c.rssi_dbm} dBm",
                f"{c.airtime_utilization_pct}%",
                f"{c.health_score:.1f}",
            )
        console.print(table)

        if decision.should_handover:
            console.print(
                f"[bold green]✔ ¡HANDOVER ACTIVADO! Conmutando a {decision.target_ssid} ({decision.target_bssid})[/bold green]"
            )
            console.print(f"[dim]{decision.reason}[/dim]")
            await executor.switch_network(decision.target_ssid, decision.target_bssid)
            await executor.warm_up_connection(duration_sec=1.5)
        else:
            console.print(f"[bold yellow]⏸ Conmutación retenida:[/bold yellow] [dim]{decision.reason}[/dim]")

        await asyncio.sleep(0.5)

    console.print(
        Panel(
            "[bold green]✔ Demostración completada exitosamente:[/bold green]\n"
            "El sistema previno el flapping prematuro, verificó la consistencia en 3 ciclos consecutivos\n"
            "y ejecutó la conmutación a Telyexpress_Pablo con fase de estabilización warm-up.",
            border_style="green",
        )
    )


if __name__ == "__main__":
    asyncio.run(run_live_simulation())
