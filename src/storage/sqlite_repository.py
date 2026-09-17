"""SQLite implementation of TelemetryRepository configured in Write-Ahead Logging (WAL) mode."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, List, Optional

from src.core.interfaces import TelemetryRepository
from src.core.models import (
    AnomalyReport,
    HardwareEventType,
    HandoverDecision,
    IoTDevice,
    KernelEvent,
    RFMetrics,
    SocketProbeMetrics,
)

logger = logging.getLogger(__name__)


class SQLiteTelemetryRepository(TelemetryRepository):
    """Production-grade SQLite persistence optimized for Edge concurrent read/write via WAL."""

    def __init__(self, db_path: str = "data/telemetry.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provides an isolated connection configured with WAL and NORMAL pragmas."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        conn.row_factory = sqlite3.Row
        try:
            # Configure high-throughput edge pragmas
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA busy_timeout = 30000;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        """Create database tables and temporal indexes."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. RF Metrics Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rf_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    ssid TEXT NOT NULL,
                    bssid TEXT NOT NULL,
                    rssi_dbm REAL NOT NULL,
                    signal_pct INTEGER NOT NULL,
                    channel INTEGER NOT NULL,
                    band TEXT NOT NULL,
                    radio_type TEXT NOT NULL,
                    mcs_index INTEGER,
                    rx_rate_mbps REAL NOT NULL,
                    tx_rate_mbps REAL NOT NULL,
                    airtime_utilization_pct REAL NOT NULL,
                    connected_stations INTEGER NOT NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rf_timestamp ON rf_metrics(timestamp);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rf_bssid ON rf_metrics(bssid);")

            # 2. Socket Probe Metrics Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS socket_probes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    target_ip TEXT NOT NULL,
                    rtt_ms REAL NOT NULL,
                    jitter_ms REAL NOT NULL,
                    packet_loss_pct REAL NOT NULL,
                    tcp_handshake_ms REAL,
                    dns_resolution_ms REAL,
                    is_reachable INTEGER NOT NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_probes_timestamp ON socket_probes(timestamp);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_probes_target ON socket_probes(target_name);")

            # 3. IoT / SSDP Discovered Assets
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS iot_devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip_address TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    usn TEXT UNIQUE NOT NULL,
                    st TEXT NOT NULL,
                    location TEXT,
                    server_header TEXT,
                    friendly_name TEXT,
                    model_name TEXT,
                    open_ports TEXT,
                    is_ghost_session INTEGER NOT NULL,
                    last_seen TEXT NOT NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_iot_ip ON iot_devices(ip_address);")

            # 4. Kernel USB / Hardware Forensics
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS kernel_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_id INTEGER NOT NULL,
                    provider_name TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    vendor_id TEXT,
                    product_id TEXT,
                    serial_number TEXT,
                    device_description TEXT,
                    raw_payload TEXT
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_kernel_timestamp ON kernel_events(timestamp);")

            # 5. Anomaly Reports (MLOps)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS anomaly_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    is_anomaly INTEGER NOT NULL,
                    anomaly_score REAL NOT NULL,
                    health_score REAL NOT NULL,
                    contributing_factors TEXT,
                    recommended_action TEXT NOT NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_anomaly_timestamp ON anomaly_reports(timestamp);")

            # 6. Handover Decisions
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS handover_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    should_handover INTEGER NOT NULL,
                    current_bssid TEXT NOT NULL,
                    target_bssid TEXT,
                    target_ssid TEXT,
                    current_score REAL NOT NULL,
                    target_score REAL,
                    score_margin_pct REAL NOT NULL,
                    consecutive_cycles INTEGER NOT NULL,
                    in_deadband INTEGER NOT NULL,
                    in_warmup INTEGER NOT NULL,
                    reason TEXT NOT NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_handover_timestamp ON handover_decisions(timestamp);")

        logger.info(f"Initialized SQLite WAL repository at {self.db_path}")

    def save_rf_metrics(self, metrics: RFMetrics) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO rf_metrics (
                    timestamp, ssid, bssid, rssi_dbm, signal_pct, channel, band,
                    radio_type, mcs_index, rx_rate_mbps, tx_rate_mbps,
                    airtime_utilization_pct, connected_stations
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metrics.timestamp.isoformat(),
                    metrics.ssid,
                    metrics.bssid,
                    metrics.rssi_dbm,
                    metrics.signal_pct,
                    metrics.channel,
                    metrics.band,
                    metrics.radio_type,
                    metrics.mcs_index,
                    metrics.rx_rate_mbps,
                    metrics.tx_rate_mbps,
                    metrics.airtime_utilization_pct,
                    metrics.connected_stations,
                ),
            )
            return cursor.lastrowid or 0

    def save_socket_probes(self, probes: List[SocketProbeMetrics]) -> None:
        if not probes:
            return
        with self._get_connection() as conn:
            cursor = conn.cursor()
            records = [
                (
                    p.timestamp.isoformat(),
                    p.target_name,
                    p.target_ip,
                    p.rtt_ms,
                    p.jitter_ms,
                    p.packet_loss_pct,
                    p.tcp_handshake_ms,
                    p.dns_resolution_ms,
                    1 if p.is_reachable else 0,
                )
                for p in probes
            ]
            cursor.executemany(
                """
                INSERT INTO socket_probes (
                    timestamp, target_name, target_ip, rtt_ms, jitter_ms,
                    packet_loss_pct, tcp_handshake_ms, dns_resolution_ms, is_reachable
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )

    def save_iot_device(self, device: IoTDevice) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO iot_devices (
                    ip_address, port, usn, st, location, server_header,
                    friendly_name, model_name, open_ports, is_ghost_session, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(usn) DO UPDATE SET
                    ip_address=excluded.ip_address,
                    port=excluded.port,
                    st=excluded.st,
                    location=excluded.location,
                    server_header=excluded.server_header,
                    friendly_name=excluded.friendly_name,
                    model_name=excluded.model_name,
                    open_ports=excluded.open_ports,
                    is_ghost_session=excluded.is_ghost_session,
                    last_seen=excluded.last_seen
                """,
                (
                    device.ip_address,
                    device.port,
                    device.usn,
                    device.st,
                    device.location,
                    device.server_header,
                    device.friendly_name,
                    device.model_name,
                    json.dumps(device.open_ports),
                    1 if device.is_ghost_session else 0,
                    device.last_seen.isoformat(),
                ),
            )

    def save_kernel_event(self, event: KernelEvent) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO kernel_events (
                    timestamp, event_id, provider_name, event_type, device_id,
                    vendor_id, product_id, serial_number, device_description, raw_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.timestamp.isoformat(),
                    event.event_id,
                    event.provider_name,
                    event.event_type.value,
                    event.device_id,
                    event.vendor_id,
                    event.product_id,
                    event.serial_number,
                    event.device_description,
                    json.dumps(event.raw_payload),
                ),
            )

    def save_anomaly_report(self, report: AnomalyReport) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO anomaly_reports (
                    timestamp, is_anomaly, anomaly_score, health_score,
                    contributing_factors, recommended_action
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    report.timestamp.isoformat(),
                    1 if report.is_anomaly else 0,
                    report.anomaly_score,
                    report.health_score,
                    json.dumps(report.contributing_factors),
                    report.recommended_action,
                ),
            )

    def save_handover_decision(self, decision: HandoverDecision) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO handover_decisions (
                    timestamp, should_handover, current_bssid, target_bssid,
                    target_ssid, current_score, target_score, score_margin_pct,
                    consecutive_cycles, in_deadband, in_warmup, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.timestamp.isoformat(),
                    1 if decision.should_handover else 0,
                    decision.current_bssid,
                    decision.target_bssid,
                    decision.target_ssid,
                    decision.current_score,
                    decision.target_score,
                    decision.score_margin_pct,
                    decision.consecutive_cycles,
                    1 if decision.in_deadband else 0,
                    1 if decision.in_warmup else 0,
                    decision.reason,
                ),
            )

    def get_recent_rf_metrics(self, limit: int = 100) -> List[RFMetrics]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM rf_metrics ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
            return [
                RFMetrics(
                    ssid=row["ssid"],
                    bssid=row["bssid"],
                    rssi_dbm=row["rssi_dbm"],
                    signal_pct=row["signal_pct"],
                    channel=row["channel"],
                    band=row["band"],
                    radio_type=row["radio_type"],
                    mcs_index=row["mcs_index"],
                    rx_rate_mbps=row["rx_rate_mbps"],
                    tx_rate_mbps=row["tx_rate_mbps"],
                    airtime_utilization_pct=row["airtime_utilization_pct"],
                    connected_stations=row["connected_stations"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                )
                for row in rows
            ]

    def get_recent_probes(self, limit: int = 100) -> List[SocketProbeMetrics]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM socket_probes ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
            return [
                SocketProbeMetrics(
                    target_name=row["target_name"],
                    target_ip=row["target_ip"],
                    rtt_ms=row["rtt_ms"],
                    jitter_ms=row["jitter_ms"],
                    packet_loss_pct=row["packet_loss_pct"],
                    tcp_handshake_ms=row["tcp_handshake_ms"],
                    dns_resolution_ms=row["dns_resolution_ms"],
                    is_reachable=bool(row["is_reachable"]),
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                )
                for row in rows
            ]

    def get_recent_anomalies(self, limit: int = 100) -> List[AnomalyReport]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM anomaly_reports ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
            return [
                AnomalyReport(
                    is_anomaly=bool(row["is_anomaly"]),
                    anomaly_score=row["anomaly_score"],
                    health_score=row["health_score"],
                    contributing_factors=json.loads(row["contributing_factors"] or "{}"),
                    recommended_action=row["recommended_action"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                )
                for row in rows
            ]

    def get_iot_devices(self) -> List[IoTDevice]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM iot_devices ORDER BY last_seen DESC")
            rows = cursor.fetchall()
            return [
                IoTDevice(
                    ip_address=row["ip_address"],
                    port=row["port"],
                    usn=row["usn"],
                    st=row["st"],
                    location=row["location"],
                    server_header=row["server_header"],
                    friendly_name=row["friendly_name"],
                    model_name=row["model_name"],
                    open_ports=json.loads(row["open_ports"] or "[]"),
                    is_ghost_session=bool(row["is_ghost_session"]),
                    last_seen=datetime.fromisoformat(row["last_seen"]),
                )
                for row in rows
            ]

    def get_kernel_events(self, limit: int = 50) -> List[KernelEvent]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM kernel_events ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
            return [
                KernelEvent(
                    event_id=row["event_id"],
                    provider_name=row["provider_name"],
                    event_type=HardwareEventType(row["event_type"]),
                    device_id=row["device_id"],
                    vendor_id=row["vendor_id"],
                    product_id=row["product_id"],
                    serial_number=row["serial_number"],
                    device_description=row["device_description"],
                    raw_payload=json.loads(row["raw_payload"] or "{}"),
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                )
                for row in rows
            ]

    def get_handover_history(self, limit: int = 50) -> List[HandoverDecision]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM handover_decisions ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
            return [
                HandoverDecision(
                    should_handover=bool(row["should_handover"]),
                    current_bssid=row["current_bssid"],
                    target_bssid=row["target_bssid"],
                    target_ssid=row["target_ssid"],
                    current_score=row["current_score"],
                    target_score=row["target_score"],
                    score_margin_pct=row["score_margin_pct"],
                    consecutive_cycles=row["consecutive_cycles"],
                    in_deadband=bool(row["in_deadband"]),
                    in_warmup=bool(row["in_warmup"]),
                    reason=row["reason"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                )
                for row in rows
            ]
