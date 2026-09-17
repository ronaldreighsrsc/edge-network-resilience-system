"""Unit and integration tests for MCDA Roaming Engine, Deadband, and Hysteresis."""

import time
import pytest
from src.core.models import APCandidate, SocketProbeMetrics
from src.engine.mcda_engine import MCDARoamingEngine


def test_mcda_score_math():
    engine = MCDARoamingEngine()
    # Ideal signal: -50 dBm (1.0), 0% airtime (1.0), 0% loss (1.0), 0ms jitter (1.0)
    score_perfect = engine._compute_mcda_score(
        rssi_dbm=-50.0,
        airtime_utilization_pct=0.0,
        loss_pct=0.0,
        jitter_ms=0.0,
    )
    assert score_perfect == 100.0

    # Worst signal: -100 dBm (0.0), 100% airtime (0.0), 100% loss (0.0), 100ms jitter (0.0)
    score_worst = engine._compute_mcda_score(
        rssi_dbm=-100.0,
        airtime_utilization_pct=100.0,
        loss_pct=100.0,
        jitter_ms=100.0,
    )
    assert score_worst == 0.0


def test_mcda_current_ap_best_no_handover(mcda_engine, sample_candidates, sample_probes):
    decision = mcda_engine.evaluate(
        candidates=sample_candidates,
        current_bssid="c0:25:2f:5e:7e:42",  # Solares is current
        recent_probes=sample_probes,
    )
    assert not decision.should_handover
    assert decision.target_bssid == "c0:25:2f:5e:7e:42"
    assert "highest MCDA score" in decision.reason


def test_mcda_deadband_suppresses_minor_improvement(mcda_engine):
    # Current AP has score ~60, candidate has score ~64 (relative improvement <15%)
    candidates = [
        APCandidate(
            ssid="Current_AP",
            bssid="11:11:11:11:11:11",
            rssi_dbm=-70.0,
            signal_pct=60,
            channel=1,
            band="2.4 GHz",
            airtime_utilization_pct=40.0,
            is_current=True,
        ),
        APCandidate(
            ssid="Marginal_Alt",
            bssid="22:22:22:22:22:22",
            rssi_dbm=-68.0,
            signal_pct=64,
            channel=6,
            band="2.4 GHz",
            airtime_utilization_pct=38.0,
            is_current=False,
        ),
    ]
    decision = mcda_engine.evaluate(
        candidates=candidates,
        current_bssid="11:11:11:11:11:11",
    )
    assert not decision.should_handover
    assert decision.in_deadband
    assert "deadband" in decision.reason.lower()


def test_mcda_hysteresis_three_cycles_requirement(mcda_engine):
    # Degraded current AP vs strong alternate AP
    candidates = [
        APCandidate(
            ssid="Solares_Degraded",
            bssid="c0:25:2f:5e:7e:42",
            rssi_dbm=-93.0,
            signal_pct=14,
            channel=1,
            band="2.4 GHz",
            airtime_utilization_pct=85.0,
            is_current=True,
        ),
        APCandidate(
            ssid="Pablo_Strong",
            bssid="c0:25:2f:72:9e:4c",
            rssi_dbm=-60.0,
            signal_pct=80,
            channel=10,
            band="2.4 GHz",
            airtime_utilization_pct=20.0,
            is_current=False,
        ),
    ]

    # Cycle 1: should NOT handover, consecutive_cycles=1
    d1 = mcda_engine.evaluate(candidates, current_bssid="c0:25:2f:5e:7e:42")
    assert not d1.should_handover
    assert d1.consecutive_cycles == 1
    assert "awaiting temporal hysteresis confirmation" in d1.reason

    # Cycle 2: should NOT handover, consecutive_cycles=2
    d2 = mcda_engine.evaluate(candidates, current_bssid="c0:25:2f:5e:7e:42")
    assert not d2.should_handover
    assert d2.consecutive_cycles == 2

    # Cycle 3: requirement fulfilled! Handover executed!
    d3 = mcda_engine.evaluate(candidates, current_bssid="c0:25:2f:5e:7e:42")
    assert d3.should_handover
    assert d3.consecutive_cycles == 3
    assert d3.target_ssid == "Pablo_Strong"
    assert d3.target_bssid == "c0:25:2f:72:9e:4c"
    assert "Hysteresis condition met" in d3.reason


def test_mcda_hysteresis_counter_reset_on_recovery(mcda_engine):
    degraded_candidates = [
        APCandidate(ssid="Solares", bssid="c0:25:2f:5e:7e:42", rssi_dbm=-90.0, signal_pct=20, channel=1, band="2.4 GHz", airtime_utilization_pct=80.0),
        APCandidate(ssid="Pablo", bssid="c0:25:2f:72:9e:4c", rssi_dbm=-65.0, signal_pct=70, channel=10, band="2.4 GHz", airtime_utilization_pct=20.0),
    ]

    # Cycle 1: candidate leads
    d1 = mcda_engine.evaluate(degraded_candidates, current_bssid="c0:25:2f:5e:7e:42")
    assert d1.consecutive_cycles == 1

    # Solares recovers
    recovered_candidates = [
        APCandidate(ssid="Solares", bssid="c0:25:2f:5e:7e:42", rssi_dbm=-50.0, signal_pct=100, channel=1, band="2.4 GHz", airtime_utilization_pct=20.0),
        APCandidate(ssid="Pablo", bssid="c0:25:2f:72:9e:4c", rssi_dbm=-75.0, signal_pct=50, channel=10, band="2.4 GHz", airtime_utilization_pct=40.0),
    ]
    d2 = mcda_engine.evaluate(recovered_candidates, current_bssid="c0:25:2f:5e:7e:42")
    assert not d2.should_handover
    assert d2.consecutive_cycles == 0


def test_mcda_warmup_buffer_suppression(mcda_engine):
    # Simulate that a handover just occurred
    mcda_engine._last_handover_timestamp = time.time()
    candidates = [
        APCandidate(ssid="Alt", bssid="22:22:22:22:22:22", rssi_dbm=-50.0, signal_pct=100, channel=1, band="2.4 GHz", airtime_utilization_pct=10.0),
    ]
    decision = mcda_engine.evaluate(candidates, current_bssid="11:11:11:11:11:11")
    assert not decision.should_handover
    assert decision.in_warmup
    assert "Warm-up buffer active" in decision.reason


def test_mcda_no_candidates_returns_safe_decision(mcda_engine):
    decision = mcda_engine.evaluate([], current_bssid="11:11:11:11:11:11")
    assert not decision.should_handover
    assert "No candidate APs" in decision.reason
