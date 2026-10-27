import csv
import io
import re
from collections.abc import Iterable

FREE_SUFFIX_RE = re.compile(
    r"\s*(?:[\(\[]\s*(?:x{2,4}|[\d.]+)?\s*FREE\s*[\)\]]|[\s-]+FREE)\s*$",
    re.IGNORECASE,
)
FIELDS = [
    "subnet",
    "current_name",
    "proposed_name",
    "site_id",
    "site_source",
    "action",
    "interfaces",
    "routes",
    "dns",
    "status",
    "notes",
]


def proposed_name(current_name: str) -> str:
    return FREE_SUFFIX_RE.sub("", current_name).strip()


def build_row(record: dict) -> dict:
    name = record.get("subnet_name", "")
    site = record.get("site", "")
    suggested = record.get("suggested_site", "")
    if site:
        site_id, source, action = site, "1DDI name", "Rename in 1DDI (remove FREE)"
    elif suggested:
        confidence = record.get("confidence", "")
        site_id = suggested
        source = f"Site ID API ({confidence})" if confidence else "Site ID API"
        action = "Confirm suggested Site ID with site owner, then rename"
    else:
        site_id, source, action = "", "", "Investigate site (hostname/routes/DNS)"
    return {
        "subnet": record.get("subnet", ""),
        "current_name": name,
        "proposed_name": proposed_name(name) if site else "",
        "site_id": site_id,
        "site_source": source,
        "action": action,
        "interfaces": record.get("interfaces", ""),
        "routes": record.get("routes", ""),
        "dns": record.get("dns", ""),
        "status": record.get("status", "Pending"),
        "notes": record.get("notes", ""),
    }


def build_rename_requests_csv(records: Iterable[dict]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDS)
    writer.writeheader()
    for record in records:
        if record.get("status") != "Resolved":
            writer.writerow(build_row(record))
    # BOM so Excel opens the UTF-8 file correctly.
    return output.getvalue().encode("utf-8-sig")
