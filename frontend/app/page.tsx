"use client";

import { ChangeEvent, FormEvent, useMemo, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const STATUSES = ["Pending", "Requested", "Resolved"] as const;
type Status = (typeof STATUSES)[number];
type RecordRow = Record<string, string> & { subnet: string; status: Status; notes: string };
type CasesResponse = {
  cases: { case1: RecordRow[]; case2: RecordRow[] };
  summary: { total: number; case1: number; case2: number; resolved: number; pending: number };
};
type SiteResult = {
  subnet: string;
  suggested_site_id?: string | null;
  confidence?: string;
  evidence?: string[];
  candidates?: Record<string, number>;
  verdict?: string;
  ddi_name?: string;
  error?: string;
};

const CASE_COLUMNS: Record<"case1" | "case2", string[]> = {
  case1: ["site", "suggested_site", "confidence", "subnet_name", "network_type", "interfaces", "routes", "dns", "candidates", "evidence"],
  case2: ["site", "subnet_name", "network_type", "fmc_objects", "fmc_rules", "configs"],
};
const LABELS: Record<string, string> = {
  subnet_name: "Subnet name",
  network_type: "Network type",
  fmc_objects: "FMC objects",
  fmc_rules: "FMC rules",
  suggested_site: "Suggested site",
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function display(value: string | undefined) {
  return value?.trim() || "—";
}

export default function Home() {
  const [data, setData] = useState<CasesResponse | null>(null);
  const [activeCase, setActiveCase] = useState<"case1" | "case2">("case1");
  const [statusFilter, setStatusFilter] = useState("All");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [analysis, setAnalysis] = useState<Record<string, unknown> | null>(null);
  const [lookupSubnet, setLookupSubnet] = useState("");
  const [lookup, setLookup] = useState<SiteResult | null>(null);

  const rows = data?.cases[activeCase] ?? [];
  const filteredRows = useMemo(
    () => statusFilter === "All" ? rows : rows.filter((row) => row.status === statusFilter),
    [rows, statusFilter],
  );
  const noSiteSubnets = (data?.cases.case1 ?? []).filter((row) => !row.site).map((row) => row.subnet);

  async function uploadCsv(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setError("");
    setBusy("Loading reconciliation report…");
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await api<CasesResponse>("/api/reconciliation", { method: "POST", body: form });
      setData(result);
      setSelected([]);
      setAnalysis(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load the CSV.");
    } finally {
      setBusy("");
    }
  }

  async function saveRow(row: RecordRow, event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    try {
      await api("/api/status", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subnet: row.subnet, status: row.status, notes: row.notes }),
      });
      setData((current) => {
        if (!current) return current;
        const updated = { ...current, cases: { ...current.cases } };
        for (const key of ["case1", "case2"] as const) {
          updated.cases[key] = updated.cases[key].map((item) => item.subnet === row.subnet ? { ...item, status: row.status, notes: row.notes } : item);
        }
        const all = [...updated.cases.case1, ...updated.cases.case2];
        updated.summary = {
          ...updated.summary,
          resolved: all.filter((item) => item.status === "Resolved").length,
          pending: all.filter((item) => item.status === "Pending").length,
        };
        return updated;
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save status.");
    }
  }

  async function suggestSites() {
    setError("");
    setBusy(`Looking up ${noSiteSubnets.length} Site ID(s)…`);
    try {
      const result: { results: SiteResult[] } = { results: [] };
      // The backend accepts at most 100 subnets per batch.
      for (let start = 0; start < noSiteSubnets.length; start += 100) {
        const chunk = await api<{ results: SiteResult[] }>("/api/site-id/batch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ subnets: noSiteSubnets.slice(start, start + 100) }),
        });
        result.results.push(...chunk.results);
      }
      setData((current) => {
        if (!current) return current;
        const bySubnet = new Map(result.results.map((item) => [item.subnet, item]));
        return {
          ...current,
          cases: {
            ...current.cases,
            case1: current.cases.case1.map((row) => {
              const suggestion = bySubnet.get(row.subnet);
              return suggestion && !suggestion.error
                ? {
                    ...row,
                    suggested_site: suggestion.suggested_site_id ?? "",
                    confidence: suggestion.confidence ?? "",
                    candidates: Object.entries(suggestion.candidates ?? {}).map(([site, score]) => `${site} (${score})`).join(", "),
                    evidence: suggestion.evidence?.join("; ") ?? "",
                  }
                : row;
            }),
          },
        };
      });
      const failures = result.results.filter((item) => item.error);
      if (failures.length) setError(`${failures.length} Site ID lookup(s) failed. Check that the Python Site ID service is running.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not look up Site IDs.");
    } finally {
      setBusy("");
    }
  }

  async function findSite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setLookup(null);
    try {
      setLookup(await api<SiteResult>(`/api/site-id?subnet=${encodeURIComponent(lookupSubnet.trim())}`));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not look up the Site ID.");
    }
  }

  async function analyzeFmc() {
    setError("");
    setBusy("Analyzing FMC rules in SSOT…");
    try {
      setAnalysis(await api<Record<string, unknown>>("/api/fmc/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subnets: selected }),
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not analyze FMC rules.");
    } finally {
      setBusy("");
    }
  }

  async function downloadFile(path: string, body: unknown, fallbackName: string) {
    const response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const errorBody = await response.json().catch(() => null);
      throw new Error(errorBody?.detail ?? `Request failed (${response.status})`);
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") ?? "";
    const filename = disposition.match(/filename="([^"]+)"/)?.[1] ?? fallbackName;
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function exportRenameRequests() {
    setError("");
    setBusy("Preparing 1DDI rename list…");
    try {
      await downloadFile("/api/case1/rename-requests", { rows: data?.cases.case1 ?? [] }, "rename_requests.csv");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not export the rename list.");
    } finally {
      setBusy("");
    }
  }

  async function downloadWorkbooks() {
    setError("");
    setBusy("Generating FMC workbooks…");
    try {
      await downloadFile("/api/fmc/workbooks", { subnets: selected }, "fmc_workbooks.zip");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not generate FMC workbooks.");
    } finally {
      setBusy("");
    }
  }

  return (
    <main className="shell">
      <header className="header">
        <div>
          <p className="eyebrow">NETWORK DATA QUALITY</p>
          <h1>Subnet Cleanse</h1>
          <p className="subtitle">Track IPAM discrepancies and coordinate cleanup.</p>
        </div>
        <label className="upload">
          Upload reconciliation CSV
          <input type="file" accept=".csv,text/csv" onChange={uploadCsv} />
        </label>
      </header>

      {error && <div className="alert" role="alert">{error}</div>}
      {busy && <div className="notice" role="status">{busy}</div>}

      {!data ? (
        <section className="empty">
          <h2>Load a reconciliation report</h2>
          <p>Upload the daily SSOT CSV to review subnets marked FREE but in use or still referenced.</p>
        </section>
      ) : (
        <>
          <section className="metrics">
            <Metric label="Total conflicts" value={data.summary.total} />
            <Metric label="FREE but IN USE" value={data.summary.case1} />
            <Metric label="FREE but REFERENCED" value={data.summary.case2} />
            <Metric label="Resolved" value={data.summary.resolved} />
            <Metric label="Pending" value={data.summary.pending} />
          </section>
          <div className="progress-wrap">
            <div className="progress-label"><span>Overall progress</span><strong>{data.summary.total ? Math.round(data.summary.resolved / data.summary.total * 100) : 0}%</strong></div>
            <progress max={data.summary.total || 1} value={data.summary.resolved} />
          </div>

          <div className="tabs" role="tablist">
            <button className={activeCase === "case1" ? "tab active" : "tab"} onClick={() => setActiveCase("case1")}>
              Case 1 · FREE but IN USE <span>{data.summary.case1}</span>
            </button>
            <button className={activeCase === "case2" ? "tab active" : "tab"} onClick={() => setActiveCase("case2")}>
              Case 2 · FREE but REFERENCED <span>{data.summary.case2}</span>
            </button>
            <button className="tab" onClick={() => { setActiveCase("case1"); document.getElementById("site-lookup")?.scrollIntoView({ behavior: "smooth" }); }}>
              Site ID lookup
            </button>
          </div>

          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>{activeCase === "case1" ? "FREE but IN USE" : "FREE but REFERENCED"}</h2>
                <p>{rows.length} subnets in this case</p>
              </div>
              <label className="filter">Status
                <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                  <option>All</option>{STATUSES.map((status) => <option key={status}>{status}</option>)}
                </select>
              </label>
            </div>

            {activeCase === "case1" && rows.length > 0 && (
              <div className="fmc-toolbar">
                {noSiteSubnets.length > 0 && (
                  <button className="secondary-button" disabled={Boolean(busy)} onClick={suggestSites}>
                    Suggest Site IDs for {noSiteSubnets.length} generic pool(s)
                  </button>
                )}
                <button className="primary-button" disabled={Boolean(busy)} onClick={exportRenameRequests}>
                  Export 1DDI rename list (CSV)
                </button>
              </div>
            )}

            {activeCase === "case2" && rows.length > 0 && (
              <div className="fmc-toolbar">
                <span>{selected.length} selected</span>
                <button className="secondary-button" disabled={Boolean(busy)} onClick={() => setSelected(selected.length ? [] : [...new Set(filteredRows.map((row) => row.subnet))])}>{selected.length ? "Clear selection" : "Select visible"}</button>
                <button className="secondary-button" disabled={!selected.length || Boolean(busy)} onClick={analyzeFmc}>Analyze FMC rules</button>
                <button className="primary-button" disabled={!selected.length || Boolean(busy)} onClick={downloadWorkbooks}>Generate Excel workbooks</button>
              </div>
            )}

            <div className="table-scroll">
              <table>
                <thead><tr>
                  {activeCase === "case2" && <th>Select</th>}
                  <th>Subnet</th>
                  {CASE_COLUMNS[activeCase].map((column) => <th key={column}>{LABELS[column] ?? column.replaceAll("_", " ")}</th>)}
                  <th>Status & notes</th>
                </tr></thead>
                <tbody>
                  {filteredRows.map((row, index) => (
                    <tr key={`${row.subnet}-${index}`}>
                      {activeCase === "case2" && <td><input aria-label={`Select ${row.subnet}`} type="checkbox" checked={selected.includes(row.subnet)} onChange={(event) => setSelected((current) => event.target.checked ? [...new Set([...current, row.subnet])] : current.filter((subnet) => subnet !== row.subnet))} /></td>}
                      <td className="cidr">{row.subnet}</td>
                      {CASE_COLUMNS[activeCase].map((column) => <td key={column}>{display(row[column])}</td>)}
                      <td>
                        <form className="status-form" onSubmit={(event) => saveRow(row, event)}>
                          <select aria-label={`Status for ${row.subnet}`} value={row.status} onChange={(event) => {
                            const status = event.target.value as Status;
                            setData((current) => {
                              if (!current) return current;
                              const cases = { ...current.cases };
                              cases[activeCase] = cases[activeCase].map((item) => item.subnet === row.subnet ? { ...item, status } : item);
                              return { ...current, cases };
                            });
                          }}>{STATUSES.map((status) => <option key={status}>{status}</option>)}</select>
                          <input aria-label={`Notes for ${row.subnet}`} placeholder="Notes / ticket" value={row.notes} onChange={(event) => {
                            const notes = event.target.value;
                            setData((current) => {
                              if (!current) return current;
                              const cases = { ...current.cases };
                              cases[activeCase] = cases[activeCase].map((item) => item.subnet === row.subnet ? { ...item, notes } : item);
                              return { ...current, cases };
                            });
                          }} />
                          <button type="submit" className="save-button">Save</button>
                        </form>
                      </td>
                    </tr>
                  ))}
                  {!filteredRows.length && <tr><td className="empty-cell" colSpan={CASE_COLUMNS[activeCase].length + 2}>No subnets match this filter.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>

          {analysis && <section className="panel"><h2>FMC analysis</h2><pre>{JSON.stringify(analysis, null, 2)}</pre></section>}

          <section className="panel lookup-panel" id="site-lookup">
            <h2>Site ID lookup</h2>
            <p>Find a likely owner site using network evidence available to the Python service.</p>
            <form className="lookup-form" onSubmit={findSite}>
              <input value={lookupSubnet} onChange={(event) => setLookupSubnet(event.target.value)} placeholder="10.140.64.0/20" required />
              <button className="primary-button" type="submit">Find Site ID</button>
            </form>
            {lookup && <div className="result">
              {lookup.error ? <p>{lookup.error}</p> : <>
                <p><strong>Suggested site:</strong> {lookup.suggested_site_id || "—"} <span className="badge">{lookup.confidence}</span></p>
                <p><strong>SSOT verdict:</strong> {lookup.verdict || "—"} · <strong>1DDI name:</strong> {lookup.ddi_name || "not in 1DDI"}</p>
                {lookup.candidates && <pre>{JSON.stringify(lookup.candidates, null, 2)}</pre>}
                {lookup.evidence?.map((item) => <p key={item}>{item}</p>)}
              </>}
            </div>}
          </section>
        </>
      )}
    </main>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return <article className="metric"><span>{label}</span><strong>{value.toLocaleString()}</strong></article>;
}
