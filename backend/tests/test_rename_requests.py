import unittest

from fastapi.testclient import TestClient

from app import main
from app.services.rename_requests import build_rename_requests_csv, proposed_name


class RenameRequestTests(unittest.TestCase):
    def test_action_depends_on_known_or_suggested_site(self):
        content = build_rename_requests_csv([
            {"subnet": "10.0.0.0/24", "subnet_name": "US-179 Bothell VLAN (8.128 Free)", "site": "US-179"},
            {"subnet": "10.0.1.0/24", "subnet_name": "EMEA-FREE", "suggested_site": "NL-004", "confidence": "high"},
            {"subnet": "10.0.2.0/24", "subnet_name": "APAC FREE"},
            {"subnet": "10.0.3.0/24", "subnet_name": "US-1 (FREE)", "site": "US-1", "status": "Resolved"},
        ]).decode("utf-8-sig")

        lines = content.splitlines()
        self.assertEqual(len(lines), 4)  # header + 3; resolved row is skipped
        self.assertIn("US-179 Bothell VLAN,US-179,1DDI name,Rename in 1DDI", lines[1])
        self.assertIn("EMEA-FREE,,NL-004,Site ID API (high),", lines[2])
        self.assertIn("Confirm suggested Site ID", lines[2])
        self.assertIn(",,,Investigate site", lines[3])

    def test_proposed_name_removes_free_suffix_variants(self):
        self.assertEqual(proposed_name("US-179 Bothell VLAN xxxx (47.64 Free)"), "US-179 Bothell VLAN xxxx")
        self.assertEqual(proposed_name("US-625 Nashville SDLAN (44.0 FREE)"), "US-625 Nashville SDLAN")
        self.assertEqual(proposed_name("US-609 FREE"), "US-609")
        self.assertEqual(proposed_name("US-609 Office"), "US-609 Office")

    def test_endpoint_returns_csv_download(self):
        response = TestClient(main.app).post(
            "/api/case1/rename-requests",
            json={"rows": [{"subnet": "10.0.0.0/24", "subnet_name": "US-609 FREE", "site": "US-609", "extra": "x"}]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("rename_requests.csv", response.headers["content-disposition"])
        self.assertIn("10.0.0.0/24,US-609 FREE,US-609,US-609", response.content.decode("utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
