"""Tests for the Person 3 modules: db_connection, client_management, case_management.

Each test builds a throwaway database from schema.sql, so bayou.db is never touched.
Run: python -m unittest -v test_person3
"""
import builtins
import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import case_management as cm
import client_management as cl
from db_connection import get_connection

HERE = Path(__file__).resolve().parent
TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()


class Person3Base(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        setup = sqlite3.connect(self.path)
        setup.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
        setup.executescript("""
            INSERT INTO PracticeArea VALUES (1, 'Family Law'), (2, 'Business Law');
            INSERT INTO Employee (employee_id, first_name, last_name, dob, phone, email, hire_date,
                                  is_active, job_role, hourly_rate, bar_number) VALUES
              (1, 'Ada', 'Lead', '1980-01-01', '225-555-0101', 'ada@bayou.test', '2020-01-01', 'TRUE', 'Attorney', 250, 'LA1'),
              (2, 'Ben', 'Second', '1985-01-01', '225-555-0102', 'ben@bayou.test', '2020-01-01', 'TRUE', 'Attorney', 200, 'LA2'),
              (3, 'Cal', 'Gone', '1970-01-01', '225-555-0103', 'cal@bayou.test', '2010-01-01', 'FALSE', 'Attorney', 300, 'LA3'),
              (4, 'Dee', 'Para', '1990-01-01', '225-555-0104', 'dee@bayou.test', '2021-01-01', 'TRUE', 'Paralegal', NULL, NULL);
            INSERT INTO Client (client_id, government_id_last4, first_name, last_name, dob, phone, email, address)
              VALUES (1, '1234', 'Rita', 'Boudreaux', '1975-05-05', '225-555-0001', 'rita@example.com', '1 Main St, Baton Rouge, LA');
        """)
        setup.commit()
        setup.close()
        self.conn = get_connection(self.path)

    def tearDown(self):
        self.conn.close()
        os.remove(self.path)

    def count(self, sql, args=()):
        return self.conn.execute(sql, args).fetchone()[0]


class ConnectionTests(Person3Base):
    def test_foreign_keys_on_and_rows_by_name(self):
        self.assertEqual(self.conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        row = self.conn.execute("SELECT client_id FROM Client").fetchone()
        self.assertEqual(row["client_id"], 1)

    def test_missing_file_is_not_created(self):
        missing = Path(self.path).with_name("does_not_exist_p3.db")
        with self.assertRaises(sqlite3.OperationalError):
            get_connection(missing)
        self.assertFalse(missing.exists())

    def test_invalid_reference_rejected_by_database(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO LegalCase (case_title, description, status, client_id, practice_area_id)"
                " VALUES ('x', 'y', 'Open', 999, 1)")


class ClientTests(Person3Base):
    def add(self, **over):
        data = dict(first_name="Luc", last_name="Thibodeaux", dob="1990-02-03",
                    phone="(225) 555-0199", email="Luc@Example.com",
                    address="9 Bayou Rd, Lafayette, LA", government_id_last4="4321")
        data.update(over)
        return cl.add_client(self.conn, **data)

    def test_add_and_search(self):
        new_id = self.add(middle_name="  ")
        row = cl.get_client(self.conn, new_id)
        self.assertEqual(row["email"], "luc@example.com")
        self.assertIsNone(row["middle_name"])
        self.assertEqual(row["date_registered"], TODAY)
        self.assertEqual([r["client_id"] for r in cl.search_clients(self.conn, "thibo")], [new_id])
        self.assertEqual(len(cl.search_clients(self.conn, "")), 2)

    def test_add_rejects_bad_input(self):
        bad = [dict(email="not-an-email"), dict(phone="12"), dict(government_id_last4="12a4"),
               dict(dob="1990-02-30"), dict(dob=TOMORROW), dict(first_name="  "),
               dict(email="RITA@example.com")]
        for override in bad:
            with self.subTest(override=override):
                with self.assertRaises(ValueError):
                    self.add(**override)
        self.assertEqual(self.count("SELECT COUNT(*) FROM Client"), 1)

    def test_update_contact_keeps_unchanged_fields(self):
        cl.update_contact(self.conn, 1, phone="225-555-7777")
        row = cl.get_client(self.conn, 1)
        self.assertEqual(row["phone"], "225-555-7777")
        self.assertEqual(row["email"], "rita@example.com")

    def test_update_rejects_duplicate_email_and_missing_client(self):
        other = self.add()
        with self.assertRaises(ValueError):
            cl.update_contact(self.conn, other, email="rita@example.com")
        with self.assertRaises(ValueError):
            cl.update_contact(self.conn, 999, phone="225-555-0000")

    def test_delete_unused_client_only(self):
        unused = self.add()
        cl.delete_client(self.conn, unused)
        self.assertEqual(self.count("SELECT COUNT(*) FROM Client WHERE client_id = ?", (unused,)), 0)
        cm.open_case(self.conn, 1, 1, "Smith custody", "Custody dispute", 1)
        with self.assertRaises(ValueError):
            cl.delete_client(self.conn, 1)
        self.assertEqual(self.count("SELECT COUNT(*) FROM Client WHERE client_id = 1"), 1)


class CaseTests(Person3Base):
    def new_case(self, **over):
        data = dict(client_id=1, practice_area_id=1, case_title="Boudreaux divorce",
                    description="Uncontested divorce", lead_attorney_id=1, date_opened=YESTERDAY)
        data.update(over)
        return cm.open_case(self.conn, **data)

    def test_open_case_creates_lead_assignment(self):
        case_id = self.new_case()
        lead = self.conn.execute(
            "SELECT employee_id, case_role, date_assigned FROM CaseAssignment WHERE case_id = ?",
            (case_id,)).fetchall()
        self.assertEqual([tuple(r) for r in lead], [(1, "Lead", YESTERDAY)])
        self.assertEqual(cm.get_case(self.conn, case_id)["status"], "Open")

    def test_open_case_rejects_invalid_references(self):
        bad = [dict(client_id=999), dict(practice_area_id=999), dict(lead_attorney_id=999),
               dict(lead_attorney_id=3), dict(lead_attorney_id=4), dict(date_opened=TOMORROW),
               dict(status="Closed"), dict(case_title="")]
        for override in bad:
            with self.subTest(override=override):
                with self.assertRaises(ValueError):
                    self.new_case(**override)
        self.assertEqual(self.count("SELECT COUNT(*) FROM LegalCase"), 0)
        self.assertEqual(self.count("SELECT COUNT(*) FROM CaseAssignment"), 0)

    def test_assign_and_duplicate_and_second_lead(self):
        case_id = self.new_case()
        cm.assign_attorney(self.conn, case_id, 2, "Associate", TODAY)
        with self.assertRaises(ValueError):
            cm.assign_attorney(self.conn, case_id, 2, "Consulting")
        with self.assertRaises(ValueError):
            cm.assign_attorney(self.conn, case_id, 4, "Associate")      # paralegal
        self.conn.execute("UPDATE CaseAssignment SET date_unassigned = ? WHERE employee_id = 2", (TODAY,))
        with self.assertRaises(ValueError):
            cm.assign_attorney(self.conn, case_id, 2, "Lead")           # Lead already exists
        with self.assertRaises(ValueError):
            cm.assign_attorney(self.conn, case_id, 2, "Associate", "2000-01-01")  # before case opened

    def test_unassign_keeps_history_and_reassign_reuses_row(self):
        case_id = self.new_case()
        cm.assign_attorney(self.conn, case_id, 2, "Associate", YESTERDAY)
        cm.unassign_attorney(self.conn, case_id, 2, TODAY)
        row = self.conn.execute(
            "SELECT date_unassigned FROM CaseAssignment WHERE case_id = ? AND employee_id = 2",
            (case_id,)).fetchone()
        self.assertEqual(row["date_unassigned"], TODAY)
        with self.assertRaises(ValueError):
            cm.unassign_attorney(self.conn, case_id, 2, TODAY)          # already removed
        cm.assign_attorney(self.conn, case_id, 2, "Consulting", TODAY)
        self.assertEqual(self.count("SELECT COUNT(*) FROM CaseAssignment WHERE case_id = ?", (case_id,)), 2)

    def test_cannot_remove_lead_or_unassign_before_logged_time(self):
        case_id = self.new_case()
        with self.assertRaises(ValueError):
            cm.unassign_attorney(self.conn, case_id, 1)
        cm.assign_attorney(self.conn, case_id, 2, "Associate", YESTERDAY)
        self.conn.execute(
            "INSERT INTO TimeEntry (case_id, employee_id, work_date, hours, hourly_rate, description)"
            " VALUES (?, 2, ?, 1.5, 200, 'Research')", (case_id, TODAY))
        with self.assertRaises(ValueError):
            cm.unassign_attorney(self.conn, case_id, 2, TODAY)

    def test_change_lead_demotes_old_lead(self):
        case_id = self.new_case()
        with self.assertRaises(ValueError):
            cm.change_lead(self.conn, case_id, 2)                       # not on the case yet
        cm.assign_attorney(self.conn, case_id, 2, "Associate", TODAY)
        cm.change_lead(self.conn, case_id, 2)
        roles = dict(self.conn.execute(
            "SELECT employee_id, case_role FROM CaseAssignment WHERE case_id = ?", (case_id,)).fetchall())
        self.assertEqual(roles, {1: "Associate", 2: "Lead"})
        cm.unassign_attorney(self.conn, case_id, 1, TODAY)              # old Lead can now leave

    def test_update_close_and_reopen(self):
        case_id = self.new_case()
        cm.update_case(self.conn, case_id, case_title="Boudreaux v. Boudreaux",
                       practice_area_id=2, status="Pending")
        case = cm.get_case(self.conn, case_id)
        self.assertEqual((case["case_title"], case["practice_area_id"], case["status"]),
                         ("Boudreaux v. Boudreaux", 2, "Pending"))
        for bad in (dict(status="Closed"), dict(practice_area_id=999), dict(case_title=" ")):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    cm.update_case(self.conn, case_id, **bad)
        with self.assertRaises(ValueError):
            cm.close_case(self.conn, case_id, "2000-01-01")             # before it opened
        cm.close_case(self.conn, case_id, TODAY)
        case = cm.get_case(self.conn, case_id)
        self.assertEqual((case["status"], case["date_closed"]), ("Closed", TODAY))
        for action in (lambda: cm.update_case(self.conn, case_id, case_title="x"),
                       lambda: cm.assign_attorney(self.conn, case_id, 2),
                       lambda: cm.close_case(self.conn, case_id)):
            with self.assertRaises(ValueError):
                action()
        cm.reopen_case(self.conn, case_id)
        case = cm.get_case(self.conn, case_id)
        self.assertEqual((case["status"], case["date_closed"]), ("Open", None))

    def test_open_case_is_all_or_nothing(self):
        # Force the Lead insert to fail after the case insert; nothing should remain.
        self.conn.execute("""CREATE TEMP TRIGGER fail_assign BEFORE INSERT ON CaseAssignment
                             BEGIN SELECT RAISE(ABORT, 'forced'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.new_case()
        self.assertEqual(self.count("SELECT COUNT(*) FROM LegalCase"), 0)


class MenuTests(Person3Base):
    def run_menu(self, menu, answers):
        out = io.StringIO()
        with mock.patch.object(builtins, "input", side_effect=answers), redirect_stdout(out):
            menu(self.conn)
        return out.getvalue()

    def test_client_menu_add_and_bad_choice(self):
        text = self.run_menu(cl.client_menu, [
            "9", "abc",
            "1", "Mae", "", "Landry", "1988-08-08", "225-555-0123", "mae@example.com",
            "4 Oak St, Baton Rouge, LA", "9876",
            "0"])
        self.assertIn("Choose a number from 0 through 5.", text)
        self.assertIn("Client 2 added.", text)

    def test_case_menu_open_view_and_invalid_input_does_not_crash(self):
        text = self.run_menu(cm.case_menu, [
            "1", "1", "1", "Landry estate", "Will and trust", "1", "", "Open",
            "3", "1",
            "5", "1", "4", "Associate", "",          # paralegal rejected
            "1", "999",                              # unknown client
            "0"])
        self.assertIn("Case 1 opened", text)
        self.assertIn("Ada Lead", text)
        self.assertIn("not an attorney", text)
        self.assertIn("Client 999 does not exist", text)

    def test_menus_return_on_end_of_input(self):
        for menu in (cl.client_menu, cm.case_menu):
            with self.subTest(menu=menu.__name__):
                self.assertIn("Returning", self.run_menu(menu, EOFError()))


if __name__ == "__main__":
    unittest.main()
