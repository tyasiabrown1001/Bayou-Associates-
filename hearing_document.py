import argparse
from contextlib import contextmanager
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "bayou.db"
HEARING_OUTCOMES = ("Continued", "Granted", "Denied", "Settled", "Dismissed")
DOCUMENT_TYPES = ("Pleading", "Contract", "Evidence", "Correspondence")
KEEP = object()

# TODO (Brandon): confirm the shared DB helper name and connection contract when available.
try:
    from db_connection import get_connection
except ImportError:
    get_connection = None


def ensure_foreign_keys(conn):
    conn.execute("PRAGMA foreign_keys = ON")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise sqlite3.OperationalError("Enable foreign keys before starting a transaction.")


def open_connection(db_path=DB):
    if get_connection is not None and Path(db_path).resolve() == DB.resolve():
        conn = get_connection()
    else:
        # Drop this fallback once Brandon's shared connection helper is available.
        uri = Path(db_path).resolve().as_uri() + "?mode=rw"
        conn = sqlite3.connect(uri, timeout=10, uri=True)
    ensure_foreign_keys(conn)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def record_change(conn):
    # A savepoint preserves any pending transaction owned by the calling main menu.
    conn.execute("SAVEPOINT person4_record")
    try:
        yield
        conn.execute("RELEASE SAVEPOINT person4_record")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT person4_record")
        conn.execute("RELEASE SAVEPOINT person4_record")
        raise


def valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Use YYYY-MM-DD for the date.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Enter a valid calendar date.") from None
    if parsed.isoformat() != value:
        raise ValueError("Use YYYY-MM-DD for the date.")
    return parsed


def valid_time(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}", value):
        raise ValueError("Use HH:MM (24-hour time).")
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError:
        raise ValueError("Enter a valid 24-hour time.") from None
    return value


def positive_id(value, label):
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} must be a positive number.")
    return value


def require_record(conn, table, key, record_id):
    # Names here are fixed by the application, not supplied by users.
    allowed = {"LegalCase": "case_id", "Court": "court_id", "Employee": "employee_id"}
    if allowed.get(table) != key:
        raise ValueError("Unknown record type.")
    statements = {
        "LegalCase": "SELECT 1 FROM LegalCase WHERE case_id = ?",
        "Court": "SELECT 1 FROM Court WHERE court_id = ?",
        "Employee": "SELECT 1 FROM Employee WHERE employee_id = ?",
    }
    row = conn.execute(statements[table], (record_id,)).fetchone()
    if row is None:
        raise ValueError(f"{table} record {record_id} does not exist.")


def case_date_check(conn, case_id, when):
    positive_id(case_id, "Case ID")
    row = conn.execute(
        "SELECT date_opened, date_closed FROM LegalCase WHERE case_id = ?", (case_id,)
    ).fetchone()
    if row is None:
        raise ValueError("That case does not exist.")
    if when < row[0]:
        raise ValueError("Date cannot be before the case opened.")
    if row[1] is not None and when > row[1]:
        raise ValueError("Date cannot be after the case closed.")


def validate_hearing(conn, case_id, court_id, hearing_date, hearing_time, purpose, outcome):
    valid_date(hearing_date)
    valid_time(hearing_time)
    case_date_check(conn, case_id, hearing_date)
    positive_id(court_id, "Court ID")
    require_record(conn, "Court", "court_id", court_id)
    if not isinstance(purpose, str) or not purpose.strip():
        raise ValueError("Enter a hearing purpose.")
    if outcome is not None and outcome not in HEARING_OUTCOMES:
        raise ValueError("Choose a valid hearing outcome.")
    if outcome is not None and valid_date(hearing_date) > date.today():
        raise ValueError("A future hearing cannot have an outcome yet.")


def validate_document(conn, case_id, uploaded_by, title, doc_type, date_added, file_path):
    valid_date(date_added)
    case_date_check(conn, case_id, date_added)
    positive_id(uploaded_by, "Employee ID")
    require_record(conn, "Employee", "employee_id", uploaded_by)
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Enter a document title.")
    if doc_type not in DOCUMENT_TYPES:
        raise ValueError("Choose a valid document type.")
    if not isinstance(file_path, str) or not file_path.strip():
        raise ValueError("Enter a file path.")
    if valid_date(date_added) > date.today():
        raise ValueError("A document cannot be recorded before it is added.")


def add_hearing(conn, case_id, court_id, hearing_date, hearing_time, purpose, outcome=None):
    validate_hearing(conn, case_id, court_id, hearing_date, hearing_time, purpose, outcome)
    with record_change(conn):
        cursor = conn.execute(
            """INSERT INTO Hearing (case_id, court_id, hearing_date, hearing_time, purpose, outcome)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (case_id, court_id, hearing_date, hearing_time, purpose.strip(), outcome),
        )
    return cursor.lastrowid


def list_hearings(conn, case_id=None):
    if case_id is not None:
        positive_id(case_id, "Case ID")
    return conn.execute(
        """SELECT h.hearing_id, h.case_id, lc.case_title, h.court_id, c.court_name,
                  h.hearing_date, h.hearing_time, h.purpose, h.outcome
           FROM Hearing AS h
           JOIN LegalCase AS lc ON lc.case_id = h.case_id
           JOIN Court AS c ON c.court_id = h.court_id
           WHERE (? IS NULL OR h.case_id = ?)
           ORDER BY h.hearing_date, h.hearing_time, h.hearing_id""",
        (case_id, case_id),
    ).fetchall()


def get_hearing(conn, hearing_id):
    positive_id(hearing_id, "Hearing ID")
    row = conn.execute(
        """SELECT h.hearing_id, h.case_id, lc.case_title, h.court_id, c.court_name,
                  h.hearing_date, h.hearing_time, h.purpose, h.outcome
           FROM Hearing AS h
           JOIN LegalCase AS lc ON lc.case_id = h.case_id
           JOIN Court AS c ON c.court_id = h.court_id
           WHERE h.hearing_id = ?""", (hearing_id,)
    ).fetchone()
    if row is None:
        raise ValueError("That hearing does not exist.")
    return row


def update_hearing(conn, hearing_id, case_id=None, court_id=None, hearing_date=None,
                   hearing_time=None, purpose=None, outcome=KEEP):
    old = get_hearing(conn, hearing_id)
    case_id = old["case_id"] if case_id is None else case_id
    court_id = old["court_id"] if court_id is None else court_id
    hearing_date = old["hearing_date"] if hearing_date is None else hearing_date
    hearing_time = old["hearing_time"] if hearing_time is None else hearing_time
    purpose = old["purpose"] if purpose is None else purpose
    outcome = old["outcome"] if outcome is KEEP else outcome
    validate_hearing(conn, case_id, court_id, hearing_date, hearing_time, purpose, outcome)
    with record_change(conn):
        conn.execute(
            """UPDATE Hearing SET case_id = ?, court_id = ?, hearing_date = ?,
                  hearing_time = ?, purpose = ?, outcome = ? WHERE hearing_id = ?""",
            (case_id, court_id, hearing_date, hearing_time, purpose.strip(), outcome, hearing_id),
        )


def delete_hearing(conn, hearing_id):
    get_hearing(conn, hearing_id)
    with record_change(conn):
        conn.execute("DELETE FROM Hearing WHERE hearing_id = ?", (hearing_id,))


def add_document(conn, case_id, uploaded_by, title, doc_type, date_added, file_path):
    validate_document(conn, case_id, uploaded_by, title, doc_type, date_added, file_path)
    with record_change(conn):
        cursor = conn.execute(
            """INSERT INTO Document (case_id, uploaded_by, title, doc_type, date_added, file_path)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (case_id, uploaded_by, title.strip(), doc_type, date_added, file_path.strip()),
        )
    return cursor.lastrowid


def list_documents(conn, case_id=None):
    if case_id is not None:
        positive_id(case_id, "Case ID")
    return conn.execute(
        """SELECT d.document_id, d.case_id, lc.case_title, d.uploaded_by,
                  e.first_name || ' ' || e.last_name AS uploader,
                  d.title, d.doc_type, d.date_added, d.file_path
           FROM Document AS d
           JOIN LegalCase AS lc ON lc.case_id = d.case_id
           JOIN Employee AS e ON e.employee_id = d.uploaded_by
           WHERE (? IS NULL OR d.case_id = ?)
           ORDER BY d.date_added DESC, d.document_id DESC""",
        (case_id, case_id),
    ).fetchall()


def get_document(conn, document_id):
    positive_id(document_id, "Document ID")
    row = conn.execute(
        """SELECT d.document_id, d.case_id, lc.case_title, d.uploaded_by,
                  e.first_name || ' ' || e.last_name AS uploader,
                  d.title, d.doc_type, d.date_added, d.file_path
           FROM Document AS d
           JOIN LegalCase AS lc ON lc.case_id = d.case_id
           JOIN Employee AS e ON e.employee_id = d.uploaded_by
           WHERE d.document_id = ?""", (document_id,)
    ).fetchone()
    if row is None:
        raise ValueError("That document does not exist.")
    return row


def update_document(conn, document_id, case_id=None, uploaded_by=None, title=None,
                    doc_type=None, date_added=None, file_path=None):
    old = get_document(conn, document_id)
    case_id = old["case_id"] if case_id is None else case_id
    uploaded_by = old["uploaded_by"] if uploaded_by is None else uploaded_by
    title = old["title"] if title is None else title
    doc_type = old["doc_type"] if doc_type is None else doc_type
    date_added = old["date_added"] if date_added is None else date_added
    file_path = old["file_path"] if file_path is None else file_path
    validate_document(conn, case_id, uploaded_by, title, doc_type, date_added, file_path)
    with record_change(conn):
        conn.execute(
            """UPDATE Document SET case_id = ?, uploaded_by = ?, title = ?,
                  doc_type = ?, date_added = ?, file_path = ? WHERE document_id = ?""",
            (case_id, uploaded_by, title.strip(), doc_type, date_added,
             file_path.strip(), document_id),
        )


def delete_document(conn, document_id):
    get_document(conn, document_id)
    with record_change(conn):
        conn.execute("DELETE FROM Document WHERE document_id = ?", (document_id,))


def ask_id(label, allow_keep=False):
    while True:
        text = input(f"{label}{' (Enter to keep)' if allow_keep else ''}: ").strip()
        if allow_keep and not text:
            return None
        try:
            value = int(text)
            positive_id(value, label)
            return value
        except ValueError:
            print("Enter a positive whole-number ID.")


def ask_text(label, old=None):
    while True:
        entry = input(f"{label}{f' [{old}]' if old is not None else ''}: ").strip()
        if entry:
            return entry
        if old is not None:
            return old
        print("This field cannot be blank.")


def ask_date(label, old=None):
    while True:
        value = input(f"{label} (YYYY-MM-DD){f' [{old}]' if old else ''}: ").strip()
        if not value and old is not None:
            return old
        try:
            valid_date(value)
            return value
        except ValueError as error:
            print(f"Check your input: {error}")


def ask_time(label, old=None):
    while True:
        value = input(f"{label} (HH:MM){f' [{old}]' if old else ''}: ").strip()
        if not value and old is not None:
            return old
        try:
            valid_time(value)
            return value
        except ValueError as error:
            print(f"Check your input: {error}")


def ask_enum(label, allowed, optional=False, old=KEEP):
    print(f"Options: {', '.join(allowed)}")
    while True:
        raw = input(f"{label}: ").strip()
        if old is not KEEP and not raw:
            return old
        if optional and (raw.lower() in ("none", "clear") or (old is KEEP and not raw)):
            return None
        for item in allowed:
            if raw.lower() == item.lower():
                return item
        print("Choose one of the listed options" + (" (or 'clear')." if optional else "."))


def show_hearing(row):
    print(f"\nHearing {row['hearing_id']} | {row['case_title']} (case {row['case_id']})")
    print(f"Court: {row['court_name']} | {row['hearing_date']} {row['hearing_time']}")
    print(f"Purpose: {row['purpose']} | Outcome: {row['outcome'] or 'Pending'}")


def show_document(row):
    print(f"\nDocument {row['document_id']} | {row['title']} ({row['doc_type']})")
    print(f"Case: {row['case_title']} (case {row['case_id']})")
    print(f"Uploaded by: {row['uploader']} | Date: {row['date_added']}")
    print(f"Path: {row['file_path']}")


def hearing_actions(conn, choice):
    if choice == "1":
        record_id = add_hearing(
            conn, ask_id("Case ID"), ask_id("Court ID"), ask_date("Hearing date"),
            ask_time("Hearing time"), ask_text("Purpose"),
            ask_enum("Outcome (blank for pending)", HEARING_OUTCOMES, optional=True),
        )
        print(f"Hearing {record_id} added.")
    elif choice == "2":
        scope = input("Show all (a), by case (c), or one detail (d)? ").strip().lower()
        if scope == "d":
            show_hearing(get_hearing(conn, ask_id("Hearing ID")))
        elif scope in ("a", "c"):
            rows = list_hearings(conn, ask_id("Case ID") if scope == "c" else None)
            if not rows:
                print("No hearings found.")
            for row in rows:
                show_hearing(row)
        else:
            print("Choose a, c, or d.")
    elif choice == "3":
        record_id = ask_id("Hearing ID")
        old = get_hearing(conn, record_id)
        print("Press Enter to keep a value. Type 'clear' to remove the outcome.")
        update_hearing(
            conn, record_id,
            case_id=ask_id("Case ID", allow_keep=True),
            court_id=ask_id("Court ID", allow_keep=True),
            hearing_date=ask_date("Hearing date", old["hearing_date"]),
            hearing_time=ask_time("Hearing time", old["hearing_time"]),
            purpose=ask_text("Purpose", old["purpose"]),
            outcome=ask_enum("Outcome", HEARING_OUTCOMES, optional=True, old=old["outcome"]),
        )
        print("Hearing updated.")
    elif choice == "4":
        record_id = ask_id("Hearing ID")
        show_hearing(get_hearing(conn, record_id))
        if input("Delete this hearing? (y/n): ").strip().lower() == "y":
            delete_hearing(conn, record_id)
            print("Hearing deleted.")
        else:
            print("Deletion canceled.")


def document_actions(conn, choice):
    if choice == "5":
        record_id = add_document(
            conn, ask_id("Case ID"), ask_id("Uploader employee ID"),
            ask_text("Title"), ask_enum("Document type", DOCUMENT_TYPES),
            ask_date("Date added"), ask_text("File path"),
        )
        print(f"Document {record_id} added.")
    elif choice == "6":
        scope = input("Show all (a), by case (c), or one detail (d)? ").strip().lower()
        if scope == "d":
            show_document(get_document(conn, ask_id("Document ID")))
        elif scope in ("a", "c"):
            rows = list_documents(conn, ask_id("Case ID") if scope == "c" else None)
            if not rows:
                print("No documents found.")
            for row in rows:
                show_document(row)
        else:
            print("Choose a, c, or d.")
    elif choice == "7":
        record_id = ask_id("Document ID")
        old = get_document(conn, record_id)
        print("Press Enter to keep a value.")
        update_document(
            conn, record_id,
            case_id=ask_id("Case ID", allow_keep=True),
            uploaded_by=ask_id("Uploader employee ID", allow_keep=True),
            title=ask_text("Title", old["title"]),
            doc_type=ask_enum("Document type", DOCUMENT_TYPES, old=old["doc_type"]),
            date_added=ask_date("Date added", old["date_added"]),
            file_path=ask_text("File path", old["file_path"]),
        )
        print("Document updated.")
    elif choice == "8":
        record_id = ask_id("Document ID")
        show_document(get_document(conn, record_id))
        if input("Delete this document? (y/n): ").strip().lower() == "y":
            delete_document(conn, record_id)
            print("Document deleted.")
        else:
            print("Deletion canceled.")


# TODO (Ty'Asia): add hearing_document_menu(conn) to the team's main menu when available.
def hearing_document_menu(conn):
    try:
        ensure_foreign_keys(conn)
    except sqlite3.Error as error:
        print(f"Cannot use database connection: {error}")
        return
    conn.row_factory = sqlite3.Row
    while True:
        print("\nHearing and Document Management")
        print("1. Add hearing")
        print("2. View hearings")
        print("3. Update hearing")
        print("4. Delete hearing")
        print("5. Add document")
        print("6. View documents")
        print("7. Update document")
        print("8. Delete document")
        print("0. Return")
        try:
            choice = input("Choose an option: ").strip()
            if choice == "0":
                return
            if choice in ("1", "2", "3", "4"):
                hearing_actions(conn, choice)
            elif choice in ("5", "6", "7", "8"):
                document_actions(conn, choice)
            else:
                print("Choose a number from 0 through 8.")
        except ValueError as error:
            print(f"Check your input: {error}")
        except sqlite3.IntegrityError as error:
            print(f"Cannot save that record: {error}")
        except sqlite3.Error as error:
            print(f"Database error: {error}")
        except (EOFError, KeyboardInterrupt):
            print("\nReturning from hearing/document management.")
            return


def main():
    parser = argparse.ArgumentParser(description="Manage hearings and document records.")
    parser.add_argument("--db", type=Path, default=DB)
    args = parser.parse_args()
    conn = None
    try:
        conn = open_connection(args.db)
        hearing_document_menu(conn)
    except sqlite3.Error as error:
        parser.exit(1, f"Could not open database: {error}\n")
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
