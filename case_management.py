"""Case management (Person 3): open cases, assign attorneys, view, update, close, unassign.

Main menu entry point: case_menu(conn)
Run on its own:        python case_management.py

Business rules enforced here (team plan, "Rule / Where to enforce it"):
  * A case is opened together with its Lead attorney, so it always has at least
    one assigned employee.
  * Only active attorneys are assigned (they are the employees with billing rates,
    which time entries need).
  * One active Lead per case. Changing the Lead demotes the old Lead to Associate.
  * Removing an assignment sets date_unassigned instead of deleting the row, so
    hours already logged keep their history.
  * Closing sets status = 'Closed' and date_closed together (matches the schema CHECK).
"""
import re
import sqlite3
from contextlib import contextmanager
from datetime import date

from db_connection import get_connection

OPEN_STATUSES = ("Open", "Pending")
ROLES = ("Lead", "Associate", "Consulting")


@contextmanager
def record_change(conn):
    # Same pattern as the other modules: all-or-nothing, and it never commits
    # a transaction the main menu already owns.
    conn.execute("SAVEPOINT case_change")
    try:
        yield
        conn.execute("RELEASE SAVEPOINT case_change")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT case_change")
        conn.execute("RELEASE SAVEPOINT case_change")
        raise


# ---------- validation ----------

def valid_date(value, label="Date"):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{label}: use YYYY-MM-DD.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label}: enter a real calendar date.") from None
    if parsed > date.today():
        raise ValueError(f"{label} cannot be in the future.")
    return value


def required_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} cannot be blank.")
    return value.strip()


def require_client(conn, client_id):
    if conn.execute("SELECT 1 FROM Client WHERE client_id = ?", (client_id,)).fetchone() is None:
        raise ValueError(f"Client {client_id} does not exist.")


def require_practice_area(conn, practice_area_id):
    if conn.execute("SELECT 1 FROM PracticeArea WHERE practice_area_id = ?",
                    (practice_area_id,)).fetchone() is None:
        raise ValueError(f"Practice area {practice_area_id} does not exist.")


def require_attorney(conn, employee_id):
    row = conn.execute(
        "SELECT job_role, is_active, hourly_rate FROM Employee WHERE employee_id = ?",
        (employee_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Employee {employee_id} does not exist.")
    if row["job_role"] != "Attorney":
        raise ValueError(f"Employee {employee_id} is a {row['job_role']}, not an attorney.")
    if row["is_active"] != "TRUE":
        raise ValueError(f"Attorney {employee_id} is no longer active.")
    if row["hourly_rate"] is None:
        raise ValueError(f"Attorney {employee_id} has no hourly rate on file.")


def get_case(conn, case_id):
    row = conn.execute(
        """SELECT lc.*, c.first_name || ' ' || c.last_name AS client_name, pa.area_name
           FROM LegalCase AS lc
           JOIN Client AS c ON c.client_id = lc.client_id
           JOIN PracticeArea AS pa ON pa.practice_area_id = lc.practice_area_id
           WHERE lc.case_id = ?""",
        (case_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Case {case_id} does not exist.")
    return row


def require_not_closed(case):
    if case["status"] == "Closed":
        raise ValueError(f"Case {case['case_id']} is closed. Reopen it first.")


def active_assignment(conn, case_id, employee_id):
    return conn.execute(
        """SELECT * FROM CaseAssignment
           WHERE case_id = ? AND employee_id = ? AND date_unassigned IS NULL""",
        (case_id, employee_id),
    ).fetchone()


def active_lead(conn, case_id):
    return conn.execute(
        """SELECT employee_id FROM CaseAssignment
           WHERE case_id = ? AND case_role = 'Lead' AND date_unassigned IS NULL""",
        (case_id,),
    ).fetchone()


# ---------- data functions ----------

def open_case(conn, client_id, practice_area_id, case_title, description,
              lead_attorney_id, date_opened=None, status="Open"):
    """Insert the case and its Lead assignment in one step. Returns the new case_id."""
    date_opened = valid_date(date_opened or date.today().isoformat(), "Date opened")
    if status not in OPEN_STATUSES:
        raise ValueError("A new case must start as Open or Pending.")
    case_title = required_text(case_title, "Case title")
    description = required_text(description, "Description")
    require_client(conn, client_id)
    require_practice_area(conn, practice_area_id)
    require_attorney(conn, lead_attorney_id)
    with record_change(conn):
        cursor = conn.execute(
            """INSERT INTO LegalCase (case_title, description, status, date_opened,
                                      client_id, practice_area_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (case_title, description, status, date_opened, client_id, practice_area_id),
        )
        case_id = cursor.lastrowid
        conn.execute(
            """INSERT INTO CaseAssignment (case_id, employee_id, case_role, date_assigned)
               VALUES (?, ?, 'Lead', ?)""",
            (case_id, lead_attorney_id, date_opened),
        )
    return case_id


def assign_attorney(conn, case_id, employee_id, case_role="Associate", date_assigned=None):
    case = get_case(conn, case_id)
    require_not_closed(case)
    require_attorney(conn, employee_id)
    if case_role not in ROLES:
        raise ValueError(f"Role must be one of: {', '.join(ROLES)}.")
    date_assigned = valid_date(date_assigned or date.today().isoformat(), "Date assigned")
    if date_assigned < case["date_opened"]:
        raise ValueError("Assignment date cannot be before the case opened.")
    if active_assignment(conn, case_id, employee_id):
        raise ValueError(f"Attorney {employee_id} is already assigned to case {case_id}.")
    if case_role == "Lead" and active_lead(conn, case_id):
        raise ValueError("This case already has a Lead. Use 'Change Lead attorney' instead.")
    previous = conn.execute(
        "SELECT date_unassigned FROM CaseAssignment WHERE case_id = ? AND employee_id = ?",
        (case_id, employee_id),
    ).fetchone()
    with record_change(conn):
        if previous is None:
            conn.execute(
                """INSERT INTO CaseAssignment (case_id, employee_id, case_role, date_assigned)
                   VALUES (?, ?, ?, ?)""",
                (case_id, employee_id, case_role, date_assigned),
            )
        else:
            # The key is (case_id, employee_id), so a returning attorney reuses the row.
            if date_assigned < previous["date_unassigned"]:
                raise ValueError("Reassignment date cannot be before the earlier unassignment.")
            conn.execute(
                """UPDATE CaseAssignment
                   SET case_role = ?, date_assigned = ?, date_unassigned = NULL
                   WHERE case_id = ? AND employee_id = ?""",
                (case_role, date_assigned, case_id, employee_id),
            )


def change_lead(conn, case_id, new_lead_id):
    """Make an attorney already on the case the Lead; the old Lead becomes an Associate."""
    case = get_case(conn, case_id)
    require_not_closed(case)
    if not active_assignment(conn, case_id, new_lead_id):
        raise ValueError(f"Attorney {new_lead_id} is not assigned to this case. Assign them first.")
    old = active_lead(conn, case_id)
    if old and old["employee_id"] == new_lead_id:
        raise ValueError(f"Attorney {new_lead_id} is already the Lead.")
    with record_change(conn):
        if old:
            conn.execute(
                """UPDATE CaseAssignment SET case_role = 'Associate'
                   WHERE case_id = ? AND employee_id = ?""",
                (case_id, old["employee_id"]),
            )
        conn.execute(
            "UPDATE CaseAssignment SET case_role = 'Lead' WHERE case_id = ? AND employee_id = ?",
            (case_id, new_lead_id),
        )


def unassign_attorney(conn, case_id, employee_id, date_unassigned=None):
    """End an assignment by dating it. The row stays for history and billing."""
    case = get_case(conn, case_id)
    require_not_closed(case)
    current = active_assignment(conn, case_id, employee_id)
    if current is None:
        raise ValueError(f"Attorney {employee_id} is not currently assigned to case {case_id}.")
    if current["case_role"] == "Lead":
        raise ValueError("Cannot remove the Lead. Change the Lead attorney first.")
    date_unassigned = valid_date(date_unassigned or date.today().isoformat(), "Date unassigned")
    if date_unassigned < current["date_assigned"]:
        raise ValueError("Unassignment date cannot be before the assignment date.")
    last_work = conn.execute(
        "SELECT MAX(work_date) FROM TimeEntry WHERE case_id = ? AND employee_id = ?",
        (case_id, employee_id),
    ).fetchone()[0]
    if last_work is not None and date_unassigned <= last_work:
        raise ValueError(f"This attorney logged time on {last_work}; unassign after that date.")
    with record_change(conn):
        conn.execute(
            """UPDATE CaseAssignment SET date_unassigned = ?
               WHERE case_id = ? AND employee_id = ?""",
            (date_unassigned, case_id, employee_id),
        )


def update_case(conn, case_id, case_title=None, description=None,
                practice_area_id=None, status=None):
    """Edit details or move between Open and Pending. None keeps the current value."""
    case = get_case(conn, case_id)
    require_not_closed(case)
    case_title = case["case_title"] if case_title is None else required_text(case_title, "Case title")
    description = case["description"] if description is None else required_text(description, "Description")
    practice_area_id = case["practice_area_id"] if practice_area_id is None else practice_area_id
    status = case["status"] if status is None else status
    if status not in OPEN_STATUSES:
        raise ValueError("Status can be Open or Pending here. Use 'Close case' to close it.")
    require_practice_area(conn, practice_area_id)
    with record_change(conn):
        conn.execute(
            """UPDATE LegalCase SET case_title = ?, description = ?, practice_area_id = ?, status = ?
               WHERE case_id = ?""",
            (case_title, description, practice_area_id, status, case_id),
        )


def close_case(conn, case_id, date_closed=None):
    case = get_case(conn, case_id)
    require_not_closed(case)
    date_closed = valid_date(date_closed or date.today().isoformat(), "Date closed")
    if date_closed < case["date_opened"]:
        raise ValueError("Close date cannot be before the case opened.")
    with record_change(conn):
        conn.execute(
            "UPDATE LegalCase SET status = 'Closed', date_closed = ? WHERE case_id = ?",
            (date_closed, case_id),
        )


def reopen_case(conn, case_id):
    case = get_case(conn, case_id)
    if case["status"] != "Closed":
        raise ValueError(f"Case {case_id} is not closed.")
    if not active_lead(conn, case_id):
        raise ValueError("This case has no active Lead attorney, so it cannot be reopened.")
    with record_change(conn):
        conn.execute(
            "UPDATE LegalCase SET status = 'Open', date_closed = NULL WHERE case_id = ?",
            (case_id,),
        )


def list_cases(conn, status=None, client_id=None):
    return conn.execute(
        """SELECT lc.case_id, lc.case_title, lc.status, lc.date_opened,
                  c.first_name || ' ' || c.last_name AS client_name, pa.area_name,
                  (SELECT e.first_name || ' ' || e.last_name
                     FROM CaseAssignment ca JOIN Employee e ON e.employee_id = ca.employee_id
                    WHERE ca.case_id = lc.case_id AND ca.case_role = 'Lead'
                      AND ca.date_unassigned IS NULL) AS lead_name
           FROM LegalCase AS lc
           JOIN Client AS c ON c.client_id = lc.client_id
           JOIN PracticeArea AS pa ON pa.practice_area_id = lc.practice_area_id
           WHERE (? IS NULL OR lc.status = ?) AND (? IS NULL OR lc.client_id = ?)
           ORDER BY lc.case_id""",
        (status, status, client_id, client_id),
    ).fetchall()


def case_assignments(conn, case_id):
    return conn.execute(
        """SELECT ca.employee_id, e.first_name || ' ' || e.last_name AS name, ca.case_role,
                  ca.date_assigned, ca.date_unassigned
           FROM CaseAssignment AS ca
           JOIN Employee AS e ON e.employee_id = ca.employee_id
           WHERE ca.case_id = ?
           ORDER BY ca.date_unassigned IS NOT NULL,
                    CASE ca.case_role WHEN 'Lead' THEN 0 WHEN 'Associate' THEN 1 ELSE 2 END""",
        (case_id,),
    ).fetchall()


def case_activity(conn, case_id):
    return conn.execute(
        """SELECT (SELECT COUNT(*) FROM Hearing WHERE case_id = ?) AS hearings,
                  (SELECT COUNT(*) FROM Document WHERE case_id = ?) AS documents,
                  (SELECT COUNT(*) FROM TimeEntry WHERE case_id = ?) AS time_entries,
                  (SELECT COALESCE(SUM(hours), 0) FROM TimeEntry WHERE case_id = ?) AS hours,
                  (SELECT COUNT(*) FROM Invoice WHERE case_id = ?) AS invoices""",
        (case_id,) * 5,
    ).fetchone()


# ---------- prompts ----------

def ask(label, current=None, optional=False):
    prompt = f"{label} [{current}]: " if current is not None else f"{label}: "
    while True:
        text = input(prompt).strip()
        if text:
            return text
        if current is not None or optional:
            return None
        print("This field cannot be blank.")


def ask_id(label, keep=False):
    while True:
        text = input(f"{label}{' (Enter to keep)' if keep else ''}: ").strip()
        if keep and not text:
            return None
        if text.isdigit() and int(text) > 0:
            return int(text)
        print("Enter a positive whole-number ID.")


def ask_choice(label, options, keep=False):
    print(f"Options: {', '.join(options)}")
    while True:
        text = input(f"{label}{' (Enter to keep)' if keep else ''}: ").strip()
        if keep and not text:
            return None
        for option in options:
            if text.lower() == option.lower():
                return option
        print("Choose one of the listed options.")


def ask_date(label):
    text = input(f"{label} (YYYY-MM-DD, Enter for today): ").strip()
    return text or None


def print_practice_areas(conn):
    rows = conn.execute("SELECT practice_area_id, area_name FROM PracticeArea ORDER BY 1").fetchall()
    print("Practice areas: " + ", ".join(f"{r[0]}={r[1]}" for r in rows))


def print_attorneys(conn):
    rows = conn.execute(
        """SELECT e.employee_id, e.first_name || ' ' || e.last_name AS name,
                  (SELECT COUNT(*) FROM CaseAssignment ca JOIN LegalCase lc ON lc.case_id = ca.case_id
                    WHERE ca.employee_id = e.employee_id AND ca.date_unassigned IS NULL
                      AND lc.status <> 'Closed') AS open_cases
           FROM Employee e
           WHERE e.job_role = 'Attorney' AND e.is_active = 'TRUE'
           ORDER BY e.employee_id"""
    ).fetchall()
    print("Active attorneys:")
    for r in rows:
        print(f"  {r['employee_id']:>3}  {r['name']:<24} {r['open_cases']} open case(s)")


def show_case(conn, case_id):
    c = get_case(conn, case_id)
    print(f"\nCase {c['case_id']}: {c['case_title']}")
    print(f"  Client: {c['client_name']} (client {c['client_id']})   Area: {c['area_name']}")
    closed = f", closed {c['date_closed']}" if c["date_closed"] else ""
    print(f"  Status: {c['status']} (opened {c['date_opened']}{closed})")
    print(f"  Description: {c['description']}")
    print("  Team:")
    for a in case_assignments(conn, case_id):
        until = f" to {a['date_unassigned']} (removed)" if a["date_unassigned"] else ""
        print(f"    {a['employee_id']:>3} {a['name']:<24} {a['case_role']:<11} from {a['date_assigned']}{until}")
    act = case_activity(conn, case_id)
    print(f"  Activity: {act['hearings']} hearing(s), {act['documents']} document(s), "
          f"{act['time_entries']} time entries ({act['hours']:g} h), {act['invoices']} invoice(s)")


def menu_open(conn):
    client_id = ask_id("Client ID")
    require_client(conn, client_id)
    print_practice_areas(conn)
    area = ask_id("Practice area ID")
    print_attorneys(conn)
    case_id = open_case(
        conn, client_id, area,
        case_title=ask("Case title"),
        description=ask("Description"),
        lead_attorney_id=ask_id("Lead attorney employee ID"),
        date_opened=ask_date("Date opened"),
        status=ask_choice("Starting status", OPEN_STATUSES),
    )
    print(f"Case {case_id} opened with its Lead attorney assigned.")


def menu_list(conn):
    scope = input("Show open/pending (o), closed (c), all (a), or by client (k)? ").strip().lower()
    if scope == "k":
        rows = list_cases(conn, client_id=ask_id("Client ID"))
    elif scope in ("o", "c", "a"):
        rows = list_cases(conn, status="Closed" if scope == "c" else None)
        if scope == "o":
            rows = [r for r in rows if r["status"] != "Closed"]
    else:
        print("Choose o, c, a, or k.")
        return
    if not rows:
        print("No cases found.")
        return
    print(f"\n{'ID':>4}  {'Title':<34} {'Status':<8} {'Client':<22} {'Lead':<22}")
    for r in rows:
        print(f"{r['case_id']:>4}  {r['case_title'][:34]:<34} {r['status']:<8} "
              f"{r['client_name'][:22]:<22} {(r['lead_name'] or '-')[:22]:<22}")


def menu_update(conn):
    case_id = ask_id("Case ID")
    c = get_case(conn, case_id)
    print("Press Enter to keep the current value.")
    print_practice_areas(conn)
    update_case(
        conn, case_id,
        case_title=ask("Case title", c["case_title"]),
        description=ask("Description", c["description"]),
        practice_area_id=ask_id("Practice area ID", keep=True),
        status=ask_choice(f"Status [{c['status']}]", OPEN_STATUSES, keep=True),
    )
    print("Case updated.")


def menu_assign(conn):
    case_id = ask_id("Case ID")
    print_attorneys(conn)
    assign_attorney(
        conn, case_id, ask_id("Attorney employee ID"),
        case_role=ask_choice("Role", ("Associate", "Consulting")),
        date_assigned=ask_date("Date assigned"),
    )
    print("Attorney assigned.")


def menu_change_lead(conn):
    case_id = ask_id("Case ID")
    show_case(conn, case_id)
    change_lead(conn, case_id, ask_id("New Lead (must already be on the case)"))
    print("Lead attorney changed; the previous Lead is now an Associate.")


def menu_unassign(conn):
    case_id = ask_id("Case ID")
    show_case(conn, case_id)
    employee_id = ask_id("Attorney to remove")
    when = ask_date("Date unassigned")
    if input("Remove this attorney from the case? (y/n): ").strip().lower() == "y":
        unassign_attorney(conn, case_id, employee_id, when)
        print("Assignment ended (kept on record with an end date).")
    else:
        print("Canceled.")


def menu_close(conn):
    case_id = ask_id("Case ID")
    show_case(conn, case_id)
    when = ask_date("Date closed")
    if input("Close this case? (y/n): ").strip().lower() == "y":
        close_case(conn, case_id, when)
        print("Case closed.")
    else:
        print("Canceled.")


def menu_reopen(conn):
    case_id = ask_id("Case ID")
    reopen_case(conn, case_id)
    print("Case reopened as Open.")


def case_menu(conn):
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    actions = {
        "1": menu_open,
        "2": menu_list,
        "3": lambda c: show_case(c, ask_id("Case ID")),
        "4": menu_update,
        "5": menu_assign,
        "6": menu_change_lead,
        "7": menu_unassign,
        "8": menu_close,
        "9": menu_reopen,
    }
    while True:
        print("\nCase Management")
        print("1. Open a new case")
        print("2. List cases")
        print("3. View case details")
        print("4. Update case details / status")
        print("5. Assign an attorney")
        print("6. Change Lead attorney")
        print("7. Remove an attorney assignment")
        print("8. Close a case")
        print("9. Reopen a closed case")
        print("0. Return")
        try:
            choice = input("Choose an option: ").strip()
            if choice == "0":
                return
            if choice in actions:
                actions[choice](conn)
            else:
                print("Choose a number from 0 through 9.")
        except ValueError as error:
            print(f"Check your input: {error}")
        except sqlite3.IntegrityError as error:
            print(f"Cannot save that record: {error}")
        except sqlite3.Error as error:
            print(f"Database error: {error}")
        except (EOFError, KeyboardInterrupt):
            print("\nReturning from case management.")
            return


if __name__ == "__main__":
    connection = get_connection()
    try:
        case_menu(connection)
    finally:
        connection.close()
