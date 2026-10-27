# Subnet Cleanse

Web application for tracking subnet discrepancies found in SSOT's
`ddi_reconciliation` report. The target architecture separates the UI from
Python business services:

- **Frontend:** Next.js + React + TypeScript. It renders reconciliation data
  and calls the REST API; it does not classify subnets, store credentials, or
  call SSOT directly.
- **Backend:** Python + FastAPI. It parses and classifies the CSV, persists
  statuses and Site ID suggestions in SQLite, and brokers Site ID/FMC API
  requests.
- **SSOT:** used read-only. Changes to 1DDI and firewalls continue through the
  owning teams' normal change process.

## Features

- **Case 1 — FREE but IN USE:** view the subnet and evidence; request a Site ID
  suggestion for generic pools using the existing Site ID service; export the
  1DDI rename list (`rename_requests.csv`) with the proposed name and action
  for each subnet (rename, confirm suggested site, or investigate).
- **Case 2 — FREE but REFERENCED:** select subnets, analyze FMC rules, and
  download the generated workbook ZIP.
- **Monthly tracking:** set a subnet to Pending, Requested, or Resolved and
  add a note/ticket reference. The backend persists the state in the existing
  `estado_subnets.db`, keyed by subnet, so it remains when a new CSV is loaded.
- **Site ID lookup:** request a suggestion for any IPv4 subnet.

## Run locally

### Quick start (one command)

From the repository root in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

The script starts the Site ID service (WSL, port `8800`), the FastAPI backend
(port `8000`) and the Next.js frontend (port `3000`), then opens the browser.
It creates the backend virtual environment and installs frontend packages the
first time. Press **Ctrl+C** to stop everything. Logs are written to `logs\`.
All services listen on `127.0.0.1` only.

The sections below describe how to start each service manually.

### 1. Start the FastAPI backend

From the repository root in PowerShell:

```powershell
py -m venv backend\.venv
backend\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
Copy-Item backend\.env.example backend\.env   # first time only; then fill in SSOT_API_KEY
uvicorn app.main:app --app-dir backend --reload --port 8000
```

Configuration is read from `backend\.env` (python-decouple); environment
variables set in the terminal take precedence. `backend\.env` is ignored by
git.

The existing Site ID service must also be running in WSL on port `8800` (see
`..\api\start_api.sh`). To use the SSOT service's trusted certificate, set
`SSOT_CA_BUNDLE` to the certificate bundle path available to the backend.
The backend verifies TLS by default; API keys are kept on the backend and are
never sent to the browser. Do not commit credentials or certificate files.

SQLite defaults to `estado_subnets.db` in the repository root, reusing the
existing status and suggestion tables. Set `SUBNET_CLEANSE_DB` to use another
database file. Set `FRONTEND_ORIGINS` to a comma-separated list when the
frontend is not running on `http://localhost:3000`.

### 2. Start the Next.js frontend

In a second terminal:

```powershell
cd frontend
npm install
$env:NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000"
npm run dev
```

Open `http://localhost:3000` and upload the daily reconciliation CSV. The
backend accepts UTF-8 CSV files up to 25 MB.

## API routes

| Route | Purpose |
|---|---|
| `GET /api/health` | Backend health check |
| `POST /api/reconciliation` | Upload, filter, and enrich the reconciliation CSV |
| `PUT /api/status` | Persist a subnet's status and note |
| `GET /api/site-id?subnet=...` | Look up one Site ID |
| `POST /api/site-id/batch` | Look up Site IDs for generic pools |
| `POST /api/case1/rename-requests` | Download the Case 1 1DDI rename list (CSV) |
| `POST /api/fmc/analyze` | Analyze firewall rules through SSOT |
| `POST /api/fmc/workbooks` | Generate and download FMC workbooks through SSOT |

Interactive API documentation is available at `http://localhost:8000/docs`.

Run the backend tests from the repository root:

```powershell
Set-Location backend
python -m unittest discover -s tests -v
```

## Repository layout

```text
backend/
  app/main.py                FastAPI routes and request validation
  app/services/              CSV, SQLite, Site ID, and SSOT integrations
  tests/                     Backend service tests
frontend/
  app/                       Next.js user interface
```
