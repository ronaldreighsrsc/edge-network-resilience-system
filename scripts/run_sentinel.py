"""OmniEdge Sentinel Unified CLI Launcher."""

from __future__ import annotations

import argparse
import asyncio
import subprocess
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

from src.engine.orchestrator import ResilienceOrchestrator
from src.storage.sqlite_repository import SQLiteTelemetryRepository


def run_daemon():
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    print("Starting OmniEdge Sentinel Autonomous Daemon (Real Field Telemetry)...")
    repo = SQLiteTelemetryRepository()
    orchestrator = ResilienceOrchestrator(repository=repo)
    try:
        asyncio.run(orchestrator.start())
    except KeyboardInterrupt:
        orchestrator.stop()
        print("\nDaemon stopped by user.")


def run_api(host: str = "0.0.0.0", port: int = 8000):
    print(f"Launching OmniEdge Sentinel REST API on http://{host}:{port} (Swagger docs: http://{host}:{port}/docs)...")
    import uvicorn
    uvicorn.run("src.api.app:app", host=host, port=port, reload=False)


def run_dashboard(port: int = 8501):
    print(f"Launching OmniEdge Sentinel Streamlit Dashboard on port {port}...")
    dashboard_path = PROJECT_ROOT / "src" / "dashboard" / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(dashboard_path), "--server.port", str(port)])


def run_demo():
    from scripts.simulate_edge_daemon import run_live_simulation
    asyncio.run(run_live_simulation())


def main():
    parser = argparse.ArgumentParser(description="OmniEdge Sentinel CLI")
    parser.add_argument(
        "--mode",
        choices=["daemon", "api", "dashboard", "demo", "generate-data"],
        default="demo",
        help="Execution mode (default: demo)",
    )
    parser.add_argument("--port", type=int, default=None, help="Port for API or Dashboard")
    args = parser.parse_args()

    if args.mode == "daemon":
        run_daemon()
    elif args.mode == "api":
        run_api(port=args.port or 8000)
    elif args.mode == "dashboard":
        run_dashboard(port=args.port or 8501)
    elif args.mode == "demo":
        run_demo()
    elif args.mode == "generate-data":
        from data.generate_azapa_dataset import generate_azapa_dataset
        generate_azapa_dataset()


if __name__ == "__main__":
    main()
