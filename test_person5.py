import sqlite3
import unittest
from pathlib import Path

from query_runner import load_queries
from time_entry import add_entry, edit_entry, delete_entry

HERE = Path(__file__).resolve().parent


class Person5Tests(unittest.TestCase):
    def setUp(self):
        # Each test starts with its own sample data.
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(
            (HERE / "schema.sql").read_text(encoding="utf-8")
        )
        self.conn.executescript("""
            INSERT INTO Client (
                client_id, government_id_last4, first_name, last_name,
                dob, phone, email, address, date_registered
            ) VALUES (
                1, '1234', 'Jordan', 'Smith', '1990-01-01',
                '2255550100', 'jordan@example.com', '123 Main St',
                '2026-01-01'
            );

            INSERT INTO Employee (
                employee_id, first_name, last_name, dob, phone,
                email, hire_date, job_role, hourly_rate, bar_number
            ) VALUES
                (1, 'Alex', 'Brown', '1980-01-01', '2255550101',
                 'alex@example.com', '2020-01-01', 'Attorney', 200, 'LA100'),
                (2, 'Sam', 'Jones', '1985-01-01', '2255550102',
                 'sam@example.com', '2020-01-01', 'Attorney', 250, 'LA101'),
                (3, 'Taylor', 'Green', '1990-01-01', '2255550103',
                 'taylor@example.com', '2020-01-01', 'Legal Assistant',
                 NULL, NULL);

            INSERT INTO PracticeArea VALUES (1, 'Family Law');
            INSERT INTO PracticeArea VALUES (2, 'Business Law');

            INSERT INTO LegalCase (
                case_id, case_title, description, status,
                date_opened, client_id, practice_area_id
            ) VALUES (
                1, 'Smith Case', 'Sample case', 'Open',
                '2026-01-01', 1, 1
            );

            INSERT INTO CaseAssignment (
                case_id, employee_id, case_role, date_assigned
            ) VALUES
                (1, 1, 'Lead', '2026-01-01'),
                (1, 3, 'Associate', '2026-01-01');

            INSERT INTO Court VALUES (
                1, 'Sample Court', 'State', '100 Court St'
            );

            INSERT INTO Hearing (
                hearing_id, case_id, court_id, hearing_date,
                hearing_time, purpose
            ) VALUES
                (1, 1, 1, '2026-11-30', '09:00', 'Before window'),
                (2, 1, 1, '2026-12-01', '09:00', 'First day'),
                (3, 1, 1, '2026-12-14', '09:00', 'Last day'),
                (4, 1, 1, '2026-12-15', '09:00', 'After window');

            INSERT INTO Invoice VALUES
                (1, 1, '2026-10-01', '2026-10-15', 1000, 'Sent'),
                (2, 1, '2026-10-01', '2026-11-01', 200, 'Sent'),
                (3, 1, '2026-10-01', '2026-10-15', 300, 'Paid'),
                (4, 1, '2026-10-01', '2026-10-15', 900, 'Draft');

            INSERT INTO Payment (
                payment_id, invoice_id, payment_date, amount, method
            ) VALUES
                (1, 1, '2026-10-20', 100, 'Cash'),
                (2, 1, '2026-10-25', 150, 'Card'),
                (3, 3, '2026-10-25', 300, 'ACH');

            INSERT INTO TimeEntry (
                time_entry_id, case_id, employee_id, work_date,
                hours, hourly_rate, description, billing_status, invoice_id
            ) VALUES
                (1, 1, 1, '2026-10-01', 2, 200, 'Research',
                 'Unbilled', NULL),
                (2, 1, 1, '2026-10-02', 5, 200, 'Case work',
                 'Billed', 1),
                (3, 1, 1, '2026-10-03', 1, 200, 'Written off work',
                 'Written Off', NULL);
        """)

    def tearDown(self):
        self.conn.close()

    def test_add_entry_saves_rate_and_status(self):
        entry_id = add_entry(
            self.conn, 1, 1, "2026-11-01", 1.5, "Client meeting"
        )
        row = self.conn.execute(
            """
            SELECT hours, hourly_rate, billing_status, invoice_id
            FROM TimeEntry WHERE time_entry_id = ?
            """,
            (entry_id,),
        ).fetchone()
        self.assertEqual(row, (1.5, 200.0, "Unbilled", None))

    def test_invalid_hours_are_rejected(self):
        for hours in (0, -1, 25, float("nan"), float("inf")):
            with self.subTest(hours=hours):
                with self.assertRaises(ValueError):
                    add_entry(
                        self.conn, 1, 1, "2026-11-01", hours, "Research"
                    )

    def test_invalid_date_is_rejected(self):
        with self.assertRaises(ValueError):
            add_entry(self.conn, 1, 1, "2026-02-30", 1, "Research")

    def test_missing_case_is_rejected(self):
        with self.assertRaises(ValueError):
            add_entry(self.conn, 999, 1, "2026-11-01", 1, "Research")

    def test_unassigned_employee_is_rejected(self):
        with self.assertRaises(ValueError):
            add_entry(self.conn, 1, 2, "2026-11-01", 1, "Research")

    def test_missing_rate_is_rejected(self):
        with self.assertRaises(ValueError):
            add_entry(self.conn, 1, 3, "2026-11-01", 1, "Research")

    def test_assignment_dates_are_checked(self):
        with self.assertRaises(ValueError):
            add_entry(self.conn, 1, 1, "2025-12-31", 1, "Research")

        with self.conn:
            self.conn.execute(
                """
                UPDATE CaseAssignment SET date_unassigned = '2026-11-01'
                WHERE case_id = 1 AND employee_id = 1
                """
            )

        with self.assertRaises(ValueError):
            add_entry(self.conn, 1, 1, "2026-11-02", 1, "Research")

    def test_blank_description_is_rejected(self):
        with self.assertRaises(ValueError):
            add_entry(self.conn, 1, 1, "2026-11-01", 1, "   ")

    def test_edit_keeps_original_rate(self):
        with self.conn:
            self.conn.execute(
                "UPDATE Employee SET hourly_rate = 300 WHERE employee_id = 1"
            )

        edit_entry(self.conn, 1, "2026-11-02", 3, "Updated research")
        row = self.conn.execute(
            """
            SELECT work_date, hours, hourly_rate, description
            FROM TimeEntry WHERE time_entry_id = 1
            """
        ).fetchone()
        self.assertEqual(row, ("2026-11-02", 3.0, 200.0, "Updated research"))

    def test_delete_unbilled_entry(self):
        delete_entry(self.conn, 1)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM TimeEntry WHERE time_entry_id = 1"
        ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_protected_entries_cannot_be_changed(self):
        for entry_id in (2, 3):
            with self.subTest(entry_id=entry_id):
                with self.assertRaises(ValueError):
                    edit_entry(
                        self.conn, entry_id, "2026-11-02", 2, "Changed"
                    )
                with self.assertRaises(ValueError):
                    delete_entry(self.conn, entry_id)

    def test_missing_entries_are_rejected(self):
        with self.assertRaises(ValueError):
            edit_entry(self.conn, 999, "2026-11-02", 1, "Research")
        with self.assertRaises(ValueError):
            delete_entry(self.conn, 999)

    def test_failed_add_does_not_save_a_row(self):
        before = self.conn.execute(
            "SELECT COUNT(*) FROM TimeEntry"
        ).fetchone()[0]

        with self.assertRaises(ValueError):
            add_entry(self.conn, 1, 2, "2026-11-01", 1, "Research")

        after = self.conn.execute(
            "SELECT COUNT(*) FROM TimeEntry"
        ).fetchone()[0]
        self.assertEqual(before, after)

        # A failed entry should not stop the next valid entry.
        add_entry(self.conn, 1, 1, "2026-11-01", 1, "Research")

    def query_results(self, index):
        return self.conn.execute(
            load_queries()[index], {"as_of": "2026-12-01"}
        ).fetchall()

    def test_open_cases_query(self):
        self.assertEqual(
            self.query_results(0),
            [(1, "Alex Brown", 1), (2, "Sam Jones", 0)],
        )

    def test_overdue_invoice_query(self):
        # Invoice 2 is exactly 30 days overdue, so it stays out.
        self.assertEqual(
            self.query_results(1),
            [(1, "Jordan Smith", "2026-10-15", 750.0)],
        )

    def test_billable_hours_query(self):
        self.assertEqual(
            self.query_results(2),
            [("Family Law", 7.0), ("Business Law", 0.0)],
        )

    def test_upcoming_hearings_query(self):
        rows = self.query_results(3)
        self.assertEqual([row[0] for row in rows], [2, 3])
        self.assertTrue(all(row[5] == "Alex Brown" for row in rows))

    def test_top_clients_query(self):
        self.assertEqual(
            self.query_results(4),
            [(1, 1, "Jordan Smith", 1500.0)],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
