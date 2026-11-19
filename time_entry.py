import math
import sqlite3
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent


def validate_entry(conn, case_id, employee_id, work_date, hours, description):
    parsed_date = date.fromisoformat(work_date)

    if parsed_date.isoformat() != work_date:
        raise ValueError("Use YYYY-MM-DD for the date.")

    if not math.isfinite(hours) or not 0 < hours <= 24:
        raise ValueError("Hours must be greater than 0 and no more than 24.")

    if not description.strip():
        raise ValueError("Enter a description of the work.")

    assignment = conn.execute(
        """
        SELECT e.hourly_rate
        FROM CaseAssignment AS ca
        JOIN Employee AS e ON e.employee_id = ca.employee_id
        WHERE ca.case_id = ?
          AND ca.employee_id = ?
          AND ca.date_assigned <= ?
          AND (
              ca.date_unassigned IS NULL
              OR ca.date_unassigned > ?
          )
        """,
        (case_id, employee_id, work_date, work_date),
    ).fetchone()

    if assignment is None:
        raise ValueError("This employee was not assigned to that case on that date.")

    rate = assignment[0]

    if rate is None or not math.isfinite(rate) or rate < 0:
        raise ValueError("This employee needs a valid billing rate.")

    return rate


def add_entry(conn, case_id, employee_id, work_date, hours, description):
    with conn:
        # Check the assignment and save the entry in one transaction.
        conn.execute("BEGIN IMMEDIATE")
        rate = validate_entry(
            conn, case_id, employee_id, work_date, hours, description
        )
        cursor = conn.execute(
            """
            INSERT INTO TimeEntry (
                case_id, employee_id, work_date, hours,
                hourly_rate, description, billing_status, invoice_id
            )
            VALUES (?, ?, ?, ?, ?, ?, 'Unbilled', NULL)
            """,
            (case_id, employee_id, work_date, hours, rate, description.strip()),
        )
        return cursor.lastrowid


def view_entries(conn):
    rows = conn.execute(
        """
        SELECT
            te.time_entry_id,
            lc.case_title,
            e.first_name || ' ' || e.last_name,
            te.work_date,
            te.hours,
            te.hourly_rate,
            te.description,
            te.billing_status,
            te.invoice_id
        FROM TimeEntry AS te
        JOIN LegalCase AS lc ON lc.case_id = te.case_id
        JOIN Employee AS e ON e.employee_id = te.employee_id
        ORDER BY te.work_date DESC, te.time_entry_id DESC
        """
    ).fetchall()

    if not rows:
        print("\nNo time entries yet.")
        return

    for row in rows:
        entry_id, case, employee, work_date, hours, rate, description, status, invoice = row
        print(f"\nEntry {entry_id} | {case}")
        print(f"Employee: {employee}")
        print(f"Date: {work_date} | Hours: {hours:g} | Rate: ${rate:.2f}")
        print(f"Description: {description}")
        print(f"Status: {status} | Invoice: {invoice if invoice is not None else 'None'}")


def get_unbilled_entry(conn, entry_id):
    row = conn.execute(
        """
        SELECT case_id, employee_id, billing_status, invoice_id
        FROM TimeEntry
        WHERE time_entry_id = ?
        """,
        (entry_id,),
    ).fetchone()

    if row is None:
        raise ValueError("That time entry does not exist.")

    if row[2] != "Unbilled" or row[3] is not None:
        raise ValueError("Only unbilled entries without an invoice can be changed.")

    return row


def edit_entry(conn, entry_id, work_date, hours, description):
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        row = get_unbilled_entry(conn, entry_id)
        validate_entry(conn, row[0], row[1], work_date, hours, description)

        # Keep the rate that was saved with the original entry.
        conn.execute(
            """
            UPDATE TimeEntry
            SET work_date = ?, hours = ?, description = ?
            WHERE time_entry_id = ?
              AND billing_status = 'Unbilled'
              AND invoice_id IS NULL
            """,
            (work_date, hours, description.strip(), entry_id),
        )


def delete_entry(conn, entry_id):
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        get_unbilled_entry(conn, entry_id)
        conn.execute(
            """
            DELETE FROM TimeEntry
            WHERE time_entry_id = ?
              AND billing_status = 'Unbilled'
              AND invoice_id IS NULL
            """,
            (entry_id,),
        )


def read_work_details():
    work_date = input("Work date (YYYY-MM-DD): ").strip()
    hours = float(input("Hours worked: ").strip())
    description = input("Work description: ").strip()
    return work_date, hours, description


def time_entry_menu(conn):
    conn.execute("PRAGMA foreign_keys = ON")

    while True:
        print("\nTime Entry")
        print("1. Add time entry")
        print("2. View time entries")
        print("3. Edit unbilled time entry")
        print("4. Delete unbilled time entry")
        print("0. Return")

        try:
            choice = input("Choose an option: ").strip()

            if choice == "0":
                return

            if choice == "1":
                case_id = int(input("Case ID: ").strip())
                employee_id = int(input("Employee ID: ").strip())
                work_date, hours, description = read_work_details()
                entry_id = add_entry(
                    conn, case_id, employee_id, work_date, hours, description
                )
                print(f"Time entry {entry_id} added.")

            elif choice == "2":
                view_entries(conn)

            elif choice == "3":
                entry_id = int(input("Time entry ID: ").strip())
                get_unbilled_entry(conn, entry_id)
                work_date, hours, description = read_work_details()
                edit_entry(conn, entry_id, work_date, hours, description)
                print("Time entry updated.")

            elif choice == "4":
                entry_id = int(input("Time entry ID: ").strip())
                get_unbilled_entry(conn, entry_id)
                confirm = input("Delete this entry? (y/n): ").strip().lower()

                if confirm == "y":
                    delete_entry(conn, entry_id)
                    print("Time entry deleted.")
                else:
                    print("Deletion canceled.")

            else:
                print("Choose 0, 1, 2, 3, or 4.")

        except ValueError as error:
            print(f"Check your input: {error}")
        except sqlite3.Error as error:
            print(f"Database error: {error}")
        except (EOFError, KeyboardInterrupt):
            print("\nReturning from time entry.")
            return


def main():
    conn = None

    try:
        database_uri = (HERE / "bayou.db").as_uri() + "?mode=rw"
        conn = sqlite3.connect(database_uri, timeout=10)
        conn.execute("PRAGMA foreign_keys = ON")
        time_entry_menu(conn)
    except sqlite3.Error as error:
        print(f"Could not open the database: {error}")
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
