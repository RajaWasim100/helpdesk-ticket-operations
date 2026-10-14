import csv
import json
import tempfile
import unittest
from pathlib import Path

from analyze import LABEL, summarize


FIELDS = [
    "id", "issue_num", "issue_type", "issue_priority", "issue_created", "issue_resolution_date",
    "issue_resolution", "issue_status", "issue_comments_count", "issue_contr_count",
    "wf_total_time", "processing_steps", "wf_open", "wf_in_progress",
]


class HelpdeskOperationsTests(unittest.TestCase):
    def write_csv(self, path, fields, rows):
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_aggregates_useful_metrics_and_never_export_ids_or_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "issues.csv"
            self.write_csv(path, FIELDS, [
                {"id": "private-ticket-1", "issue_num": "ticket-number-1", "issue_type": "Incident", "issue_priority": "High", "issue_created": "2022-01-01T10:00:00+00:00", "issue_resolution_date": "2022-01-01T13:00:00+00:00", "issue_resolution": "Done", "issue_status": "done", "issue_comments_count": "3", "issue_contr_count": "2", "wf_total_time": "7200", "processing_steps": "4", "wf_open": "600", "wf_in_progress": "6600"},
                {"id": "private-ticket-2", "issue_num": "ticket-number-2", "issue_type": "Request", "issue_priority": "Low", "issue_created": "2022-01-02T10:00:00+00:00", "issue_resolution_date": "", "issue_resolution": "", "issue_status": "in progress", "issue_comments_count": "1", "issue_contr_count": "1", "wf_total_time": "3600", "processing_steps": "2", "wf_open": "120", "wf_in_progress": "3480"},
            ])
            result = summarize(path)
            self.assertEqual(result["label"], LABEL)
            self.assertEqual(result["scope"]["ticket_records"], 2)
            self.assertEqual(result["scope"]["unresolved_or_missing_resolution_timestamp"], 1)
            self.assertEqual(result["workflow_metrics"]["created_to_resolution_elapsed_hours"], {"median": 3.0, "p90": 3.0})
            self.assertEqual(result["workflow_metrics"]["tickets_with_multiple_contributors"], 1)
            self.assertIn({"label": "High", "count": 1, "share_pct": 50.0}, result["triage_profile"]["priority"])
            self.assertEqual(len(result["triage_profile"]["priority"]), 2)
            self.assertEqual([x["workflow_state"] for x in result["workflow_metrics"]["workflow_state_median_hours"]], ["in progress", "open"])
            serialized = json.dumps(result)
            self.assertNotIn("private-ticket", serialized)
            self.assertNotIn("issue_assignee", serialized)
            self.assertNotIn("issue_reporter", serialized)
            self.assertNotIn("ticket-number-1", serialized)
            self.assertEqual(len(result["provenance"]["source_sha256"]), 64)

    def test_history_aggregates_status_without_serializing_ticket_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "issues.csv"
            history = root / "issues_change_history.csv"
            row = {field: "" for field in FIELDS}
            row.update(id="masked-id-1", issue_num="masked-id-1", issue_created="2022-01-01T00:00:00+00:00", issue_resolution_date="2022-01-01T01:00:00+00:00")
            self.write_csv(source, FIELDS, [row])
            self.write_csv(history, ["id", "issueid", "field", "value", "created"], [
                {"id": "history-1", "issueid": "masked-id-1", "field": "status", "value": "open", "created": "2022-01-01T00:00:00+00:00"},
                {"id": "history-2", "issueid": "masked-id-1", "field": "assignee", "value": "4xyz", "created": "2022-01-01T00:10:00+00:00"},
                {"id": "history-3", "issueid": "masked-id-1", "field": "assignee", "value": "4abc", "created": "2022-01-01T00:20:00+00:00"},
                {"id": "history-4", "issueid": "masked-id-1", "field": "status", "value": "resolved", "created": "2022-01-01T01:00:00+00:00"},
                {"id": "history-5", "issueid": "not-in-current-file", "field": "assignee", "value": "4xyz", "created": "2022-01-02T00:00:00+00:00"},
            ])
            result = summarize(source, history)
            self.assertEqual(result["change_history"]["history_rows"], 5)
            self.assertEqual(result["change_history"]["status_change_count"], 2)
            self.assertEqual(result["change_history"]["assignment_history"]["assignee_change_events_per_ticket"]["median"], 1.0)
            self.assertEqual(result["change_history"]["ticket_records_with_history_pct"], 100)
            self.assertEqual(result["change_history"]["ticket_records_without_history"], 0)
            serialized = json.dumps(result)
            for forbidden in ("masked-id-1", "history-1", "not-in-current-file", "4xyz", "4abc"):
                self.assertNotIn(forbidden, serialized)

    def test_rejects_missing_schema_and_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "bad.csv"
            bad.write_text("id,issue_type\n1,Incident\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing required fields"):
                summarize(bad)
            duplicate = Path(directory) / "duplicate.csv"
            row = {field: "" for field in FIELDS}
            row.update(id="same", issue_num="same", issue_created="2022-01-01T00:00:00+00:00", issue_resolution_date="2022-01-01T00:01:00+00:00")
            self.write_csv(duplicate, FIELDS, [row, row])
            with self.assertRaisesRegex(ValueError, "duplicate issue IDs"):
                summarize(duplicate)

    def test_rejects_invalid_timestamps_and_negative_elapsed_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "issues.csv"
            row = {field: "" for field in FIELDS}
            row.update(id="1", issue_num="1", issue_created="bad")
            self.write_csv(path, FIELDS, [row])
            with self.assertRaisesRegex(ValueError, "invalid issue_created timestamp"):
                summarize(path)
            row.update(issue_created="2022-01-02T00:00:00+00:00", issue_resolution_date="2022-01-01T00:00:00+00:00")
            self.write_csv(path, FIELDS, [row])
            with self.assertRaisesRegex(ValueError, "negative created-to-resolution intervals"):
                summarize(path)


if __name__ == "__main__":
    unittest.main()
