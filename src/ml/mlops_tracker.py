"""MLOps Experiment Tracker and Model Registry for Edge Deployments."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MLOpsTracker:
    """Lightweight, self-contained MLOps tracking and model registry for edge nodes."""

    def __init__(self, registry_dir: str = "models/registry") -> None:
        self.registry_dir = Path(registry_dir)
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.registry_dir / "experiment_history.json"
        self._init_history()

    def _init_history(self) -> None:
        if not self.history_file.exists():
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2)

    def log_experiment(
        self,
        experiment_name: str,
        params: Dict[str, Any],
        metrics: Dict[str, float],
        model_version: str,
        artifact_path: Optional[str] = None,
        notes: str = "",
    ) -> Dict[str, Any]:
        """Logs an MLOps experiment run with parameters, metrics, and artifact references."""
        now = datetime.now(timezone.utc)
        run_record = {
            "run_id": f"run_{int(now.timestamp())}",
            "timestamp": now.isoformat(),
            "experiment_name": experiment_name,
            "model_version": model_version,
            "params": params,
            "metrics": metrics,
            "artifact_path": artifact_path,
            "notes": notes,
        }

        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
            history.append(run_record)
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
            logger.info(f"Logged MLOps run {run_record['run_id']} for experiment '{experiment_name}'")
        except Exception as e:
            logger.error(f"Failed to log MLOps experiment: {e}")

        return run_record

    def get_runs(self) -> List[Dict[str, Any]]:
        """Returns all recorded experiment runs."""
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def get_latest_run(self) -> Optional[Dict[str, Any]]:
        """Returns the most recent experiment run."""
        runs = self.get_runs()
        return runs[-1] if runs else None
