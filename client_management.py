"""Client management (Person 3): add, search, view, update contact info, delete unused clients.

Main menu entry point: client_menu(conn)
Run on its own:        python client_management.py
"""
import re
import sqlite3
from contextlib import contextmanager
from datetime import date

from db_connection import get_connection

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9()+\-. ]{7,20}$")


@contextmanager
def record_change(conn):
    # A savepoint keeps one change all-or-nothing without committing a
    # transaction the main menu may already have open.
    conn.execute("SAVEPOINT client_change")
    try:
        yield
        conn.execute("RELEASE SAVEPOINT client_change")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT client_change")
        conn.execute("RELEASE SAVEPOINT client_change")
        raise


# ---------- validation ----------

def valid_date(value, label="Date"):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{label}: use YYYY-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label}: enter a real calendar date.") from None


def required_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} cannot be blank.")
    return value.strip()


def valid_email(value):
    value = required_text(value, "Email").lower()
    if not EMAIL_RE.match(value):
        raise ValueError("Enter a valid email address (name@example.com).")
    return value


def valid_phone(value):
    value = required_text(value, "Phone")
    if not PHONE_RE.match(value) or sum(ch.isdigit() for ch in value) < 7:
        raise ValueError("Enter a valid phone number (at least 7 digits).")
    return value


def valid_last4(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}", value.strip()):
        raise ValueError("Government ID must be exactly the last 4 digits.")
    return value.strip()


def valid_dob(value):
    born = valid_date(value, "Date of birth")
    if born > date.today():
        raise ValueError("Date of birth cannot be in the future.")
    return value


def email_taken(conn, email, skip_client_id=None):
    row = conn.execute(
        "SELECT client_id FROM Client WHERE lower(email) = lower(?) AND client_id IS NOT ?",
        (email, skip_client_id),
    ).fetchone()
    return row is not None


# ---------- data functions ----------

def add_client(conn, first_name, last_name, dob, phone, email, address,
               government_id_last4, middle_name=None):
    first_name = required_text(first_name, "First name")
    last_name = required_text(last_name, "Last name")
    middle_name = middle_name.strip() if middle_name and middle_name.strip() else None
    dob = valid_dob(dob)
    phone = valid_phone(phone)
    email = valid_email(email)
    address = required_text(address, "Address")
    government_id_last4 = valid_last4(government_id_last4)
    if email_taken(conn, email):
        raise ValueError("Another client already uses that email.")
    with record_change(conn):
        cursor = conn.execute(
            """INSERT INTO Client (government_id_last4, first_name, middle_name, last_name,
                                   dob, phone, email, address)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (government_id_last4, first_name, middle_name, last_name, dob, phone, email, address),
        )
    return cursor.lastrowid


def search_clients(conn, term=""):
    """Match on name, email, or phone. An empty term lists everyone."""
    like = f"%{term.strip()}%"
    return conn.execute(
        """SELECT c.client_id, c.first_name, c.middle_name, c.last_name, c.phone, c.email,
                  COUNT(lc.case_id) AS case_count
           FROM Client AS c
           LEFT JOIN LegalCase AS lc ON lc.client_id = c.client_id
           WHERE c.first_name || ' ' || c.last_name LIKE ?
              OR c.email LIKE ? OR c.phone LIKE ?
           GROUP BY c.client_id
           ORDER BY c.last_name, c.first_name, c.client_id""",
        (like, like, like),
    ).fetchall()


def get_client(conn, client_id):
    row = conn.execute("SELECT * FROM Client WHERE client_id = ?", (client_id,)).fetchone()
    if row is None:
        raise ValueError(f"Client {client_id} does not exist.")
    return row


def client_cases(conn, client_id):
    return conn.execute(
        """SELECT lc.case_id, lc.case_title, lc.status, lc.date_opened, pa.area_name
           FROM LegalCase AS lc
           JOIN PracticeArea AS pa ON pa.practice_area_id = lc.practice_area_id
           WHERE lc.client_id = ?
           ORDER BY lc.date_opened DESC""",
        (client_id,),
    ).fetchall()


def update_contact(conn, client_id, phone=None, email=None, address=None):
    """Update contact fields. None means keep the current value."""
    old = get_client(conn, client_id)
    phone = old["phone"] if phone is None else valid_phone(phone)
    email = old["email"] if email is None else valid_email(email)
    address = old["address"] if address is None else required_text(address, "Address")
    if email_taken(conn, email, skip_client_id=client_id):
        raise ValueError("Another client already uses that email.")
    with record_change(conn):
        conn.execute(
            "UPDATE Client SET phone = ?, email = ?, address = ? WHERE client_id = ?",
            (phone, email, address, client_id),
        )


def delete_client(conn, client_id):
    """Delete only a client with no cases. Clients with history must be kept."""
    get_client(conn, client_id)
    cases = conn.execute(
        "SELECT COUNT(*) FROM LegalCase WHERE client_id = ?", (client_id,)
    ).fetchone()[0]
    if cases:
        raise ValueError(
            f"Client {client_id} has {cases} case(s) on file and cannot be deleted. "
            "Close the cases instead."
        )
    with record_change(conn):
        conn.execute("DELETE FROM Client WHERE client_id = ?", (client_id,))


# ---------- prompts ----------

def ask(label, current=None, optional=False):
    prompt = f"{label} [{current}]: " if current is not None else f"{label}: "
    while True:
        text = input(prompt).strip()
        if text:
            return text
        if current is not None:
            return None          # keep current value
        if optional:
            return None
        print("This field cannot be blank.")


def ask_id(label):
    while True:
        text = input(f"{label}: ").strip()
        if text.isdigit() and int(text) > 0:
            return int(text)
        print("Enter a positive whole-number ID.")


def full_name(row):
    middle = f" {row['middle_name']}" if row["middle_name"] else ""
    return f"{row['first_name']}{middle} {row['last_name']}"


def show_client(conn, client_id):
    c = get_client(conn, client_id)
    print(f"\nClient {c['client_id']}: {full_name(c)}")
    print(f"  DOB: {c['dob']}   Gov ID last 4: {c['government_id_last4']}")
    print(f"  Phone: {c['phone']}   Email: {c['email']}")
    print(f"  Address: {c['address']}")
    print(f"  Registered: {c['date_registered']}")
    cases = client_cases(conn, client_id)
    if cases:
        print("  Cases:")
        for k in cases:
            print(f"    #{k['case_id']} {k['case_title']} ({k['area_name']}) — {k['status']}, opened {k['date_opened']}")
    else:
        print("  Cases: none")


def menu_add(conn):
    print("\nNew client (middle name optional, press Enter to skip)")
    new_id = add_client(
        conn,
        first_name=ask("First name"),
        middle_name=ask("Middle name", optional=True),
        last_name=ask("Last name"),
        dob=ask("Date of birth (YYYY-MM-DD)"),
        phone=ask("Phone"),
        email=ask("Email"),
        address=ask("Address"),
        government_id_last4=ask("Government ID, last 4 digits"),
    )
    print(f"Client {new_id} added.")


def menu_search(conn):
    term = input("Search name, email, or phone (Enter for all): ")
    rows = search_clients(conn, term)
    if not rows:
        print("No clients found.")
        return
    print(f"\n{'ID':>4}  {'Name':<28} {'Phone':<15} {'Email':<32} Cases")
    for r in rows:
        print(f"{r['client_id']:>4}  {full_name(r):<28} {r['phone']:<15} {r['email']:<32} {r['case_count']}")


def menu_update(conn):
    client_id = ask_id("Client ID")
    old = get_client(conn, client_id)
    print("Press Enter to keep the current value.")
    update_contact(
        conn, client_id,
        phone=ask("Phone", old["phone"]),
        email=ask("Email", old["email"]),
        address=ask("Address", old["address"]),
    )
    print("Contact information updated.")


def menu_delete(conn):
    client_id = ask_id("Client ID")
    show_client(conn, client_id)
    if input("Delete this client? (y/n): ").strip().lower() == "y":
        delete_client(conn, client_id)
        print("Client deleted.")
    else:
        print("Deletion canceled.")


def client_menu(conn):
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    actions = {
        "1": menu_add,
        "2": menu_search,
        "3": lambda c: show_client(c, ask_id("Client ID")),
        "4": menu_update,
        "5": menu_delete,
    }
    while True:
        print("\nClient Management")
        print("1. Add client")
        print("2. Search / list clients")
        print("3. View client details")
        print("4. Update contact information")
        print("5. Delete unused client")
        print("0. Return")
        try:
            choice = input("Choose an option: ").strip()
            if choice == "0":
                return
            if choice in actions:
                actions[choice](conn)
            else:
                print("Choose a number from 0 through 5.")
        except ValueError as error:
            print(f"Check your input: {error}")
        except sqlite3.IntegrityError as error:
            print(f"Cannot save that record: {error}")
        except sqlite3.Error as error:
            print(f"Database error: {error}")
        except (EOFError, KeyboardInterrupt):
            print("\nReturning from client management.")
            return


if __name__ == "__main__":
    connection = get_connection()
    try:
        client_menu(connection)
    finally:
        connection.close()
