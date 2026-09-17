"""Multi-Criteria Decision Analysis (MCDA) Roaming Engine with Deadband and Anti-Flapping Hysteresis."""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from src.core.interfaces import DecisionStrategy
from src.core.models import APCandidate, HandoverDecision, SocketProbeMetrics

logger = logging.getLogger(__name__)


class MCDARoamingEngine(DecisionStrategy):
    """Evaluates candidate APs using MCDA with temporal hysteresis, deadband and warm-up buffer."""

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        deadband_pct: float = 0.15,
        hysteresis_cycles: int = 3,
        warmup_duration_sec: float = 4.0,
    ) -> None:
        # Default criteria weights summing to 1.0
        self.weights = weights or {
            "rssi": 0.35,
            "airtime": 0.25,
            "loss": 0.25,
            "jitter": 0.15,
        }
        self.deadband_pct = deadband_pct
        self.hysteresis_cycles = hysteresis_cycles
        self.warmup_duration_sec = warmup_duration_sec

        # State tracking
        self._consecutive_favorable_cycles: int = 0
        self._favorable_candidate_bssid: Optional[str] = None
        self._last_handover_timestamp: float = 0.0

    def evaluate(
        self,
        candidates: List[APCandidate],
        current_bssid: str,
        recent_probes: Optional[List[SocketProbeMetrics]] = None,
    ) -> HandoverDecision:
        """Calculates MCDA score for all candidates and applies deadband, warm-up, and hysteresis."""
        now = time.time()
        current_bssid = current_bssid.lower()

        # 1. Warm-up buffer check: prevent handover during post-switch stabilization
        time_since_handover = now - self._last_handover_timestamp
        in_warmup = time_since_handover < self.warmup_duration_sec
        if in_warmup:
            return HandoverDecision(
                should_handover=False,
                current_bssid=current_bssid,
                current_score=100.0,
                in_warmup=True,
                reason=f"Warm-up buffer active ({time_since_handover:.1f}s / {self.warmup_duration_sec}s). Link stabilizing.",
            )

        if not candidates:
            return HandoverDecision(
                should_handover=False,
                current_bssid=current_bssid,
                current_score=0.0,
                reason="No candidate APs visible in scan.",
            )

        # 2. Extract probe metrics if available (loss & jitter)
        avg_loss = 0.0
        avg_jitter = 5.0
        if recent_probes:
            valid_probes = [p for p in recent_probes if p.is_reachable]
            if valid_probes:
                avg_loss = sum(p.packet_loss_pct for p in valid_probes) / len(valid_probes)
                avg_jitter = sum(p.jitter_ms for p in valid_probes) / len(valid_probes)

        # 3. Calculate MCDA score for each candidate
        scored_candidates: List[APCandidate] = []
        current_ap: Optional[APCandidate] = None

        for cand in candidates:
            cand_bssid = cand.bssid.lower()
            # For the current AP, use observed probe metrics; for alternate APs estimate default clean channel
            cand_loss = avg_loss if (cand_bssid == current_bssid) else 0.0
            cand_jitter = avg_jitter if (cand_bssid == current_bssid) else 5.0

            score = self._compute_mcda_score(
                rssi_dbm=cand.rssi_dbm,
                airtime_utilization_pct=cand.airtime_utilization_pct,
                loss_pct=cand_loss,
                jitter_ms=cand_jitter,
            )
            cand.health_score = round(score, 2)
            scored_candidates.append(cand)

            if cand_bssid == current_bssid:
                current_ap = cand

        # If current AP was not in scan results, synthesize placeholder
        current_score = current_ap.health_score if current_ap else 20.0

        # Sort candidates by Health Score descending
        scored_candidates.sort(key=lambda c: c.health_score, reverse=True)
        best_candidate = scored_candidates[0]

        # 4. If current AP is already the best candidate
        if best_candidate.bssid.lower() == current_bssid:
            self._reset_hysteresis()
            return HandoverDecision(
                should_handover=False,
                current_bssid=current_bssid,
                target_bssid=best_candidate.bssid,
                target_ssid=best_candidate.ssid,
                current_score=current_score,
                target_score=best_candidate.health_score,
                score_margin_pct=0.0,
                consecutive_cycles=0,
                in_deadband=False,
                reason="Current AP provides the highest MCDA score.",
            )

        # 5. Deadband (Zone of Indifference) verification
        score_diff = best_candidate.health_score - current_score
        relative_improvement = score_diff / max(current_score, 1.0)

        if relative_improvement < self.deadband_pct:
            self._reset_hysteresis()
            return HandoverDecision(
                should_handover=False,
                current_bssid=current_bssid,
                target_bssid=best_candidate.bssid,
                target_ssid=best_candidate.ssid,
                current_score=current_score,
                target_score=best_candidate.health_score,
                score_margin_pct=round(relative_improvement * 100, 2),
                consecutive_cycles=0,
                in_deadband=True,
                reason=(
                    f"Candidate improvement ({relative_improvement * 100:.1f}%) is within deadband zone "
                    f"(< {self.deadband_pct * 100:.0f}%). Roaming suppressed."
                ),
            )

        # 6. Anti-Flapping Temporal Hysteresis Counter
        if self._favorable_candidate_bssid == best_candidate.bssid.lower():
            self._consecutive_favorable_cycles += 1
        else:
            self._favorable_candidate_bssid = best_candidate.bssid.lower()
            self._consecutive_favorable_cycles = 1

        logger.info(
            f"Candidate {best_candidate.ssid} ({best_candidate.bssid}) beats current AP: "
            f"+{relative_improvement * 100:.1f}% (Cycle {self._consecutive_favorable_cycles}/{self.hysteresis_cycles})"
        )

        if self._consecutive_favorable_cycles >= self.hysteresis_cycles:
            # Hysteresis requirement fulfilled: trigger handover
            self._reset_hysteresis()
            self._last_handover_timestamp = now
            return HandoverDecision(
                should_handover=True,
                current_bssid=current_bssid,
                target_bssid=best_candidate.bssid,
                target_ssid=best_candidate.ssid,
                current_score=current_score,
                target_score=best_candidate.health_score,
                score_margin_pct=round(relative_improvement * 100, 2),
                consecutive_cycles=self.hysteresis_cycles,
                in_deadband=False,
                reason=(
                    f"Hysteresis condition met ({self.hysteresis_cycles} consecutive cycles with "
                    f"+{relative_improvement * 100:.1f}% improvement). Executing Handover."
                ),
            )
        else:
            return HandoverDecision(
                should_handover=False,
                current_bssid=current_bssid,
                target_bssid=best_candidate.bssid,
                target_ssid=best_candidate.ssid,
                current_score=current_score,
                target_score=best_candidate.health_score,
                score_margin_pct=round(relative_improvement * 100, 2),
                consecutive_cycles=self._consecutive_favorable_cycles,
                in_deadband=False,
                reason=(
                    f"Candidate exceeds threshold but awaiting temporal hysteresis confirmation "
                    f"({self._consecutive_favorable_cycles}/{self.hysteresis_cycles} cycles)."
                ),
            )

    def _compute_mcda_score(
        self,
        rssi_dbm: float,
        airtime_utilization_pct: float,
        loss_pct: float,
        jitter_ms: float,
    ) -> float:
        """Normalizes and computes composite 0-100 score."""
        # 1. Norm RSSI: -100 dBm (0.0) to -50 dBm (1.0)
        norm_rssi = max(0.0, min(1.0, (rssi_dbm + 100.0) / 50.0))

        # 2. Norm Airtime: 0% (1.0) to 100% (0.0)
        norm_airtime = 1.0 - max(0.0, min(1.0, airtime_utilization_pct / 100.0))

        # 3. Norm Loss: 0% (1.0) to 100% (0.0)
        norm_loss = 1.0 - max(0.0, min(1.0, loss_pct / 100.0))

        # 4. Norm Jitter: 0ms (1.0) to 100ms (0.0)
        norm_jitter = 1.0 - max(0.0, min(1.0, jitter_ms / 100.0))

        score = (
            (self.weights["rssi"] * norm_rssi)
            + (self.weights["airtime"] * norm_airtime)
            + (self.weights["loss"] * norm_loss)
            + (self.weights["jitter"] * norm_jitter)
        ) * 100.0

        return max(0.0, min(100.0, score))

    def _reset_hysteresis(self) -> None:
        self._consecutive_favorable_cycles = 0
        self._favorable_candidate_bssid = None
