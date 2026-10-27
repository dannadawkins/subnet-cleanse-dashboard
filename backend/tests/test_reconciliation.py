import unittest

from fastapi import HTTPException

from app.services.reconciliation import merge_persisted_data, parse_reconciliation_csv


class ReconciliationTests(unittest.TestCase):
    def test_parses_only_tracked_cases_and_extracts_site(self):
        content = (
            "subnet,verdict,subnet_name,site_name,interfaces\n"
            "10.0.0.0/24,FREE but IN USE,US-609 FREE,PGN,2\n"
            "10.0.1.0/24,FREE but REFERENCED,EMEA-FREE,Cloud,0\n"
            "10.0.2.0/24,IN USE,NL-004,PGN,1\n"
        ).encode()

        result = parse_reconciliation_csv(content)

        self.assertEqual(len(result["case1"]), 1)
        self.assertEqual(result["case1"][0]["site"], "US-609")
        self.assertEqual(result["case1"][0]["network_type"], "PGN")
        self.assertEqual(result["case2"][0]["site"], "")

    def test_reuses_status_and_site_suggestion_by_subnet(self):
        cases = {"case1": [{"subnet": "10.0.0.0/24", "status": "Pending", "notes": ""}], "case2": []}

        result = merge_persisted_data(
            cases,
            [{"subnet": "10.0.0.0/24", "estado": "Requested", "nota": "Ticket 123"}],
            [{
                "subnet": "10.0.0.0/24",
                "suggested_site": "US-609",
                "confidence": "high",
                "candidates": "US-609 (3)",
                "evidence": "Interfaces: device-1",
            }],
        )

        row = result["case1"][0]
        self.assertEqual(row["status"], "Requested")
        self.assertEqual(row["notes"], "Ticket 123")
        self.assertEqual(row["suggested_site"], "US-609")

    def test_rejects_csv_missing_required_columns(self):
        with self.assertRaises(HTTPException) as error:
            parse_reconciliation_csv(b"address,result\n10.0.0.1,FREE\n")
        self.assertEqual(error.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
