"""
Dashboard de Subnet Cleanse (independiente de SSOT)
====================================================

QUE HACE:
  Lee el CSV que ya genera el reporte de reconciliacion de SSOT
  (ddi_reconciliation_<fecha>.csv) y te muestra 2 tablas:
    - Caso 1: FREE but IN USE
    - Caso 2: FREE but REFERENCED
  Cada fila tiene una columna "Estado" (Pendiente / Solicitado / Resuelto)
  que tu editas a mano y se guarda en un archivo local (estado.db), asi
  no se pierde cuando vuelves a cargar un CSV nuevo el mes siguiente.

REQUISITOS (una sola vez, en tu laptop):
  pip install streamlit pandas

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
  que bajaste, y ya ves las 2 tablas.
"""

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).parent / "estado_subnets.db"
ESTADOS = ["Pendiente", "Solicitado", "Resuelto"]

st.set_page_config(page_title="Subnet Cleanse Dashboard", layout="wide")
st.title("Subnet Cleanse Dashboard")
st.caption("Datos: reporte de reconciliación de SSOT (`ddi_reconciliation`). No modifica nada en SSOT/DDI/FMC.")


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
# Cargar el CSV de reconciliación
# ---------------------------------------------------------------------------
archivo = st.file_uploader(
    "Sube el CSV de reconciliación (ddi_reconciliation_<fecha>.csv)", type=["csv"]
)

if archivo is None:
    st.info("Sube un CSV para ver el dashboard. Instrucciones de cómo generarlo arriba, en el docstring del script.")
    st.stop()

df = pd.read_csv(archivo)
estados_guardados = cargar_estados()

# Une el estado guardado (si existe) con los datos del CSV
df = df.merge(estados_guardados[["subnet", "estado", "nota"]], on="subnet", how="left")
df["estado"] = df["estado"].fillna("Pendiente")
df["nota"] = df["nota"].fillna("")


def tabla_caso(df: pd.DataFrame, verdict: str, columnas: list[str], titulo: str, key: str):
    sub = df[df["verdict"] == verdict].copy()
    st.subheader(f"{titulo} ({len(sub)} subredes)")
    if sub.empty:
        st.write("Sin subredes en este caso.")
        return

    sub = sub.rename(columns={"estado": "Estado", "nota": "Nota"})
    editable = sub[["subnet"] + columnas + ["Estado", "Nota"]]

    edited = st.data_editor(
        editable,
        key=key,
        column_config={
            "Estado": st.column_config.SelectboxColumn("Estado", options=ESTADOS, required=True),
        },
        disabled=["subnet"] + columnas,
        hide_index=True,
        use_container_width=True,
    )

    if st.button(f"Guardar cambios - {titulo}", key=f"save_{key}"):
        guardar_estados(edited)
        st.success("Guardado.")


# --- Caso 1: FREE but IN USE -------------------------------------------------
tabla_caso(
    df,
    verdict="FREE but IN USE",
    columnas=["subnet_name", "site_name", "interfaces", "routes", "dns"],
    titulo="Caso 1 — FREE but IN USE (corregir Site ID en 1DDI)",
    key="caso1",
)

st.divider()

# --- Caso 2: FREE but REFERENCED --------------------------------------------
tabla_caso(
    df,
    verdict="FREE but REFERENCED",
    columnas=["subnet_name", "site_name", "fmc_objects", "fmc_rules", "configs"],
    titulo="Caso 2 — FREE but REFERENCED (pedir borrado en FMC)",
    key="caso2",
)

st.divider()
st.caption(
    "Estado guardado localmente en estado_subnets.db, junto a este script. "
    "No se borra al subir un CSV nuevo el próximo mes."
)
