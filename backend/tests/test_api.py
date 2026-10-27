import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import main
from app.services import status_store


CSV = (
    "subnet,verdict,subnet_name,site_name,interfaces\n"
    "10.0.0.0/24,FREE but IN USE,US-609 FREE,PGN,2\n"
    "10.0.1.0/24,FREE but REFERENCED,EMEA-FREE,Cloud,0\n"
).encode()


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        status_store.DB_PATH = Path(self.temp_dir.name) / "state.db"
        self.client = TestClient(main.app)

    def tearDown(self):
        self.temp_dir.cleanup()

    def upload(self):
        return self.client.post(
            "/api/reconciliation",
            files={"file": ("report.csv", CSV, "text/csv")},
        )

    def test_reconciliation_upload_and_status_persist_across_reports(self):
        first = self.upload()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["summary"]["total"], 2)

        updated = self.client.put(
            "/api/status",
            json={"subnet": "10.0.0.0/24", "status": "Requested", "notes": "CHG123"},
        )
        self.assertEqual(updated.status_code, 200)

        second = self.upload()
        row = second.json()["cases"]["case1"][0]
        self.assertEqual(row["status"], "Requested")
        self.assertEqual(row["notes"], "CHG123")

    def test_invalid_subnet_is_rejected_before_site_service_call(self):
        with patch("app.main._lookup_site") as lookup:
            response = self.client.get("/api/site-id", params={"subnet": "not-a-subnet"})
        self.assertEqual(response.status_code, 400)
        lookup.assert_not_called()

    def test_site_lookup_uses_and_caches_python_service_result(self):
        result = {
            "subnet": "10.0.0.0/24",
            "suggested_site_id": "US-609",
            "confidence": "high",
            "candidates": {"US-609": 3},
            "evidence": ["Interfaces: device-1"],
        }
        with patch("app.main.site_id_client.lookup_site", new=AsyncMock(return_value=result)):
            response = self.client.get("/api/site-id", params={"subnet": "10.0.0.0/24"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["suggested_site_id"], "US-609")
        cached = status_store.get_suggestions(["10.0.0.0/24"])
        self.assertEqual(cached[0]["suggested_site"], "US-609")

    def test_fmc_call_requires_backend_key(self):
        with patch.dict(os.environ, {"SSOT_API_KEY": ""}):
            response = self.client.post("/api/fmc/analyze", json={"subnets": ["10.0.0.0/24"]})
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
