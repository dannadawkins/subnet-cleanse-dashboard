"""
Legacy Streamlit Dashboard (replaced by the Next.js + FastAPI application)
====================================================================

WHAT IT DOES:
  Reads the CSV produced by SSOT's reconciliation report
  (ddi_reconciliation_<date>.csv) and shows two tabs:
    - Case 1: FREE but IN USE
    - Case 2: FREE but REFERENCED
  Each row has a "Status" column (Pending / Requested / Resolved) that you
  edit by hand. It is saved locally (estado_subnets.db) so it is not lost
  when you upload a new CSV next month.

  Case 1 subnets whose name has no site (generic EMEA/AMEC/APAC/TPG-FREE
  pools) get a suggested Site ID from the Site ID API (../api/site_id_api.py,
  runs in WSL). Suggestions are cached in estado_subnets.db. The
  "Site ID lookup" tab queries any subnet on demand.

  Case 2 tab: "FMC decommission" section calls the SSOT firewall
  decommission API (SSOT_HOST, key in SSOT_API_KEY) to analyze the rules to
  delete/modify and download the FMC Excel workbooks (ZIP, one per firewall).
  A copy of each ZIP is saved in ../data/fmc_workbooks/.

REQUIREMENTS (once, on your laptop):
  pip install -r requirements.txt

HOW TO GET THE CSV:
  SSOT prod generates the report every day. Copy it from WSL:
  scp ssot-prod:/dn/ssot/reports/ddi_reconciliation/ddi_reconciliation_<date>.csv \
      /mnt/c/Users/320319586/Proyectos/Subnet-Cleanse/data/

HOW TO RUN THE DASHBOARD (on your laptop, in this folder):
  1. Start the Site ID API in WSL (see ../api/site_id_api.py):
       cd /opt/dn/ssot
       venv/bin/uvicorn --app-dir /mnt/c/Users/320319586/Proyectos/Subnet-Cleanse/api \
           site_id_api:app --host 127.0.0.1 --port 8800
  2. In PowerShell:
       streamlit run subnet_cleanse_dashboard.py

  Opens automatically in your browser (http://localhost:8501). Upload the
  CSV from the sidebar.
"""

import json
import os
import re
import sqlite3
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DB_PATH = Path(__file__).parent / "estado_subnets.db"
API_URL = os.environ.get("SITE_ID_API", "http://localhost:8800")
API_START_CMD = (
    "cd /opt/dn/ssot && venv/bin/uvicorn --app-dir "
    "/mnt/c/Users/320319586/Proyectos/Subnet-Cleanse/api site_id_api:app --host 127.0.0.1 --port 8800"
)
SSOT_HOST = os.environ.get("SSOT_HOST", "https://ssot.dn.pgn.philips.com:8555")
SSOT_TIMEOUT = 600
WORKBOOK_DIR = Path(__file__).parent.parent / "data" / "fmc_workbooks"
STATUSES = ["Pending", "Requested", "Resolved"]
# Site code in the subnet name, e.g. "US-609 Pleasanton", "NL-004 FREE", "US-T123".
# Generic pools (EMEA-FREE, AMEC-FREE, APAC-FREE, TPG-FREE) have no site.
SITE_RE = re.compile(r"\b([A-Z]{2}-[A-Z]?\d{2,4})\b", re.IGNORECASE)

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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS site_suggestions (
            subnet TEXT PRIMARY KEY,
            suggested_site TEXT,
            confidence TEXT,
            candidates TEXT,
            evidence TEXT,
            checked_at TEXT
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
# Site ID API (runs in WSL) + local cache of its suggestions
# ---------------------------------------------------------------------------
def api_online() -> bool:
    try:
        return requests.get(f"{API_URL}/health", timeout=3).ok
    except requests.RequestException:
        return False


def query_site_id(subnet: str) -> dict:
    r = requests.get(f"{API_URL}/site-id", params={"subnet": subnet}, timeout=300)
    r.raise_for_status()
    return r.json()


def load_suggestions() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql("SELECT subnet, suggested_site, confidence, candidates, evidence FROM site_suggestions", conn)
    conn.close()
    return df


def save_suggestion(res: dict):
    candidates = ", ".join(f"{k} ({v:g})" for k, v in res.get("candidates", {}).items())
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO site_suggestions (subnet, suggested_site, confidence, candidates, evidence, checked_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(subnet) DO UPDATE SET
            suggested_site=excluded.suggested_site,
            confidence=excluded.confidence,
            candidates=excluded.candidates,
            evidence=excluded.evidence,
            checked_at=excluded.checked_at
        """,
        (res["subnet"], res.get("suggested_site_id") or "", res.get("confidence", ""),
         candidates, "; ".join(res.get("evidence", []))),
    )
    conn.commit()
    conn.close()


def clear_suggestions(subnets: list[str]):
    conn = get_conn()
    conn.executemany("DELETE FROM site_suggestions WHERE subnet = ?", [(s,) for s in subnets])
    conn.commit()
    conn.close()


def fetch_missing_suggestions(subnets: list[str]):
    """Ask the API for every subnet that has no cached suggestion yet."""
    cached = set(load_suggestions()["subnet"])
    missing = [s for s in subnets if s not in cached]
    if not missing:
        return
    if not api_online():
        st.warning(
            f"Site ID API is not running, so {len(missing)} Case 1 subnet(s) without site have no suggestion yet. "
            f"Start it in WSL and reload:\n\n`{API_START_CMD}`"
        )
        return
    bar = st.progress(0.0, text=f"Looking up Site IDs (0/{len(missing)})...")
    for i, subnet in enumerate(missing, 1):
        try:
            save_suggestion(query_site_id(subnet))
        except requests.RequestException as e:
            st.error(f"{subnet}: {e}")
        bar.progress(i / len(missing), text=f"Looking up Site IDs ({i}/{len(missing)})...")
    bar.empty()


# ---------------------------------------------------------------------------
# SSOT firewall decommission API (Case 2): analyze rules + FMC Excel workbooks
# ---------------------------------------------------------------------------
def ssot_session(api_key: str) -> requests.Session:
    s = requests.Session()
    s.headers["X-API-Key"] = api_key
    s.verify = False  # SSOT uses a self-signed certificate
    return s


def decommission_analyze(api_key: str, subnets: list[str]) -> dict:
    r = ssot_session(api_key).get(
        f"{SSOT_HOST}/api/v1/firewall/decommission/analyze",
        params={"subnets": ",".join(subnets)},
        timeout=SSOT_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def decommission_workbooks(api_key: str, subnets: list[str]) -> tuple[str, bytes]:
    s = ssot_session(api_key)
    r = s.post(
        f"{SSOT_HOST}/api/v1/firewall/decommission/workbooks",
        params={"subnets": ",".join(subnets)},
        timeout=SSOT_TIMEOUT,
    )
    r.raise_for_status()
    batch_id = r.json()["batch"]["batch_id"]
    r = s.get(f"{SSOT_HOST}/api/v1/firewall/decommission/batches/{batch_id}/bundle.zip", timeout=SSOT_TIMEOUT)
    r.raise_for_status()
    return batch_id, r.content


def api_error(e: requests.RequestException) -> str:
    resp = getattr(e, "response", None)
    if resp is not None and resp.status_code in (401, 403):
        return "SSOT rejected the API key (check SSOT_API_KEY)."
    detail = resp.text[:300] if resp is not None else str(e)
    return f"SSOT API error: {detail}"


def decommission_section(case2_subnets: pd.DataFrame, api_key: str):
    st.subheader("FMC decommission (Excel for the firewall team)")
    if not api_key:
        st.info("Set your SSOT API key in the sidebar (or the SSOT_API_KEY environment variable) to use this.")
        return

    pending = case2_subnets.loc[case2_subnets["estado"] == "Pending", "subnet"].tolist()
    all_pending = st.checkbox(f"Use all Pending subnets ({len(pending)})", key="dec_all")
    selected = pending if all_pending else st.multiselect(
        "Subnets", case2_subnets["subnet"].tolist(), key="dec_subnets",
        help="Pick the subnets to analyze / generate workbooks for",
    )
    if not selected:
        return

    a, b = st.columns(2)
    if a.button(f"Analyze rules ({len(selected)})", key="dec_analyze"):
        with st.spinner("Analyzing firewall rules in SSOT..."):
            try:
                st.session_state["dec_result"] = (selected, decommission_analyze(api_key, selected))
            except requests.RequestException as e:
                st.error(api_error(e))
    if b.button(f"Generate FMC workbooks ({len(selected)})", key="dec_workbooks", type="primary"):
        with st.spinner("Generating Excel workbooks (one per firewall)..."):
            try:
                batch_id, content = decommission_workbooks(api_key, selected)
                WORKBOOK_DIR.mkdir(exist_ok=True)
                (WORKBOOK_DIR / f"fmc_workbooks_{batch_id}.zip").write_bytes(content)
                st.session_state["dec_zip"] = (batch_id, content)
            except requests.RequestException as e:
                st.error(api_error(e))

    if "dec_result" in st.session_state:
        subnets_done, data = st.session_state["dec_result"]
        st.caption(f"Analysis for: {', '.join(subnets_done)}")
        summary = data.get("summary")
        if isinstance(summary, dict):
            cols = st.columns(min(len(summary), 5) or 1)
            for i, (k, v) in enumerate(summary.items()):
                if isinstance(v, (int, float, str)):
                    cols[i % len(cols)].metric(k.replace("_", " ").capitalize(), v)
        elif summary:
            st.write(summary)
        plan = data.get("plan", {})
        for label, key in (("Rules to DELETE", "remove_rules"), ("Rules to MODIFY", "modify_rules")):
            rules = plan.get(key, [])
            st.markdown(f"**{label}: {len(rules)}**")
            if rules:
                st.dataframe(pd.json_normalize(rules), hide_index=True, use_container_width=True)

    if "dec_zip" in st.session_state:
        batch_id, content = st.session_state["dec_zip"]
        st.success(f"Workbooks ready (batch {batch_id}). Copy saved in {WORKBOOK_DIR}.")
        st.download_button("Download ZIP", content, file_name=f"fmc_workbooks_{batch_id}.zip",
                           mime="application/zip", key="dec_download")


# ---------------------------------------------------------------------------
# Sidebar: file upload
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Data")
    uploaded_file = st.file_uploader("Reconciliation CSV", type=["csv"])
    st.caption("Daily report from ssot-prod: `/dn/ssot/reports/ddi_reconciliation/ddi_reconciliation_<date>.csv`")
    ssot_api_key = os.environ.get("SSOT_API_KEY", "")
    if not ssot_api_key:
        ssot_api_key = st.text_input("SSOT API key", type="password",
                                     help="For FMC workbooks (Case 2). Not saved to disk.")

st.title("Subnet Cleanse Dashboard")

if uploaded_file is None:
    st.info("Upload a CSV from the left sidebar to view the dashboard.")
    st.stop()

df = pd.read_csv(uploaded_file)
# The report's "site_name" column actually holds the network type (PGN, Cloud, ...).
df = df.rename(columns={"site_name": "network_type"})
df["site"] = df["subnet_name"].fillna("").str.extract(SITE_RE, expand=False).str.upper().fillna("")
saved_status = load_status()

df = df.merge(saved_status[["subnet", "estado", "nota"]], on="subnet", how="left")
df["estado"] = df["estado"].fillna("Pending")
df["nota"] = df["nota"].fillna("")

case1_df = df[df["verdict"] == "FREE but IN USE"]
case2_df = df[df["verdict"] == "FREE but REFERENCED"]

# Case 1B: no site in the name -> suggest one from the Site ID API.
case1_no_site = case1_df.loc[case1_df["site"] == "", "subnet"].tolist()
fetch_missing_suggestions(case1_no_site)
suggestions = load_suggestions()
suggestions = suggestions[suggestions["subnet"].isin(case1_no_site)]
case1_df = case1_df.merge(suggestions, on="subnet", how="left")
for col in ["suggested_site", "confidence", "candidates", "evidence"]:
    case1_df[col] = case1_df[col].fillna("")

tracked = pd.concat([case1_df, case2_df])
total = len(tracked)
resolved = (tracked["estado"] == "Resolved").sum()
pending = (tracked["estado"] == "Pending").sum()

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
            "site": st.column_config.TextColumn("Site", help="Empty = generic FREE pool, site must be investigated"),
            "network_type": st.column_config.TextColumn("Network type"),
            "suggested_site": st.column_config.TextColumn("Suggested site", help="From the Site ID API (Case 1B only)"),
            "confidence": st.column_config.TextColumn("Confidence", help="high / medium / low - review low ones by hand"),
            "candidates": st.column_config.TextColumn("All candidates (score)"),
            "evidence": st.column_config.TextColumn("Evidence"),
        },
        disabled=["subnet"] + columns,
        hide_index=True,
        use_container_width=True,
    )

    if st.button("Save changes", key=f"save_{key}", type="primary"):
        save_status(edited)
        st.success(f"Saved ({len(edited)} rows).")


tab1, tab2, tab3 = st.tabs(
    [
        f"Case 1 - FREE but IN USE ({len(case1_df)})",
        f"Case 2 - FREE but REFERENCED ({len(case2_df)})",
        "Site ID lookup",
    ]
)

with tab1:
    status_table(
        case1_df,
        columns=["site", "suggested_site", "confidence", "subnet_name", "network_type",
                 "interfaces", "routes", "dns", "candidates", "evidence"],
        key="case1",
    )
    if case1_no_site and st.button("Re-check suggested Site IDs", key="recheck"):
        clear_suggestions(case1_no_site)
        st.rerun()

with tab2:
    status_table(
        case2_df,
        columns=["site", "subnet_name", "network_type", "fmc_objects", "fmc_rules", "configs"],
        key="case2",
    )
    if not case2_df.empty:
        st.divider()
        decommission_section(case2_df, ssot_api_key)

with tab3:
    st.write("Look up the Site ID of any subnet (uses the Site ID API in WSL).")
    with st.form("lookup"):
        lookup_subnet = st.text_input("Subnet (CIDR)", placeholder="10.140.64.0/20")
        submitted = st.form_submit_button("Find Site ID", type="primary")
    if submitted and lookup_subnet.strip():
        if not api_online():
            st.error(f"Site ID API is not running. Start it in WSL:\n\n`{API_START_CMD}`")
        else:
            with st.spinner("Searching SSOT data..."):
                try:
                    res = query_site_id(lookup_subnet.strip())
                except requests.RequestException as e:
                    res = None
                    st.error(str(e))
            if res:
                r1, r2, r3 = st.columns(3)
                r1.metric("Suggested site", res.get("suggested_site_id") or "-")
                r2.metric("Confidence", res.get("confidence", "-"))
                r3.metric("SSOT verdict", res.get("verdict") or "-")
                st.write(f"**1DDI name:** {res.get('ddi_name') or '(not in 1DDI)'}")
                if res.get("candidates"):
                    st.write("**All candidates (score):**")
                    st.dataframe(
                        pd.DataFrame(list(res["candidates"].items()), columns=["Site", "Score"]),
                        hide_index=True,
                    )
                if res.get("evidence"):
                    st.write("**Evidence for the suggested site:**")
                    for e in res["evidence"]:
                        st.write(f"- {e}")
                if not res.get("candidates"):
                    st.info("No site code found in the SSOT evidence for this subnet.")
