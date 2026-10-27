import re
from pathlib import Path

import httpx
from fastapi import HTTPException

from app.config import config

SSOT_HOST = config("SSOT_HOST", default="https://ssot.dn.pgn.philips.com:8555").rstrip("/")
SSOT_TIMEOUT = config("SSOT_TIMEOUT", default=600.0, cast=float)
SSOT_CA_BUNDLE = config("SSOT_CA_BUNDLE", default="")
TLS_VERIFY: bool | str = str(Path(SSOT_CA_BUNDLE)) if SSOT_CA_BUNDLE else True
WORKBOOK_DIR = Path(
    config("FMC_WORKBOOK_DIR", default="")
    or Path(__file__).resolve().parents[4] / "data" / "fmc_workbooks"
)
BATCH_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def save_workbook_copy(batch_id: str, content: bytes) -> Path:
    WORKBOOK_DIR.mkdir(parents=True, exist_ok=True)
    path = WORKBOOK_DIR / f"fmc_workbooks_{batch_id}.zip"
    path.write_bytes(content)
    return path


def _client() -> httpx.AsyncClient:
    api_key = config("SSOT_API_KEY", default="")
    if not api_key:
        raise HTTPException(503, "Configure SSOT_API_KEY on the backend to use FMC decommission.")
    return httpx.AsyncClient(
        headers={"X-API-Key": api_key},
        timeout=SSOT_TIMEOUT,
        verify=TLS_VERIFY,
    )


async def analyze(subnets: list[str]) -> dict:
    async with _client() as client:
        try:
            response = await client.get(
                f"{SSOT_HOST}/api/v1/firewall/decommission/analyze",
                params={"subnets": ",".join(subnets)},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            _raise_upstream_error(exc)
        except httpx.RequestError as exc:
            raise HTTPException(502, f"Could not reach the SSOT API: {exc}") from exc


async def workbooks(subnets: list[str]) -> tuple[str, bytes]:
    async with _client() as client:
        try:
            response = await client.post(
                f"{SSOT_HOST}/api/v1/firewall/decommission/workbooks",
                params={"subnets": ",".join(subnets)},
            )
            response.raise_for_status()
            batch_id = str(response.json()["batch"]["batch_id"])
            if not BATCH_ID_RE.fullmatch(batch_id):
                raise HTTPException(502, "SSOT returned an invalid workbook batch ID.")
            bundle = await client.get(
                f"{SSOT_HOST}/api/v1/firewall/decommission/batches/{batch_id}/bundle.zip"
            )
            bundle.raise_for_status()
            return batch_id, bundle.content
        except httpx.HTTPStatusError as exc:
            _raise_upstream_error(exc)
        except (httpx.RequestError, KeyError) as exc:
            raise HTTPException(502, f"Could not generate FMC workbooks through SSOT: {exc}") from exc


def _raise_upstream_error(exc: httpx.HTTPStatusError) -> None:
    status_code = exc.response.status_code
    if status_code in (401, 403):
        raise HTTPException(status_code, "SSOT rejected the backend API key.")
    raise HTTPException(502, f"SSOT API returned HTTP {status_code}.")
