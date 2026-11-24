import hashlib
import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from unittest.mock import patch
from pathlib import Path

from generate_data import generate_database
from hearing_document import (
    add_document, add_hearing, delete_document, delete_hearing,
    get_document, get_hearing, list_documents, list_hearings,
    update_document, update_hearing, open_connection,
    hearing_document_menu, ask_date, ask_id, ask_enum, ask_text, ask_time,
    positive_id, require_record, record_change, valid_date, valid_time,
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
        future = (date.today() + timedelta(days=10)).isoformat()
        for day, hour, outcome in (
            ("2026-02-30", "09:00", None),
            ("2026-12-04", "25:00", None),
            ("2026-12-04", "9:00", None),
            ("2026-12-04", "09:00", "Approved"),
            ("2025-12-01", "09:00", None),
            (future, "09:00", "Granted"),
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


    def test_today_hearing_can_have_outcome(self):
        record_id = add_hearing(self.conn, 1, 1, date.today().isoformat(),
                                "10:00", "Status conference", "Granted")
        self.assertEqual(get_hearing(self.conn, record_id)["outcome"], "Granted")

    def test_validator_rejects_bad_date_time_and_ids(self):
        for bad in (None, 20261205, "2026-2-05", "2026-02-30"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    valid_date(bad)
        for bad in (None, 1030, "9:00", "24:00"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    valid_time(bad)
        for bad in (True, 0, -2, "1"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    positive_id(bad, "ID")
        self.assertEqual(valid_date("2026-10-03"), date(2026, 10, 3))
        self.assertEqual(valid_time("07:05"), "07:05")

    def test_require_record_checks_allowed_types_and_existence(self):
        self.assertIsNone(require_record(self.conn, "Court", "court_id", 1))
        with self.assertRaises(ValueError):
            require_record(self.conn, "Court", "court_id", 999)
        with self.assertRaises(ValueError):
            require_record(self.conn, "Invoice", "invoice_id", 1)
        with self.assertRaises(ValueError):
            require_record(self.conn, "Court", "case_id", 1)

    def test_generator_is_repeatable(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "bayou.db"
            generate_database(target, HERE / "schema.sql")
            first = hashlib.sha256(target.read_bytes()).digest()
            generate_database(target, HERE / "schema.sql")
            self.assertEqual(hashlib.sha256(target.read_bytes()).digest(), first)

    def test_generator_rejects_paths_that_are_not_database_files(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "notes.sql"
            target.write_text("Do not change me", encoding="utf-8")
            with self.assertRaises(ValueError):
                generate_database(target, HERE / "schema.sql")
            self.assertEqual(target.read_text(encoding="utf-8"), "Do not change me")

    def test_failed_rebuild_preserves_existing_database(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "bayou.db"
            bad_schema = Path(folder) / "bad.sql"
            bad_schema.write_text("CREATE TABLE Broken (x INTEGER);", encoding="utf-8")
            generate_database(target, HERE / "schema.sql")
            before = target.read_bytes()
            with self.assertRaises(sqlite3.Error):
                generate_database(target, bad_schema)
            self.assertEqual(target.read_bytes(), before)

    def test_open_connection_enforces_foreign_keys(self):
        conn = open_connection(self.database)
        try:
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertIsInstance(conn.execute("SELECT * FROM Client LIMIT 1").fetchone(), sqlite3.Row)
        finally:
            conn.close()

    def test_menu_rejects_connection_without_foreign_key_enforcement(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("BEGIN")
            with redirect_stdout(io.StringIO()) as output:
                hearing_document_menu(conn)
            self.assertIn("Enable foreign keys", output.getvalue())
        finally:
            conn.rollback()
            conn.close()

    def test_own_change_does_not_commit_outer_transaction(self):
        self.conn.execute("BEGIN")
        record_id = add_hearing(self.conn, 1, 1, "2026-12-07", "11:00", "Review")
        self.assertTrue(self.conn.in_transaction)
        self.conn.rollback()
        with self.assertRaises(ValueError):
            get_hearing(self.conn, record_id)

    def test_change_rolls_back_when_sql_fails(self):
        count_before = self.conn.execute("SELECT COUNT(*) FROM Court").fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            with record_change(self.conn):
                self.conn.execute("INSERT INTO Court VALUES (99, 'Demo Court', 'State', 'Test')")
                self.conn.execute("INSERT INTO Court VALUES (99, 'Duplicate', 'State', 'Test')")
        count_after = self.conn.execute("SELECT COUNT(*) FROM Court").fetchone()[0]
        self.assertEqual(count_after, count_before)

    def test_input_helpers_reprompt_and_keep_existing_values(self):
        with patch("builtins.input", side_effect=["bad", "-1", "3"]), redirect_stdout(io.StringIO()):
            self.assertEqual(ask_id("Case ID"), 3)
        with patch("builtins.input", side_effect=["2026-02-30", "2026-12-05"]), redirect_stdout(io.StringIO()):
            self.assertEqual(ask_date("Date"), "2026-12-05")
        with patch("builtins.input", side_effect=["26:30", "10:45"]), redirect_stdout(io.StringIO()):
            self.assertEqual(ask_time("Time"), "10:45")
        with patch("builtins.input", return_value=""):
            self.assertIsNone(ask_id("Case ID", allow_keep=True))
            self.assertEqual(ask_text("Purpose", old="Initial"), "Initial")
            self.assertEqual(ask_date("Date", old="2026-10-03"), "2026-10-03")
            self.assertEqual(ask_time("Time", old="11:00"), "11:00")
        with patch("builtins.input", side_effect=["wrong", "evidence"]), redirect_stdout(io.StringIO()):
            self.assertEqual(ask_enum("Type", ("Pleading", "Evidence")), "Evidence")
        with patch("builtins.input", return_value="clear"), redirect_stdout(io.StringIO()):
            self.assertIsNone(ask_enum("Outcome", ("Granted", "Denied"), optional=True, old="Granted"))

    def test_cli_hearing_add_view_update_delete(self):
        new_id = 26  # The seeded database has 25 hearings.
        inputs = [
            "wrong", "1", "1", "1", "2026-12-07", "10:00", "Review", "",
            "2", "d", str(new_id),
            "2", "c", "1",
            "3", str(new_id), "", "", "", "", "Updated review", "",
            "4", str(new_id), "y", "0",
        ]
        with patch("builtins.input", side_effect=inputs), redirect_stdout(io.StringIO()) as output:
            hearing_document_menu(self.conn)
        self.assertIn("Hearing 26 added", output.getvalue())
        self.assertIn("Updated review", output.getvalue())
        self.assertIn("Hearing deleted", output.getvalue())
        with self.assertRaises(ValueError):
            get_hearing(self.conn, new_id)

    def test_cli_document_add_view_update_delete(self):
        new_id = 61  # The seeded database has 60 documents.
        inputs = [
            "5", "1", "1", "New notes", "Evidence", "2026-11-20", "documents/case_001/new.pdf",
            "6", "d", str(new_id),
            "6", "c", "1",
            "7", str(new_id), "", "", "Updated notes", "", "", "",
            "8", str(new_id), "y", "0",
        ]
        with patch("builtins.input", side_effect=inputs), redirect_stdout(io.StringIO()) as output:
            hearing_document_menu(self.conn)
        self.assertIn("Document 61 added", output.getvalue())
        self.assertIn("Updated notes", output.getvalue())
        self.assertIn("Document deleted", output.getvalue())
        with self.assertRaises(ValueError):
            get_document(self.conn, new_id)

    def test_cli_respects_cancelled_deletions(self):
        h = add_hearing(self.conn, 1, 1, "2026-12-04", "09:00", "Review")
        d = add_document(self.conn, 1, 1, "Keep", "Evidence", "2026-10-03", "documents/keep.pdf")
        with patch("builtins.input", side_effect=["4", str(h), "n", "8", str(d), "n", "0"]), redirect_stdout(io.StringIO()):
            hearing_document_menu(self.conn)
        self.assertEqual(get_hearing(self.conn, h)["purpose"], "Review")
        self.assertEqual(get_document(self.conn, d)["title"], "Keep")

    def test_cli_handles_invalid_choices_and_records(self):
        with patch("builtins.input", side_effect=["9", "2", "x", "3", "999", "0"]), redirect_stdout(io.StringIO()) as output:
            hearing_document_menu(self.conn)
        self.assertIn("Choose a number from 0 through 8", output.getvalue())
        self.assertIn("Choose a, c, or d", output.getvalue())
        self.assertIn("That hearing does not exist", output.getvalue())

    def test_sql_parameters_protect_document_title(self):
        tricky = "Client'); DROP TABLE Client; --"
        record_id = add_document(self.conn, 1, 1, tricky, "Evidence", "2026-10-03", "documents/test.pdf")
        self.assertEqual(get_document(self.conn, record_id)["title"], tricky)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM Client").fetchone()[0], 30)

    def test_actual_queries_when_available(self):
        query_file = HERE / "queries.sql"
        if not query_file.is_file():
            self.skipTest("Ceionna's queries.sql is on her branch, not Joy_branch")
        with redirect_stdout(io.StringIO()):
            self.assertTrue(verify_database(self.database, query_file))

    def test_verifier_catches_bad_invoice_total(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "bad_bayou.db"
            disk = sqlite3.connect(target)
            self.conn.backup(disk)
            disk.execute("UPDATE Invoice SET total_amount = total_amount + 1 WHERE invoice_id = 1")
            disk.commit()
            disk.close()
            with redirect_stdout(io.StringIO()):
                self.assertFalse(verify_database(target))

    def test_verifier_catches_client_registered_after_case(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "bad_bayou.db"
            disk = sqlite3.connect(target)
            self.conn.backup(disk)
            disk.execute("UPDATE Client SET date_registered = '2026-04-01' WHERE client_id = 1")
            disk.commit()
            disk.close()
            with redirect_stdout(io.StringIO()):
                self.assertFalse(verify_database(target))


if __name__ == "__main__":
    unittest.main(verbosity=2)
