"""Unsupervised Anomaly Detection and Connectivity Health Score Calculator."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from src.core.models import AnomalyReport, RFMetrics, SocketProbeMetrics

logger = logging.getLogger(__name__)


FEATURE_NAMES = [
    "rssi_dbm",
    "signal_pct",
    "airtime_utilization_pct",
    "loss_pct",
    "rtt_ms",
    "jitter_ms",
]


class LinkAnomalyDetector:
    """Predictive ML model evaluating network health and detecting degradation patterns."""

    def __init__(
        self,
        model_path: Optional[str] = "models/anomaly_detector.joblib",
        contamination: float = 0.05,
        anomaly_threshold: float = 0.65,
        preemptive_threshold: float = 45.0,
    ) -> None:
        self.model_path = Path(model_path) if model_path else None
        self.contamination = contamination
        self.anomaly_threshold = anomaly_threshold
        self.preemptive_threshold = preemptive_threshold

        self.model: Optional[IsolationForest] = None
        self.scaler = StandardScaler()
        self.is_fitted = False

        if self.model_path and self.model_path.exists():
            self.load(str(self.model_path))
        else:
            self._init_default_model()

    def _init_default_model(self) -> None:
        """Initializes default Isolation Forest estimator."""
        self.model = IsolationForest(
            n_estimators=100,
            contamination=self.contamination,
            random_state=42,
            n_jobs=-1,
        )

    def extract_features(
        self,
        rf: RFMetrics,
        probes: Optional[List[SocketProbeMetrics]] = None,
    ) -> np.ndarray:
        """Extracts normalized feature vector from RF and transport probe metrics."""
        avg_loss = 0.0
        avg_rtt = 15.0
        avg_jitter = 2.0

        if probes:
            valid = [p for p in probes if p.is_reachable]
            if valid:
                avg_loss = sum(p.packet_loss_pct for p in valid) / len(valid)
                avg_rtt = sum(p.rtt_ms for p in valid) / len(valid)
                avg_jitter = sum(p.jitter_ms for p in valid) / len(valid)

        vector = np.array(
            [
                rf.rssi_dbm,
                float(rf.signal_pct),
                rf.airtime_utilization_pct,
                avg_loss,
                avg_rtt,
                avg_jitter,
            ],
            dtype=np.float32,
        )
        return vector.reshape(1, -1)

    def fit(self, X: np.ndarray) -> None:
        """Fits the StandardScaler and Isolation Forest on training telemetry."""
        if len(X) < 10:
            raise ValueError(f"Insufficient training samples ({len(X)} < 10)")

        logger.info(f"Training LinkAnomalyDetector on {len(X)} telemetry samples...")
        self.scaler.fit(X)
        X_scaled = self.scaler.transform(X)

        self._init_default_model()
        assert self.model is not None
        self.model.fit(X_scaled)
        self.is_fitted = True
        logger.info("Model training completed successfully.")

    def predict(
        self,
        rf: RFMetrics,
        probes: Optional[List[SocketProbeMetrics]] = None,
    ) -> AnomalyReport:
        """Evaluates live metrics and produces an AnomalyReport with Health Score."""
        X_raw = self.extract_features(rf, probes)
        factors = {
            "rssi_dbm": float(X_raw[0, 0]),
            "signal_pct": float(X_raw[0, 1]),
            "airtime_pct": float(X_raw[0, 2]),
            "loss_pct": float(X_raw[0, 3]),
            "rtt_ms": float(X_raw[0, 4]),
            "jitter_ms": float(X_raw[0, 5]),
        }

        # Deterministic analytical fallback if model is not yet fitted
        if not self.is_fitted or self.model is None:
            return self._heuristic_evaluate(factors)

        # Scale features and query decision function
        X_scaled = self.scaler.transform(X_raw)
        raw_score = self.model.decision_function(X_scaled)[0]
        # In scikit-learn, decision_function returns negative values for anomalies
        # Normal samples typically have positive raw_score around 0.1 to 0.25
        # Anomalies have negative raw_score around -0.1 to -0.3
        # Normalize into [0.0, 1.0] where 1.0 = highly anomalous
        normalized_anomaly = float(np.clip(0.5 - (raw_score * 2.0), 0.0, 1.0))

        # Health score: 100 - (anomaly_score * 100)
        health_score = round(max(0.0, min(100.0, (1.0 - normalized_anomaly) * 100.0)), 1)
        is_anomaly = normalized_anomaly >= self.anomaly_threshold

        action = "NO_ACTION"
        if health_score <= self.preemptive_threshold:
            action = "TRIGGER_PREEMPTIVE_HANDOVER"
        elif is_anomaly:
            action = "AUDIT_CHANNEL_CONGESTION"

        return AnomalyReport(
            is_anomaly=is_anomaly,
            anomaly_score=round(normalized_anomaly, 3),
            health_score=health_score,
            contributing_factors=factors,
            recommended_action=action,
            timestamp=datetime.utcnow(),
        )

    def _heuristic_evaluate(self, factors: Dict[str, float]) -> AnomalyReport:
        """Heuristic evaluation when un-fitted."""
        penalty = 0.0
        # RSSI degradation
        if factors["rssi_dbm"] < -85:
            penalty += 45.0
        elif factors["rssi_dbm"] < -75:
            penalty += 30.0
        elif factors["rssi_dbm"] < -65:
            penalty += 15.0

        # Loss penalty
        penalty += min(40.0, factors["loss_pct"] * 2.0)

        # Airtime penalty
        if factors["airtime_pct"] > 80:
            penalty += 25.0
        elif factors["airtime_pct"] > 60:
            penalty += 10.0

        # Jitter penalty
        if factors["jitter_ms"] > 30:
            penalty += 15.0

        health_score = max(0.0, min(100.0, 100.0 - penalty))
        anomaly_score = float(np.clip(penalty / 100.0, 0.0, 1.0))
        is_anomaly = anomaly_score >= self.anomaly_threshold

        action = "NO_ACTION"
        if health_score <= self.preemptive_threshold:
            action = "TRIGGER_PREEMPTIVE_HANDOVER"
        elif is_anomaly:
            action = "AUDIT_CHANNEL_CONGESTION"

        return AnomalyReport(
            is_anomaly=is_anomaly,
            anomaly_score=anomaly_score,
            health_score=health_score,
            contributing_factors=factors,
            recommended_action=action,
            timestamp=datetime.utcnow(),
        )

    def save(self, path: Optional[str] = None) -> None:
        """Serializes trained model and scaler."""
        save_path = Path(path) if path else self.model_path
        if not save_path:
            raise ValueError("No path specified for saving model")

        save_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model": self.model,
                "scaler": self.scaler,
                "is_fitted": self.is_fitted,
                "contamination": self.contamination,
            },
            save_path,
        )
        logger.info(f"Saved LinkAnomalyDetector to {save_path}")

    def load(self, path: str) -> None:
        """Deserializes trained model and scaler."""
        data = joblib.load(path)
        self.model = data["model"]
        self.scaler = data["scaler"]
        self.is_fitted = data["is_fitted"]
        self.contamination = data.get("contamination", self.contamination)
        logger.info(f"Loaded LinkAnomalyDetector from {path}")
