import argparse
import sqlite3
from pathlib import Path

from generate_data import DATA_AS_OF, REFERENCE_DATE

HERE = Path(__file__).resolve().parent
DB = HERE / "bayou.db"
TARGETS = {
    "Client": 30, "Employee": 13, "PracticeArea": 4, "LegalCase": 40,
    "CaseAssignment": 52, "Court": 4, "Hearing": 25, "Document": 60,
    "TimeEntry": 120, "Invoice": 35, "Payment": 31,
}


class Checks:
    def __init__(self, conn):
        self.conn = conn
        self.failed = 0

    def check(self, label, condition, detail=""):
        if condition:
            print(f"PASS: {label}{f' — {detail}' if detail else ''}")
        else:
            print(f"FAIL: {label}{f' — {detail}' if detail else ''}")
            self.failed += 1

    def no_rows(self, label, query, args=()):
        rows = self.conn.execute(query, args).fetchall()
        self.check(label, not rows, f"{len(rows)} violations" if rows else "")


def verify_database(db_path=DB, query_path=None):
    path = Path(db_path)
    if not path.is_file():
        print(f"FAIL: Database not found: {path}")
        return False
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro")
    except sqlite3.Error as error:
        print(f"FAIL: Could not open database: {error}")
        return False
    conn.row_factory = sqlite3.Row
    checks = Checks(conn)
    try:
        print(f"Checking {path} | reference date: {REFERENCE_DATE}")
        checks.check("Database integrity", conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
        checks.check("Foreign keys", not conn.execute("PRAGMA foreign_key_check").fetchall())

        for table, target in TARGETS.items():
            count = conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            checks.check(f"{table} count", count == target, f"{count} records; target {target}")

        checks.no_rows("Synthetic contact and ID formats", """
            SELECT 'client' FROM Client
            WHERE email NOT LIKE '%@example.com' OR length(government_id_last4) <> 4
               OR phone NOT LIKE '225555%'
            UNION ALL
            SELECT 'employee' FROM Employee
            WHERE email NOT LIKE '%@example.com' OR phone NOT LIKE '225555%'
        """)
        checks.no_rows("Clients registered before their cases opened", """
            SELECT lc.case_id FROM LegalCase lc
            JOIN Client c ON c.client_id = lc.client_id
            WHERE c.date_registered > lc.date_opened
        """)
        checks.no_rows("Required case close dates", """
            SELECT case_id FROM LegalCase
            WHERE (status = 'Closed') <> (date_closed IS NOT NULL)
               OR (date_closed IS NOT NULL AND date_closed < date_opened)
        """)
        checks.no_rows("Case assignments exist and have exactly one lead", """
            SELECT lc.case_id FROM LegalCase lc
            LEFT JOIN CaseAssignment ca ON ca.case_id = lc.case_id
            GROUP BY lc.case_id
            HAVING COUNT(ca.employee_id) < 1
                OR SUM(CASE WHEN ca.case_role = 'Lead' THEN 1 ELSE 0 END) <> 1
        """)
        checks.no_rows("Assignment date order and case bounds", """
            SELECT ca.case_id, ca.employee_id FROM CaseAssignment ca
            JOIN LegalCase lc ON lc.case_id = ca.case_id
            WHERE ca.date_assigned < lc.date_opened
               OR (ca.date_unassigned IS NOT NULL AND ca.date_unassigned < ca.date_assigned)
               OR (lc.date_closed IS NOT NULL AND (
                   ca.date_assigned > lc.date_closed OR ca.date_unassigned > lc.date_closed))
        """)
        checks.no_rows("Attorney bar numbers and staff roles", """
            SELECT employee_id FROM Employee
            WHERE (job_role = 'Attorney') <> (bar_number IS NOT NULL)
        """)
        checks.no_rows("Birth dates, hire dates and client registration", """
            SELECT 'client' AS category FROM Client
            WHERE dob > ? OR date_registered > ?
            UNION ALL
            SELECT 'employee' FROM Employee
            WHERE dob > ? OR hire_date > ?
        """, (str(DATA_AS_OF), str(DATA_AS_OF), str(DATA_AS_OF), str(DATA_AS_OF)))
        checks.no_rows("Case hearing dates", """
            SELECT h.hearing_id FROM Hearing h
            JOIN LegalCase lc ON lc.case_id = h.case_id
            WHERE h.hearing_date < lc.date_opened
               OR (lc.date_closed IS NOT NULL AND h.hearing_date > lc.date_closed)
        """)
        checks.no_rows("Past hearing outcomes only", """
            SELECT hearing_id FROM Hearing
            WHERE (hearing_date >= ? AND outcome IS NOT NULL)
               OR (hearing_date < ? AND outcome IS NULL)
        """, (str(DATA_AS_OF), str(DATA_AS_OF)))
        checks.no_rows("Document dates and paths", """
            SELECT d.document_id FROM Document d
            JOIN LegalCase lc ON lc.case_id = d.case_id
            WHERE d.date_added < lc.date_opened OR d.date_added > ?
               OR (lc.date_closed IS NOT NULL AND d.date_added > lc.date_closed)
               OR d.file_path NOT LIKE 'documents/%'
        """, (str(DATA_AS_OF),))
        checks.no_rows("Work dates, assignment and hourly rates", """
            SELECT te.time_entry_id FROM TimeEntry te
            JOIN LegalCase lc ON lc.case_id = te.case_id
            JOIN Employee e ON e.employee_id = te.employee_id
            LEFT JOIN CaseAssignment ca
              ON ca.case_id = te.case_id AND ca.employee_id = te.employee_id
            WHERE te.work_date < lc.date_opened
               OR te.work_date > ?
               OR (lc.date_closed IS NOT NULL AND te.work_date > lc.date_closed)
               OR ca.employee_id IS NULL
               OR te.work_date < ca.date_assigned
               OR (ca.date_unassigned IS NOT NULL AND te.work_date >= ca.date_unassigned)
               OR e.hourly_rate IS NULL OR te.hourly_rate <> e.hourly_rate
               OR te.hours <= 0 OR te.hours > 24
        """, (str(DATA_AS_OF),))
        checks.no_rows("Billed entries reference invoices for the same case", """
            SELECT te.time_entry_id FROM TimeEntry te
            LEFT JOIN Invoice i ON i.invoice_id = te.invoice_id
            WHERE (te.billing_status = 'Billed') <> (te.invoice_id IS NOT NULL)
               OR (te.invoice_id IS NOT NULL AND (i.invoice_id IS NULL OR i.case_id <> te.case_id))
        """)
        checks.no_rows("Invoice dates and billed work dates", """
            SELECT i.invoice_id FROM Invoice i
            JOIN LegalCase lc ON lc.case_id = i.case_id
            WHERE i.due_date < i.invoice_date
               OR i.invoice_date < lc.date_opened OR i.invoice_date > ?
               OR (lc.date_closed IS NOT NULL AND i.invoice_date > lc.date_closed)
               OR EXISTS (
                 SELECT 1 FROM TimeEntry te
                 WHERE te.invoice_id = i.invoice_id AND te.work_date > i.invoice_date
               )
        """, (str(DATA_AS_OF),))
        checks.no_rows("Every invoice matches its billed work total", """
            SELECT i.invoice_id FROM Invoice i
            LEFT JOIN TimeEntry te ON te.invoice_id = i.invoice_id
            GROUP BY i.invoice_id
            HAVING COUNT(te.time_entry_id) = 0
                OR ABS(i.total_amount - ROUND(SUM(te.hours * te.hourly_rate), 2)) >= 0.01
        """)
        checks.no_rows("Payments dated correctly and within invoice totals", """
            SELECT i.invoice_id FROM Invoice i
            JOIN LegalCase lc ON lc.case_id = i.case_id
            LEFT JOIN Payment p ON p.invoice_id = i.invoice_id
            GROUP BY i.invoice_id
            HAVING ROUND(COALESCE(SUM(p.amount), 0), 2) > i.total_amount + 0.009
               OR SUM(CASE WHEN p.payment_id IS NOT NULL AND (
                  p.payment_date < i.invoice_date OR p.payment_date > ?
                  OR (lc.date_closed IS NOT NULL AND p.payment_date > lc.date_closed)
               ) THEN 1 ELSE 0 END) > 0
        """, (str(DATA_AS_OF),))
        checks.no_rows("Invoice statuses agree with balances and due dates", """
            SELECT i.invoice_id FROM Invoice i
            LEFT JOIN Payment p ON p.invoice_id = i.invoice_id
            GROUP BY i.invoice_id
            HAVING (i.status = 'Paid') <> (
                 ROUND(COALESCE(SUM(p.amount), 0), 2) >= i.total_amount - 0.009
            ) OR (i.status = 'Draft' AND COUNT(p.payment_id) > 0)
              OR (i.status = 'Overdue' AND i.due_date >= ?)
              OR (i.status = 'Sent' AND i.due_date < ?)
        """, (str(DATA_AS_OF), str(DATA_AS_OF)))

        scenarios = [
            ("An attorney has zero open cases", """
                SELECT COUNT(*) FROM Employee e WHERE e.job_role = 'Attorney' AND NOT EXISTS (
                   SELECT 1 FROM CaseAssignment ca JOIN LegalCase lc ON lc.case_id = ca.case_id
                   WHERE ca.employee_id = e.employee_id AND ca.date_unassigned IS NULL AND lc.status = 'Open')
            """, 1),
            ("Old invoices have unpaid balances", """
                SELECT COUNT(*) FROM Invoice i WHERE i.status <> 'Draft'
                AND date(i.due_date) < date(?, '-30 days')
                AND i.total_amount > (SELECT COALESCE(SUM(p.amount), 0)
                                      FROM Payment p WHERE p.invoice_id = i.invoice_id)
            """, 2),
            ("All practice areas contain billable work", """
                SELECT COUNT(DISTINCT lc.practice_area_id)
                FROM TimeEntry te JOIN LegalCase lc ON lc.case_id = te.case_id
                WHERE te.billing_status IN ('Billed', 'Unbilled')
            """, 4),
            ("Hearings fall inside the reporting window", """
                SELECT COUNT(*) FROM Hearing
                WHERE date(hearing_date) >= date(?)
                  AND date(hearing_date) < date(?, '+14 days')
            """, 4),
            ("Clients have multiple non-draft invoices", """
                SELECT COUNT(*) FROM (
                    SELECT lc.client_id FROM Invoice i JOIN LegalCase lc ON lc.case_id = i.case_id
                    WHERE i.status <> 'Draft' GROUP BY lc.client_id HAVING COUNT(*) > 1)
            """, 3),
        ]
        for label, sql, minimum in scenarios:
            params = (str(REFERENCE_DATE), str(REFERENCE_DATE)) if "reporting window" in label else (
                (str(REFERENCE_DATE),) if "Old invoices" in label else ())
            count = conn.execute(sql, params).fetchone()[0]
            checks.check(label, count >= minimum, f"{count}; expected at least {minimum}")

        resolved_queries = Path(query_path) if query_path is not None else HERE / "queries.sql"
        if resolved_queries.is_file():
            queries = [part.strip() for part in resolved_queries.read_text(encoding="utf-8").split(";") if part.strip()]
            checks.check("Ceionna's query file contains five queries", len(queries) == 5)
            if len(queries) == 5:
                for number, query in enumerate(queries, 1):
                    try:
                        rows = conn.execute(query, {"as_of": str(REFERENCE_DATE)}).fetchall()
                        meaningful = len(rows) >= (4 if number in (1, 3, 4, 5) else 2)
                        if number == 1:
                            meaningful = meaningful and any(row[2] == 0 for row in rows)
                        if number == 3:
                            meaningful = meaningful and all(row[1] > 0 for row in rows)
                        checks.check(f"Ceionna query {number}", meaningful, f"{len(rows)} rows")
                    except sqlite3.Error as error:
                        checks.check(f"Ceionna query {number}", False, str(error))
        else:
            if query_path is not None:
                checks.check("Ceionna query file available", False, str(resolved_queries))
            print("NOTE: queries.sql not present; five data scenarios checked above.")
            print("      Pass --queries path/to/queries.sql to test Ceionna's actual SQL.")
    except (sqlite3.Error, OSError, ValueError) as error:
        checks.check("Verification completed", False, str(error))
    finally:
        conn.close()
    print(f"\n{'ALL CHECKS PASSED' if not checks.failed else f'{checks.failed} CHECK(S) FAILED'}")
    return checks.failed == 0


def main():
    parser = argparse.ArgumentParser(description="Verify the sample law firm database.")
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--queries", type=Path, default=None)
    args = parser.parse_args()
    if not verify_database(args.db, args.queries):
        parser.exit(1)


if __name__ == "__main__":
    main()
