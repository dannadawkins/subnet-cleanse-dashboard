import csv
import io
import re
from collections.abc import Iterable

from fastapi import HTTPException

SITE_RE = re.compile(r"\b([A-Z]{2}-[A-Z]?\d{2,4})\b", re.IGNORECASE)
TRACKED_VERDICTS = {"FREE but IN USE", "FREE but REFERENCED"}


def parse_reconciliation_csv(content: bytes) -> dict:
    try:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or not {"subnet", "verdict"}.issubset(reader.fieldnames):
            raise HTTPException(422, "CSV must contain 'subnet' and 'verdict' columns.")

        cases = {"case1": [], "case2": []}
        for raw in reader:
            verdict = (raw.get("verdict") or "").strip()
            case = {"FREE but IN USE": "case1", "FREE but REFERENCED": "case2"}.get(verdict)
            if not case:
                continue

            record = {key: (value or "").strip() for key, value in raw.items() if key}
            record["network_type"] = record.pop("site_name", "")
            site_match = SITE_RE.search(record.get("subnet_name", ""))
            record["site"] = site_match.group(1).upper() if site_match else ""
            record["status"] = "Pending"
            record["notes"] = ""
            record.update(
                suggested_site="",
                confidence="",
                candidates="",
                evidence="",
            )
            cases[case].append(record)
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "CSV must be encoded as UTF-8.") from exc

    return cases


def merge_persisted_data(cases: dict, statuses: Iterable[dict], suggestions: Iterable[dict]) -> dict:
    status_by_subnet = {row["subnet"]: row for row in statuses}
    suggestion_by_subnet = {row["subnet"]: row for row in suggestions}

    for records in cases.values():
        for record in records:
            subnet = record["subnet"]
            status = status_by_subnet.get(subnet)
            if status:
                record["status"] = status["estado"] or "Pending"
                record["notes"] = status["nota"] or ""
            suggestion = suggestion_by_subnet.get(subnet)
            if suggestion:
                record.update(
                    suggested_site=suggestion["suggested_site"] or "",
                    confidence=suggestion["confidence"] or "",
                    candidates=suggestion["candidates"] or "",
                    evidence=suggestion["evidence"] or "",
                )
    return cases
