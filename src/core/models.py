"""Domain models for OmniEdge Sentinel edge network resilience platform."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class HardwareEventType(str, Enum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    BROWNOUT = "BROWNOUT"
    UNKNOWN = "UNKNOWN"


class RFMetrics(BaseModel):
    """Layer 1 & Layer 2 RF physical and data link metrics."""
    ssid: str = Field(..., description="Network Service Set Identifier")
    bssid: str = Field(..., description="Access Point BSSID MAC address")
    rssi_dbm: float = Field(..., description="Received Signal Strength Indicator in dBm")
    signal_pct: int = Field(default=0, ge=0, le=100, description="Signal quality 0-100%")
    channel: int = Field(default=1, description="Operating Wi-Fi channel")
    band: str = Field(default="2.4 GHz", description="RF frequency band")
    radio_type: str = Field(default="802.11ax", description="802.11 standard")
    mcs_index: Optional[int] = Field(default=None, description="Modulation and Coding Scheme Index")
    rx_rate_mbps: float = Field(default=0.0, ge=0.0, description="Negotiated Rx link rate in Mbps")
    tx_rate_mbps: float = Field(default=0.0, ge=0.0, description="Negotiated Tx link rate in Mbps")
    airtime_utilization_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="CSMA/CA Channel airtime load")
    connected_stations: int = Field(default=0, ge=0, description="Number of BSS stations associated")
    timestamp: datetime = Field(default_factory=utc_now)


class APCandidate(BaseModel):
    """Candidate Access Point evaluated by MCDA Roaming Engine."""
    ssid: str
    bssid: str
    rssi_dbm: float
    signal_pct: int
    channel: int
    band: str
    airtime_utilization_pct: float
    is_current: bool = False
    health_score: float = 0.0


class SocketProbeMetrics(BaseModel):
    """Layer 3 & Layer 4 transport connectivity metrics."""
    target_name: str = Field(..., description="Logical name (e.g. gateway, cpe_outdoor, dns)")
    target_ip: str = Field(..., description="Target IPv4 or IPv6 address")
    rtt_ms: float = Field(default=0.0, ge=0.0, description="Round Trip Time in milliseconds")
    jitter_ms: float = Field(default=0.0, ge=0.0, description="Latency variance / jitter in ms")
    packet_loss_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Packet loss percentage")
    tcp_handshake_ms: Optional[float] = Field(default=None, description="TCP 3-Way Handshake establishment latency")
    dns_resolution_ms: Optional[float] = Field(default=None, description="DNS lookup time in ms")
    is_reachable: bool = True
    timestamp: datetime = Field(default_factory=utc_now)


class NetworkMetrics(BaseModel):
    """Aggregated network observation snapshot."""
    rf: RFMetrics
    probes: List[SocketProbeMetrics] = Field(default_factory=list)
    active_interface: str = "Wi-Fi"
    public_ip: Optional[str] = None
    is_online: bool = True
    timestamp: datetime = Field(default_factory=utc_now)


class IoTDevice(BaseModel):
    """Discovered UPnP / SSDP IoT device on the edge subnet."""
    ip_address: str
    port: int = 1900
    usn: str = Field(..., description="Unique Service Name")
    st: str = Field(..., description="Search Target / Device Type")
    location: Optional[str] = None
    server_header: Optional[str] = None
    friendly_name: Optional[str] = None
    model_name: Optional[str] = None
    open_ports: List[int] = Field(default_factory=list)
    is_ghost_session: bool = False
    last_seen: datetime = Field(default_factory=utc_now)


class KernelEvent(BaseModel):
    """Windows PnP Kernel / Hardware event for USB adapters."""
    event_id: int
    provider_name: str = "Microsoft-Windows-UserPnpCtx"
    event_type: HardwareEventType = HardwareEventType.UNKNOWN
    device_id: str
    vendor_id: Optional[str] = None
    product_id: Optional[str] = None
    serial_number: Optional[str] = None
    device_description: Optional[str] = None
    timestamp: datetime = Field(default_factory=utc_now)
    raw_payload: Dict[str, Any] = Field(default_factory=dict)


class AnomalyReport(BaseModel):
    """Predictive Machine Learning health evaluation."""
    is_anomaly: bool = False
    anomaly_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Normalized anomaly score")
    health_score: float = Field(default=100.0, ge=0.0, le=100.0, description="Overall Link Health 0-100")
    contributing_factors: Dict[str, float] = Field(default_factory=dict)
    recommended_action: str = "NO_ACTION"
    timestamp: datetime = Field(default_factory=utc_now)


class HandoverDecision(BaseModel):
    """Result of Multi-Criteria Decision Analysis (MCDA) evaluation."""
    should_handover: bool
    current_bssid: str
    target_bssid: Optional[str] = None
    target_ssid: Optional[str] = None
    current_score: float
    target_score: Optional[float] = None
    score_margin_pct: float = 0.0
    consecutive_cycles: int = 0
    in_deadband: bool = False
    in_warmup: bool = False
    reason: str
    timestamp: datetime = Field(default_factory=utc_now)
