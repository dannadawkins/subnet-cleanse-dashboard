"""
Dashboard de Subnet Cleanse (independiente de SSOT)
====================================================

QUE HACE:
  Lee el CSV que ya genera el reporte de reconciliacion de SSOT
  (ddi_reconciliation_<fecha>.csv) y te muestra 2 vistas:
    - Caso 1: FREE but IN USE
    - Caso 2: FREE but REFERENCED
  Cada fila tiene una columna "Estado" (Pendiente / Solicitado / Resuelto)
  que tu editas a mano y se guarda en un archivo local (estado_subnets.db),
  asi no se pierde cuando vuelves a cargar un CSV nuevo el mes siguiente.

REQUISITOS (una sola vez, en tu laptop):
  pip install -r requirements.txt

COMO OBTENER EL CSV CADA MES (en ssot-dev, por SSH):
  cd /opt/dn/ssot
  source venv/bin/activate
  python -m reports.ddi_reconciliation --conflicts-only --csv
  # esto escribe: reports/ddi_reconciliation/ddi_reconciliation_<fecha>.csv

  Despues bajas ese archivo a tu laptop, por ejemplo con scp (desde tu
  laptop, en otra terminal):
  scp usuario@ssot-dev:/dn/ssot/reports/ddi_reconciliation/ddi_reconciliation_<fecha>.csv .

COMO CORRER EL DASHBOARD (en tu laptop, carpeta donde esta este archivo):
  streamlit run subnet_cleanse_dashboard.py

  Se abre solo en tu navegador (http://localhost:8501). Ahi subes el CSV
  que bajaste, desde la barra lateral.
"""

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).parent / "estado_subnets.db"
ESTADOS = ["Pendiente", "Solicitado", "Resuelto"]

st.set_page_config(page_title="Subnet Cleanse Dashboard", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
    <style>
    .block-container {padding-top: 2rem;}
    div[data-testid="stMetric"] {
        background-color: #1e2530;
        border: 1px solid #333c48;
        border-radius: 10px;
        padding: 14px 18px;
    }
    div[data-testid="stMetricLabel"] { font-size: 0.85rem; opacity: 0.8; }
    .subnet-header {
        font-size: 1.9rem;
        font-weight: 700;
        margin-bottom: 0;
    }
    .subnet-subheader {
        font-size: 1rem;
        opacity: 0.7;
        margin-top: -6px;
        margin-bottom: 1.2rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Estado local (SQLite): recuerda que estado le pusiste a cada subred
# ---------------------------------------------------------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS estado (
            subnet TEXT PRIMARY KEY,
            estado TEXT,
            nota TEXT,
            ultima_actualizacion TEXT
        )
        """
    )
    return conn


def cargar_estados() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM estado", conn)
    conn.close()
    return df


def guardar_estados(df: pd.DataFrame):
    conn = get_conn()
    for _, row in df.iterrows():
        conn.execute(
            """
            INSERT INTO estado (subnet, estado, nota, ultima_actualizacion)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(subnet) DO UPDATE SET
                estado=excluded.estado,
                nota=excluded.nota,
                ultima_actualizacion=excluded.ultima_actualizacion
            """,
            (row["subnet"], row["Estado"], row.get("Nota", "")),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Sidebar: carga de archivo + info del proceso
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Datos")
    archivo = st.file_uploader("CSV de reconciliacion", type=["csv"])
    st.caption("Generado en ssot-dev con: `python -m reports.ddi_reconciliation --conflicts-only --csv`")
    st.divider()
    st.header("Que es cada caso")
    st.markdown(
        "**Caso 1 - FREE but IN USE**\n\n"
        "La subred esta en uso real pero 1DDI no se actualizo. "
        "Accion: corregir el Site ID en 1DDI.\n\n"
        "**Caso 2 - FREE but REFERENCED**\n\n"
        "La subred no esta en uso, pero quedan objetos/reglas de firewall "
        "(FMC) referenciandola. Accion: pedir borrado al equipo de firewall."
    )

st.markdown('<p class="subnet-header">Subnet Cleanse Dashboard</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="subnet-subheader">Seguimiento de subredes "FREE" en 1DDI con conflictos reales. '
    "No modifica nada en SSOT, 1DDI o FMC.</p>",
    unsafe_allow_html=True,
)

if archivo is None:
    st.info("Sube un CSV desde la barra lateral izquierda para ver el dashboard.")
    st.stop()

df = pd.read_csv(archivo)
estados_guardados = cargar_estados()

df = df.merge(estados_guardados[["subnet", "estado", "nota"]], on="subnet", how="left")
df["estado"] = df["estado"].fillna("Pendiente")
df["nota"] = df["nota"].fillna("")

caso1_df = df[df["verdict"] == "FREE but IN USE"]
caso2_df = df[df["verdict"] == "FREE but REFERENCED"]
total = len(df)
resueltas = (df["estado"] == "Resuelto").sum()
solicitadas = (df["estado"] == "Solicitado").sum()
pendientes = (df["estado"] == "Pendiente").sum()

# --- Fila de metricas -------------------------------------------------------
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total conflictos", total)
c2.metric("Caso 1 - IN USE", len(caso1_df))
c3.metric("Caso 2 - REFERENCED", len(caso2_df))
c4.metric("Resueltas", int(resueltas), delta=f"{resueltas / total:.0%}" if total else None)
c5.metric("Pendientes", int(pendientes))

if total:
    st.progress(resueltas / total, text=f"Progreso general: {resueltas}/{total} resueltas")

st.write("")


def tabla_caso(sub: pd.DataFrame, columnas: list[str], key: str):
    if sub.empty:
        st.success("Sin subredes pendientes en este caso.")
        return

    resumen = sub["estado"].value_counts().reindex(ESTADOS, fill_value=0)
    m1, m2, m3 = st.columns(3)
    m1.metric("Pendiente", int(resumen["Pendiente"]))
    m2.metric("Solicitado", int(resumen["Solicitado"]))
    m3.metric("Resuelto", int(resumen["Resuelto"]))

    filtro = st.multiselect(
        "Filtrar por estado", ESTADOS, default=ESTADOS, key=f"filtro_{key}"
    )
    vista = sub[sub["estado"].isin(filtro)].copy()
    vista = vista.rename(columns={"estado": "Estado", "nota": "Nota"})
    editable = vista[["subnet"] + columnas + ["Estado", "Nota"]]

    edited = st.data_editor(
        editable,
        key=key,
        column_config={
            "Estado": st.column_config.SelectboxColumn("Estado", options=ESTADOS, required=True),
            "subnet": st.column_config.TextColumn("Subred", disabled=True),
        },
        disabled=["subnet"] + columnas,
        hide_index=True,
        use_container_width=True,
    )

    if st.button("Guardar cambios", key=f"save_{key}", type="primary"):
        guardar_estados(edited)
        st.success(f"Guardado ({len(edited)} filas).")


tab1, tab2 = st.tabs(
    [f"Caso 1 - FREE but IN USE ({len(caso1_df)})", f"Caso 2 - FREE but REFERENCED ({len(caso2_df)})"]
)

with tab1:
    st.caption("Accion: confirmar el sitio real (interfaces/rutas/DNS) y corregir el Site ID en 1DDI.")
    tabla_caso(
        caso1_df,
        columnas=["subnet_name", "site_name", "interfaces", "routes", "dns"],
        key="caso1",
    )

with tab2:
    st.caption("Accion: preparar la solicitud de borrado de objetos/reglas y enviarla al equipo de firewall.")
    tabla_caso(
        caso2_df,
        columnas=["subnet_name", "site_name", "fmc_objects", "fmc_rules", "configs"],
        key="caso2",
    )

st.divider()
st.caption(
    "Estado guardado localmente en estado_subnets.db, junto a este script. "
    "No se borra al subir un CSV nuevo el proximo mes."
)
