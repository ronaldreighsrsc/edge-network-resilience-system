"""Unit tests for MLOps Anomaly Detection and Experiment Tracking."""

import numpy as np
import pytest
from src.core.models import RFMetrics, SocketProbeMetrics
from src.ml.anomaly_detector import LinkAnomalyDetector
from src.ml.mlops_tracker import MLOpsTracker


def test_feature_extraction(anomaly_detector, sample_rf_metrics, sample_probes):
    features = anomaly_detector.extract_features(sample_rf_metrics, sample_probes)
    assert features.shape == (1, 6)
    assert features[0, 0] == -52.0  # RSSI
    assert features[0, 1] == 87.0   # Signal pct
    assert features[0, 2] == 34.0   # Airtime pct


def test_heuristic_fallback_nominal(anomaly_detector, sample_rf_metrics, sample_probes):
    anomaly_detector.is_fitted = False
    report = anomaly_detector.predict(sample_rf_metrics, sample_probes)
    assert not report.is_anomaly
    assert report.health_score >= 80.0
    assert report.recommended_action == "NO_ACTION"


def test_heuristic_fallback_severe_degradation(anomaly_detector, sample_probes):
    anomaly_detector.is_fitted = False
    degraded_rf = RFMetrics(
        ssid="Telyexpress_Solares",
        bssid="c0:25:2f:5e:7e:42",
        rssi_dbm=-93.0,
        signal_pct=14,
        airtime_utilization_pct=95.0,
    )
    # High packet loss
    degraded_probes = [
        SocketProbeMetrics(target_name="gateway", target_ip="192.168.0.1", rtt_ms=150.0, jitter_ms=60.0, packet_loss_pct=40.0),
    ]
    report = anomaly_detector.predict(degraded_rf, degraded_probes)
    assert report.health_score < 45.0
    assert report.recommended_action == "TRIGGER_PREEMPTIVE_HANDOVER"


def test_fit_predict_and_persistence(tmp_path, sample_rf_metrics, sample_probes):
    model_file = tmp_path / "fitted_model.joblib"
    detector = LinkAnomalyDetector(model_path=str(model_file))

    # Generate synthetic training batch matching baseline
    np.random.seed(42)
    normal_samples = np.random.normal(
        loc=[-52.0, 87.0, 34.0, 0.0, 15.0, 2.0],
        scale=[1.5, 2.0, 3.0, 0.01, 2.0, 0.5],
        size=(150, 6),
    )
    detector.fit(normal_samples)
    assert detector.is_fitted

    # Predict normal point
    normal_rep = detector.predict(sample_rf_metrics, sample_probes)
    assert normal_rep.health_score >= 60.0

    # Save and reload
    detector.save(str(model_file))
    loaded_detector = LinkAnomalyDetector(model_path=str(model_file))
    assert loaded_detector.is_fitted

    loaded_rep = loaded_detector.predict(sample_rf_metrics, sample_probes)
    assert abs(loaded_rep.health_score - normal_rep.health_score) < 1.0


def test_mlops_tracker(mlops_tracker):
    run = mlops_tracker.log_experiment(
        experiment_name="unit_test_run",
        params={"contamination": 0.05, "n_estimators": 50},
        metrics={"f1_score": 0.94},
        model_version="v0.1.0-test",
        notes="Automated test run",
    )
    assert run["experiment_name"] == "unit_test_run"
    assert run["model_version"] == "v0.1.0-test"

    runs = mlops_tracker.get_runs()
    assert len(runs) == 1

    latest = mlops_tracker.get_latest_run()
    assert latest["run_id"] == run["run_id"]
