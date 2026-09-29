"""
Subnet Cleanse Dashboard (standalone, reads a CSV produced by SSOT)
====================================================================

WHAT IT DOES:
  Reads the CSV produced by SSOT's reconciliation report
  (ddi_reconciliation_<date>.csv) and shows two tabs:
    - Case 1: FREE but IN USE
    - Case 2: FREE but REFERENCED
  Each row has a "Status" column (Pending / Requested / Resolved) that you
  edit by hand. It is saved locally (estado_subnets.db) so it is not lost
  when you upload a new CSV next month.

REQUIREMENTS (once, on your laptop):
  pip install -r requirements.txt

HOW TO GET THE CSV EACH MONTH (on ssot-dev, over SSH):
  cd /opt/dn/ssot
  source venv/bin/activate
  python -m reports.ddi_reconciliation --conflicts-only --csv
  # writes: reports/ddi_reconciliation/ddi_reconciliation_<date>.csv

  Then download it to your laptop, e.g. with scp (from your laptop, in
  another terminal):
  scp user@ssot-dev:/dn/ssot/reports/ddi_reconciliation/ddi_reconciliation_<date>.csv .

HOW TO RUN THE DASHBOARD (on your laptop, in this folder):
  streamlit run subnet_cleanse_dashboard.py

  Opens automatically in your browser (http://localhost:8501). Upload the
  CSV from the sidebar.
"""

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).parent / "estado_subnets.db"
STATUSES = ["Pending", "Requested", "Resolved"]

st.set_page_config(page_title="Subnet Cleanse Dashboard", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
    <style>
    .block-container {padding-top: 2rem;}
    div[data-testid="stMetric"] {
        background-color: rgba(127, 127, 127, 0.08);
        border: 1px solid rgba(127, 127, 127, 0.25);
        border-radius: 10px;
        padding: 14px 18px;
    }
    div[data-testid="stMetricLabel"] { font-size: 0.85rem; opacity: 0.8; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Local status store (SQLite): remembers what status you set per subnet
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


def load_status() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM estado", conn)
    conn.close()
    return df


def save_status(df: pd.DataFrame):
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
            (row["subnet"], row["Status"], row.get("Notes", "")),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Sidebar: file upload
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Data")
    uploaded_file = st.file_uploader("Reconciliation CSV", type=["csv"])
    st.caption("Generated on ssot-dev with: `python -m reports.ddi_reconciliation --conflicts-only --csv`")

st.title("Subnet Cleanse Dashboard")

if uploaded_file is None:
    st.info("Upload a CSV from the left sidebar to view the dashboard.")
    st.stop()

df = pd.read_csv(uploaded_file)
saved_status = load_status()

df = df.merge(saved_status[["subnet", "estado", "nota"]], on="subnet", how="left")
df["estado"] = df["estado"].fillna("Pending")
df["nota"] = df["nota"].fillna("")

case1_df = df[df["verdict"] == "FREE but IN USE"]
case2_df = df[df["verdict"] == "FREE but REFERENCED"]
total = len(df)
resolved = (df["estado"] == "Resolved").sum()
pending = (df["estado"] == "Pending").sum()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total conflicts", total)
c2.metric("Case 1 - IN USE", len(case1_df))
c3.metric("Case 2 - REFERENCED", len(case2_df))
c4.metric("Resolved", int(resolved), delta=f"{resolved / total:.0%}" if total else None)
c5.metric("Pending", int(pending))

if total:
    st.progress(resolved / total, text=f"Overall progress: {resolved}/{total} resolved")

st.write("")


def status_table(sub: pd.DataFrame, columns: list[str], key: str):
    if sub.empty:
        st.success("No subnets in this case.")
        return

    summary = sub["estado"].value_counts().reindex(STATUSES, fill_value=0)
    m1, m2, m3 = st.columns(3)
    m1.metric("Pending", int(summary["Pending"]))
    m2.metric("Requested", int(summary["Requested"]))
    m3.metric("Resolved", int(summary["Resolved"]))

    status_filter = st.multiselect("Filter by status", STATUSES, default=STATUSES, key=f"filter_{key}")
    view = sub[sub["estado"].isin(status_filter)].copy()
    view = view.rename(columns={"estado": "Status", "nota": "Notes"})
    editable = view[["subnet"] + columns + ["Status", "Notes"]]

    edited = st.data_editor(
        editable,
        key=key,
        column_config={
            "Status": st.column_config.SelectboxColumn("Status", options=STATUSES, required=True),
            "subnet": st.column_config.TextColumn("Subnet", disabled=True),
        },
        disabled=["subnet"] + columns,
        hide_index=True,
        use_container_width=True,
    )

    if st.button("Save changes", key=f"save_{key}", type="primary"):
        save_status(edited)
        st.success(f"Saved ({len(edited)} rows).")


tab1, tab2 = st.tabs(
    [f"Case 1 - FREE but IN USE ({len(case1_df)})", f"Case 2 - FREE but REFERENCED ({len(case2_df)})"]
)

with tab1:
    status_table(
        case1_df,
        columns=["subnet_name", "site_name", "interfaces", "routes", "dns"],
        key="case1",
    )

with tab2:
    status_table(
        case2_df,
        columns=["subnet_name", "site_name", "fmc_objects", "fmc_rules", "configs"],
        key="case2",
    )
