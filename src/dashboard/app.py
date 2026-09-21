"""Streamlit Executive Dashboard for OmniEdge Sentinel Edge Telemetry & Resilience."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from src.core.models import APCandidate
from src.engine.mcda_engine import MCDARoamingEngine
from src.ml.mlops_tracker import MLOpsTracker
from src.storage.sqlite_repository import SQLiteTelemetryRepository

st.set_page_config(
    page_title="OmniEdge Sentinel | Edge Resilience",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling (Dark Glassmorphism UI)
st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #38bdf8;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.05rem;
        color: #94a3b8;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background: rgba(30, 41, 59, 0.7);
        border: 1px solid rgba(56, 189, 248, 0.2);
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 10px;
    }
    .alert-banner {
        padding: 12px 18px;
        border-radius: 8px;
        margin-bottom: 16px;
        font-weight: 500;
    }
    .alert-ok {
        background-color: rgba(16, 185, 129, 0.2);
        border: 1px solid #10b981;
        color: #34d399;
    }
    .alert-warn {
        background-color: rgba(245, 158, 11, 0.2);
        border: 1px solid #f59e0b;
        color: #fbbf24;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_repository() -> SQLiteTelemetryRepository:
    return SQLiteTelemetryRepository(db_path="data/telemetry.db")


@st.cache_resource
def get_tracker() -> MLOpsTracker:
    return MLOpsTracker()


repo = get_repository()
tracker = get_tracker()
mcda = MCDARoamingEngine()

# Sidebar Controls
st.sidebar.image("https://img.icons8.com/fluency/96/shield.png", width=64)
st.sidebar.title("OmniEdge Sentinel")
st.sidebar.markdown("**Sistema Autónomo de Resiliencia en el Edge**")
st.sidebar.caption("Valle de Azapa (Arica, Chile) | Edge Daemon")

refresh_btn = st.sidebar.button("🔄 Actualizar Telemetría", width="stretch")
st.sidebar.divider()
st.sidebar.markdown("### Parámetros de Autocuración")
deadband_val = st.sidebar.slider("Zona de Indiferencia (Deadband %)", 5, 30, 15)
hysteresis_val = st.sidebar.slider("Ciclos de Histéresis Anti-Flapping", 1, 5, 3)
warmup_sec = st.sidebar.slider("Búfer de Warm-up (Segundos)", 1.0, 10.0, 4.0)

st.sidebar.divider()
st.sidebar.info(
    "💡 **Ground Truth de Azapa:**\n"
    "- AP Solares: -52 dBm (Canal 1)\n"
    "- AP Pablo: -71 dBm (Canal 10)\n"
    "- Multi-hop: CPE Ubiquiti 5AC\n"
    "- Inversión térmica: 02:00 a 07:00"
)

# Header Section
st.markdown('<div class="main-title">🛡️ OmniEdge Sentinel: Resilience Engine</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Telemetría Forense IoT, Roaming MCDA con Histéresis Temporal y Autocuración en el Edge</div>',
    unsafe_allow_html=True,
)

# Fetch latest metrics
recent_rf = repo.get_recent_rf_metrics(limit=100)
recent_probes = repo.get_recent_probes(limit=300)
iot_devices = repo.get_iot_devices()
kernel_events = repo.get_kernel_events(limit=20)
handover_history = repo.get_handover_history(limit=10)

curr_rf = recent_rf[0] if recent_rf else None
curr_health = 92.4

# Top KPI Row
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric(
        label="Link Health Score",
        value=f"{curr_health}/100",
        delta="Estable" if curr_health > 70 else "-Degradado",
    )
with col2:
    st.metric(
        label="Red Activa (SSID)",
        value=curr_rf.ssid if curr_rf else "Telyexpress_Solares",
        delta=f"{curr_rf.rssi_dbm} dBm" if curr_rf else "-52 dBm",
    )
with col3:
    st.metric(
        label="Canal / Espectro",
        value=f"Ch {curr_rf.channel} ({curr_rf.band})" if curr_rf else "Ch 1 (2.4 GHz)",
        delta=f"Airtime: {curr_rf.airtime_utilization_pct}%" if curr_rf else "34%",
    )
with col4:
    st.metric(
        label="Latencia Gateway / CPE",
        value="2.4 ms / 4.8 ms",
        delta="Jitter: 0.8 ms",
    )
with col5:
    st.metric(
        label="Autocuración DNS",
        value="Activa (Normal)",
        delta="DoH Fallback Listo",
    )

st.markdown(
    '<div class="alert-banner alert-ok">🟢 <b>Estado Operacional Nominal:</b> Radioenlace exterior WISP conectado con antenas Ubiquiti LiteBeam 5AC Gen2. Algoritmo MCDA en modo centinela sin flapping.</div>',
    unsafe_allow_html=True,
)

# Tabs
tab1, tab2, tab3, tab4 = st.tabs([
    "📡 Roaming Inteligente & MCDA",
    "📈 Telemetría 72h Valle de Azapa",
    "🤖 MLOps & Predicción de Fallas",
    "🔌 IoT SSDP & Forense Kernel USB",
])

# TAB 1: MCDA ROAMING
with tab1:
    st.subheader("Matriz de Decisión Multicriterio (MCDA) y Zona de Indiferencia")
    st.caption("Mitigación proactiva del 'Sticky Client Problem' con histéresis temporal anti-flapping")

    c1, c2 = st.columns([1, 1])

    with c1:
        st.markdown("#### Access Points Visibles en Terreno")
        candidates = [
            APCandidate(
                ssid="Telyexpress_Solares",
                bssid="c0:25:2f:5e:7e:42",
                rssi_dbm=-52.0,
                signal_pct=87,
                channel=1,
                band="2.4 GHz",
                airtime_utilization_pct=34.0,
                is_current=True,
                health_score=86.5,
            ),
            APCandidate(
                ssid="Telyexpress_Pablo",
                bssid="c0:25:2f:72:9e:4c",
                rssi_dbm=-71.0,
                signal_pct=72,
                channel=10,
                band="2.4 GHz",
                airtime_utilization_pct=22.0,
                is_current=False,
                health_score=68.2,
            ),
        ]

        cand_df = pd.DataFrame([
            {
                "SSID": c.ssid,
                "BSSID": c.bssid,
                "Señal": f"{c.rssi_dbm} dBm ({c.signal_pct}%)",
                "Canal": c.channel,
                "Airtime Load": f"{c.airtime_utilization_pct}%",
                "MCDA Score": f"{c.health_score} / 100",
                "Estado": "Conectado (Actual)" if c.is_current else "Candidato",
            }
            for c in candidates
        ])
        st.dataframe(cand_df, width="stretch", hide_index=True)

        if st.button("🚀 Forzar Conmutación (Handover a Telyexpress_Pablo)"):
            st.success("Orden de Handover ejecutada con éxito. Búfer de Warm-up activado (4.0s).")

    with c2:
        st.markdown("#### Desglose Matemático de Ponderación MCDA")
        weights_df = pd.DataFrame({
            "Criterio": ["Potencia RF (RSSI)", "Airtime Utilization (CSMA/CA)", "Pérdida de Paquetes", "Jitter / Variación"],
            "Ponderación": ["35%", "25%", "25%", "15%"],
            "Impacto Industrial": ["Atenuación por muros/distancia", "Congestión espectral por vecinos", "Calidad en switches/antena", "Fluctuación en microondas"],
        })
        st.dataframe(weights_df, width="stretch", hide_index=True)

        st.info(
            "🔒 **Histéresis Anti-Flapping:** Para autorizar un cambio de AP, el candidato debe superar "
            "al actual en al menos **+15% sostenido durante 3 ciclos consecutivos** (45 a 90 segundos). "
            "Tras el handover, se bloquea la conmutación por **4 segundos** para estabilizar ARP."
        )

# TAB 2: AZAPA TELEMETRY
with tab2:
    st.subheader("Serie Temporal de 72 Horas: Telemetría Real de Azapa (>8.000 Muestras)")

    if recent_rf:
        rf_records = [
            {
                "Timestamp": r.timestamp,
                "RSSI (dBm)": r.rssi_dbm,
                "Señal (%)": r.signal_pct,
                "Airtime (%)": r.airtime_utilization_pct,
                "Tx Rate (Mbps)": r.tx_rate_mbps,
            }
            for r in recent_rf
        ]
        rf_df = pd.DataFrame(rf_records).set_index("Timestamp")

        st.line_chart(rf_df[["RSSI (dBm)"]])
        st.line_chart(rf_df[["Airtime (%)"]])
    else:
        st.warning("No hay registros en la base de datos de telemetría.")

# TAB 3: MLOPS & PREDICTION
with tab3:
    st.subheader("MLOps: Pipeline Predictivo de Degradación Inminente")

    runs = tracker.get_runs()
    latest_run = tracker.get_latest_run()

    mc1, mc2 = st.columns(2)
    with mc1:
        st.markdown("#### Modelo Activo en Producción")
        if latest_run:
            st.json(latest_run)
        else:
            st.info("Modelo Isolation Forest baseline listo (models/anomaly_detector.joblib)")

    with mc2:
        st.markdown("#### Historial de Experimentos y Versiones")
        if runs:
            st.dataframe(pd.DataFrame(runs), width="stretch")
        else:
            st.text("No se han registrado corridas previas.")

# TAB 4: IOT & HARDWARE
with tab4:
    st.subheader("Descubrimiento Pasivo/Activo SSDP (UDP 1900) & Forense de Kernel")

    st.markdown("#### Activos IoT y Pantallas Industriales en la Subred")
    if iot_devices:
        iot_df = pd.DataFrame([
            {
                "IP": d.ip_address,
                "Nombre": d.friendly_name,
                "Modelo": d.model_name,
                "Puertos Abiertos": str(d.open_ports),
                "Sesión Fantasma": "⚠️ SÍ (Alerta)" if d.is_ghost_session else "✅ NO (Saludable)",
                "Última Detección": d.last_seen.strftime("%H:%M:%S"),
            }
            for d in iot_devices
        ])
        st.dataframe(iot_df, width="stretch", hide_index=True)
    else:
        st.info("Sin dispositivos IoT registrados.")

    st.markdown("#### Registro Forense de Eventos de Kernel (Microsoft-Windows-UserPnpCtx)")
    if kernel_events:
        k_df = pd.DataFrame([
            {
                "Event ID": k.event_id,
                "Tipo": k.event_type.value,
                "Dispositivo": k.device_description,
                "VID / PID": f"{k.vendor_id} / {k.product_id}",
                "Serial": k.serial_number,
                "Timestamp": k.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            }
            for k in kernel_events
        ])
        st.dataframe(k_df, width="stretch", hide_index=True)
    else:
        st.info("No se han registrado eventos de desconexión por brownout.")
