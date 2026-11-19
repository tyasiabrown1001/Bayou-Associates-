import sqlite3
import tempfile
import unittest
from pathlib import Path

from generate_data import generate_database
from hearing_document import (
    add_document, add_hearing, delete_document, delete_hearing,
    get_document, get_hearing, list_documents, list_hearings,
    update_document, update_hearing,
)
from verify_data import verify_database

HERE = Path(__file__).resolve().parent


class Person4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.database = Path(cls.folder.name) / "test_bayou.db"
        generate_database(cls.database, HERE / "schema.sql")

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        source = sqlite3.connect(self.database)
        self.conn = sqlite3.connect(":memory:")
        source.backup(self.conn)
        source.close()
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def tearDown(self):
        self.conn.close()

    def test_sample_database_verifies(self):
        self.assertTrue(verify_database(self.database))

    def test_hearing_add_and_detail(self):
        record_id = add_hearing(self.conn, 1, 1, "2026-12-07", "10:30", "Scheduling")
        row = get_hearing(self.conn, record_id)
        self.assertEqual(row["purpose"], "Scheduling")
        self.assertEqual(row["court_name"], "Capital District Civil Court")
        self.assertIsNone(row["outcome"])

    def test_hearing_views_by_case_and_all(self):
        record_id = add_hearing(self.conn, 2, 2, "2026-11-28", "14:00", "Status review")
        self.assertIn(record_id, [row["hearing_id"] for row in list_hearings(self.conn)])
        self.assertIn(record_id, [row["hearing_id"] for row in list_hearings(self.conn, 2)])
        self.assertNotIn(record_id, [row["hearing_id"] for row in list_hearings(self.conn, 1)])

    def test_hearing_update_keeps_original_values(self):
        record_id = add_hearing(self.conn, 1, 1, "2026-11-27", "09:00", "Review")
        update_hearing(self.conn, record_id, hearing_time="11:15", purpose="Updated review")
        row = get_hearing(self.conn, record_id)
        self.assertEqual((row["case_id"], row["court_id"]), (1, 1))
        self.assertEqual((row["hearing_time"], row["purpose"]), ("11:15", "Updated review"))

    def test_hearing_outcome_can_be_cleared(self):
        record_id = add_hearing(self.conn, 1, 1, "2026-10-03", "09:00", "Motion", "Granted")
        update_hearing(self.conn, record_id, outcome=None)
        self.assertIsNone(get_hearing(self.conn, record_id)["outcome"])

    def test_hearing_delete(self):
        record_id = add_hearing(self.conn, 1, 1, "2026-11-27", "09:00", "Motion")
        delete_hearing(self.conn, record_id)
        with self.assertRaises(ValueError):
            get_hearing(self.conn, record_id)

    def test_hearing_invalid_case_and_court(self):
        for case_id, court_id in ((999, 1), (1, 999)):
            with self.subTest(case_id=case_id, court_id=court_id):
                with self.assertRaises(ValueError):
                    add_hearing(self.conn, case_id, court_id, "2026-12-04", "09:00", "Review")

    def test_hearing_bad_dates_times_and_outcomes(self):
        for day, hour, outcome in (
            ("2026-02-30", "09:00", None),
            ("2026-12-04", "25:00", None),
            ("2026-12-04", "9:00", None),
            ("2026-12-04", "09:00", "Approved"),
            ("2025-12-01", "09:00", None),
            ("2026-12-04", "09:00", "Granted"),
        ):
            with self.subTest(day=day, hour=hour, outcome=outcome):
                with self.assertRaises(ValueError):
                    add_hearing(self.conn, 1, 1, day, hour, "Review", outcome)

    def test_closed_case_does_not_allow_future_hearing(self):
        with self.assertRaises(ValueError):
            add_hearing(self.conn, 31, 1, "2026-12-04", "10:00", "Review")

    def test_document_add_and_detail(self):
        record_id = add_document(self.conn, 1, 1, "Case notes", "Evidence",
                                 "2026-10-03", "documents/case_001/notes.pdf")
        row = get_document(self.conn, record_id)
        self.assertEqual(row["title"], "Case notes")
        self.assertIn(" ", row["uploader"])
        self.assertIn("case_001", row["file_path"])

    def test_document_views_by_case_and_all(self):
        record_id = add_document(self.conn, 2, 1, "Case notes", "Pleading",
                                 "2026-10-03", "documents/case_002/notes.pdf")
        self.assertIn(record_id, [row["document_id"] for row in list_documents(self.conn)])
        self.assertIn(record_id, [row["document_id"] for row in list_documents(self.conn, 2)])
        self.assertNotIn(record_id, [row["document_id"] for row in list_documents(self.conn, 1)])

    def test_document_update_keeps_other_fields(self):
        record_id = add_document(self.conn, 1, 1, "Initial filing", "Pleading",
                                 "2026-10-03", "documents/case_001/start.pdf")
        update_document(self.conn, record_id, title="Updated filing", doc_type="Correspondence")
        row = get_document(self.conn, record_id)
        self.assertEqual((row["title"], row["doc_type"]), ("Updated filing", "Correspondence"))
        self.assertEqual(row["file_path"], "documents/case_001/start.pdf")

    def test_document_delete(self):
        record_id = add_document(self.conn, 1, 1, "Temporary note", "Correspondence",
                                 "2026-10-03", "documents/case_001/temp.pdf")
        delete_document(self.conn, record_id)
        with self.assertRaises(ValueError):
            get_document(self.conn, record_id)

    def test_document_invalid_references(self):
        for case_id, employee_id in ((999, 1), (1, 999)):
            with self.subTest(case_id=case_id, employee_id=employee_id):
                with self.assertRaises(ValueError):
                    add_document(self.conn, case_id, employee_id, "Notes", "Evidence",
                                 "2026-10-03", "documents/example.pdf")

    def test_document_bad_date_type_and_blank_fields(self):
        cases = (
            ("Notes", "Evidence", "2026-02-30", "documents/example.pdf"),
            ("Notes", "Report", "2026-10-03", "documents/example.pdf"),
            ("", "Evidence", "2026-10-03", "documents/example.pdf"),
            ("Notes", "Evidence", "2026-10-03", ""),
            ("Notes", "Evidence", "2025-01-01", "documents/example.pdf"),
        )
        for title, doc_type, day, path in cases:
            with self.subTest(doc_type=doc_type, day=day, title=title):
                with self.assertRaises(ValueError):
                    add_document(self.conn, 1, 1, title, doc_type, day, path)

    def test_closed_case_does_not_allow_late_document(self):
        with self.assertRaises(ValueError):
            add_document(self.conn, 31, 1, "Notes", "Evidence", "2026-11-10",
                         "documents/case_031/notes.pdf")

    def test_missing_record_update_delete_fail_safely(self):
        for operation in (
            lambda: update_hearing(self.conn, 999, purpose="Note"),
            lambda: delete_hearing(self.conn, 999),
            lambda: update_document(self.conn, 999, title="Note"),
            lambda: delete_document(self.conn, 999),
        ):
            with self.assertRaises(ValueError):
                operation()


if __name__ == "__main__":
    unittest.main(verbosity=2)
