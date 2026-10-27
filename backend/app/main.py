import asyncio
import ipaddress
from typing import Literal

import httpx
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.config import config
from app.services import site_id_client, ssot_client, status_store
from app.services.reconciliation import merge_persisted_data, parse_reconciliation_csv
from app.services.rename_requests import build_rename_requests_csv

Status = Literal["Pending", "Requested", "Resolved"]
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in config("FRONTEND_ORIGINS", default="http://localhost:3000").split(",")
    if origin.strip()
]

app = FastAPI(title="Subnet Cleanse API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type"],
    expose_headers=["Content-Disposition"],
)


class StatusUpdate(BaseModel):
    subnet: str = Field(min_length=1, max_length=64)
    status: Status
    notes: str = Field(default="", max_length=2000)


class SiteIdBatch(BaseModel):
    subnets: list[str] = Field(min_length=1, max_length=100)


class FmcRequest(BaseModel):
    subnets: list[str] = Field(min_length=1, max_length=200)


class Case1Row(BaseModel):
    subnet: str = Field(min_length=1, max_length=64)
    subnet_name: str = Field(default="", max_length=500)
    site: str = Field(default="", max_length=64)
    suggested_site: str = Field(default="", max_length=64)
    confidence: str = Field(default="", max_length=64)
    interfaces: str = Field(default="", max_length=64)
    routes: str = Field(default="", max_length=64)
    dns: str = Field(default="", max_length=64)
    status: Status = "Pending"
    notes: str = Field(default="", max_length=2000)


class RenameRequestExport(BaseModel):
    rows: list[Case1Row] = Field(min_length=1, max_length=5000)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/reconciliation")
async def reconciliation(file: UploadFile = File(...)) -> dict:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(415, "Upload a reconciliation CSV file.")
    content = await file.read()
    if not content:
        raise HTTPException(422, "The uploaded CSV is empty.")
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(413, "The CSV exceeds the 25 MB upload limit.")
    cases = parse_reconciliation_csv(content)
    cases = merge_persisted_data(cases, status_store.get_statuses(), status_store.get_suggestions())
    return {
        "cases": cases,
        "summary": {
            "case1": len(cases["case1"]),
            "case2": len(cases["case2"]),
            "total": len(cases["case1"]) + len(cases["case2"]),
            "resolved": sum(
                row["status"] == "Resolved"
                for rows in cases.values()
                for row in rows
            ),
            "pending": sum(
                row["status"] == "Pending"
                for rows in cases.values()
                for row in rows
            ),
        },
    }


@app.put("/api/status")
def update_status(update: StatusUpdate) -> dict:
    status_store.save_status(update.subnet, update.status, update.notes)
    return {"subnet": update.subnet, "status": update.status, "notes": update.notes}


async def _lookup_site(subnet: str) -> dict:
    try:
        result = await site_id_client.lookup_site(subnet)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, "The Site ID service returned an error.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(503, "The Site ID service is unavailable.") from exc
    status_store.save_suggestion(result)
    return result


@app.get("/api/site-id")
async def lookup_site_id(subnet: str = Query(min_length=1, max_length=64)) -> dict:
    try:
        ipaddress.IPv4Network(subnet if "/" in subnet else f"{subnet}/32", strict=False)
    except ValueError as exc:
        raise HTTPException(400, f"Invalid IPv4 subnet: {subnet}") from exc
    return await _lookup_site(subnet)


@app.post("/api/site-id/batch")
async def lookup_site_ids(request: SiteIdBatch) -> dict:
    unique_subnets = list(dict.fromkeys(request.subnets))
    for subnet in unique_subnets:
        try:
            ipaddress.IPv4Network(subnet if "/" in subnet else f"{subnet}/32", strict=False)
        except ValueError as exc:
            raise HTTPException(400, f"Invalid IPv4 subnet: {subnet}") from exc

    semaphore = asyncio.Semaphore(4)

    async def lookup(subnet: str) -> dict:
        async with semaphore:
            try:
                return await _lookup_site(subnet)
            except HTTPException as exc:
                return {"subnet": subnet, "error": exc.detail}

    results = await asyncio.gather(*(lookup(subnet) for subnet in unique_subnets))
    return {"results": results}


@app.post("/api/case1/rename-requests")
def case1_rename_requests(request: RenameRequestExport) -> Response:
    content = build_rename_requests_csv(row.model_dump() for row in request.rows)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="rename_requests.csv"'},
    )


@app.post("/api/fmc/analyze")
async def fmc_analyze(request: FmcRequest) -> dict:
    return await ssot_client.analyze(list(dict.fromkeys(request.subnets)))


@app.post("/api/fmc/workbooks")
async def fmc_workbooks(request: FmcRequest) -> Response:
    batch_id, content = await ssot_client.workbooks(list(dict.fromkeys(request.subnets)))
    try:
        ssot_client.save_workbook_copy(batch_id, content)
    except OSError as exc:
        raise HTTPException(500, f"Workbooks were generated but the local copy could not be saved: {exc}") from exc
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="fmc_workbooks_{batch_id}.zip"'},
    )
