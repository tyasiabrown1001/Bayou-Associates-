import argparse
import os
import random
import sqlite3
import tempfile
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA = HERE / "schema.sql"
DEFAULT_DB = HERE / "bayou.db"
REFERENCE_DATE = date(2026, 12, 1)
DATA_AS_OF = date(2026, 11, 24)
SEED = 4402

FIRST_NAMES = [
    "Avery", "Jordan", "Camille", "Morgan", "Taylor", "Sydney", "Alexis",
    "Riley", "Quinn", "Devin", "Jules", "Casey", "Parker", "Reese", "Blair",
    "Noelle", "Micah", "Amari", "Drew", "Marcel", "Tiana", "Andre", "Nia",
    "Elliot", "Sage", "Brielle", "Ellis", "Janelle", "Darian", "Kendall",
]
LAST_NAMES = [
    "Landry", "Batiste", "Thibodeaux", "Broussard", "Fontenot", "Guidry",
    "LeBlanc", "Arceneaux", "Richard", "Hebert", "Daigle", "Boudreaux",
    "Comeaux", "Duplantier", "Doucet", "Toussaint", "Robicheaux", "Joseph",
    "Johnson", "Williams", "Charles", "Davis", "Green", "Collins", "Morris",
    "Jackson", "Price", "Taylor", "Martin", "Henderson",
]
AREAS = ["Family Law", "Estate Planning", "Business Law", "Civil Litigation"]
DOCUMENT_TYPES = ["Pleading", "Contract", "Evidence", "Correspondence"]
HOURS = [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4]
WORK = ["Client consultation", "Case research", "Drafting and review"]


def iso(day):
    return day.isoformat()


def plus(day, days):
    return day + timedelta(days=days)


def random_day(rng, first, last):
    return plus(first, rng.randint(0, (last - first).days))


def money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def make_records(rng):
    clients = []
    for number in range(1, 31):
        clients.append((
            number, f"{rng.randint(0, 9999):04d}", FIRST_NAMES[number - 1], None,
            LAST_NAMES[number - 1], iso(date(1971 + number % 25, (number % 12) + 1, 8)),
            f"225555{100 + number:04d}", f"client{number:02d}@example.com",
            f"{200 + number} Cypress Bend Ln, Baton Rouge, LA 70802",
            iso(date(2025, 1, 1) + timedelta(days=number)),
        ))

    employees = []
    for number in range(1, 14):
        is_attorney = number <= 8
        job = "Attorney" if is_attorney else [
            "Paralegal", "Paralegal", "Receptionist", "Billing Clerk", "Legal Assistant"
        ][number - 9]
        employees.append((
            number, FIRST_NAMES[(number + 9) % 30], None,
            LAST_NAMES[(number + 13) % 30],
            iso(date(1975 + number, (number % 12) + 1, 6)),
            f"225555{150 + number:04d}", f"employee{number:02d}@example.com",
            iso(date(2017 + number % 6, 2, 10)), "TRUE", job,
            (175 + 25 * number) if is_attorney else None,
            f"LA-TEST-{1000 + number}" if is_attorney else None,
        ))

    practice_areas = [(i, name) for i, name in enumerate(AREAS, 1)]
    courts = [
        (1, "Capital District Civil Court", "State", "101 Justice Square, Baton Rouge, LA"),
        (2, "River Parish Family Court", "State", "210 Parish Plaza, Baton Rouge, LA"),
        (3, "Louisiana Federal District Court (Sample)", "Federal", "310 Court Ave, Baton Rouge, LA"),
        (4, "Baton Rouge Municipal Court (Sample)", "Municipal", "410 Civic Way, Baton Rouge, LA"),
    ]

    cases, assignments = [], []
    case_days, case_closed, lead_ids = {}, {}, {}
    for case_id in range(1, 41):
        if case_id <= 20:
            opened = plus(date(2026, 1, 5), rng.randint(0, 55))
            closed, status = None, "Open"
        elif case_id <= 30:
            opened = plus(date(2026, 3, 2), rng.randint(0, 45))
            closed, status = None, "Pending"
        else:
            opened = plus(date(2025, 5, 3), rng.randint(0, 95))
            closed, status = plus(date(2026, 10, 1), rng.randint(0, 17)), "Closed"

        client_id = (case_id - 1) % 30 + 1
        case_days[case_id] = opened
        case_closed[case_id] = closed
        lead = 8 if case_id in (31, 36, 40) else (case_id - 1) % 7 + 1
        lead_ids[case_id] = lead
        cases.append((
            case_id, f"{LAST_NAMES[client_id - 1]} {AREAS[(case_id - 1) % 4]} Matter {case_id:02d}",
            "Fictional client matter for the Bayou & Associates demonstration.", status,
            iso(opened), iso(closed) if closed else None, client_id, (case_id - 1) % 4 + 1,
        ))
        assignments.append((case_id, lead, "Lead", iso(opened), None))

        if case_id <= 12:
            associate = (lead % 7) + 1
            end = iso(date(2026, 10, 30)) if case_id <= 4 else None
            assignments.append((case_id, associate, "Associate" if case_id % 2 else "Consulting",
                                iso(plus(opened, 3)), end))

    time_entries, planned = [], {}
    time_id = 1
    for case_id in range(1, 41):
        opened = case_days[case_id]
        if case_id <= 10:
            last_work = date(2026, 4, 25)
        elif case_id <= 30:
            last_work = date(2026, 9, 20)
        else:
            last_work = date(2026, 9, 25)
        planned[case_id] = []
        for slot in range(3):
            employee_id = lead_ids[case_id]
            work_date = random_day(rng, plus(opened, 7), last_work)
            hours = rng.choice(HOURS)
            rate = 175 + 25 * employee_id
            status = "Written Off" if slot == 2 and case_id % 5 == 0 else "Unbilled"
            entry = [time_id, case_id, employee_id, iso(work_date), hours, rate,
                     WORK[slot], status, None]
            planned[case_id].append(entry)
            time_entries.append(entry)
            time_id += 1

    invoice_specs = []
    for case_id in range(1, 26):
        if case_id <= 10:
            invoice_specs.append((case_id, [planned[case_id][0]]))
            invoice_specs.append((case_id, [planned[case_id][1]]))
        else:
            invoice_specs.append((case_id, planned[case_id][:2]))

    invoices, payments = [], []
    payment_id = 1
    for invoice_id, (case_id, entries) in enumerate(invoice_specs, 1):
        if case_id <= 10:
            inv_day = plus(date(2026, 5, 5), case_id + (25 if invoice_id % 2 == 0 else 0))
            due_day = plus(inv_day, 21)
        else:
            inv_day = plus(date(2026, 10, 3), case_id % 10)
            due_day = plus(inv_day, 14 if case_id % 3 == 0 else 38)

        assert max(date.fromisoformat(e[3]) for e in entries) <= inv_day
        total = money(sum(Decimal(str(e[4])) * Decimal(str(e[5])) for e in entries))
        for entry in entries:
            entry[7] = "Billed"
            entry[8] = invoice_id

        draft = invoice_id in (10, 20)
        paid_full = invoice_id % 4 == 0 and not draft
        partly_paid = invoice_id % 4 in (1, 2) and not draft
        status = ("Draft" if draft else "Paid" if paid_full
                  else "Overdue" if due_day < DATA_AS_OF else "Sent")
        invoices.append((invoice_id, case_id, iso(inv_day), iso(due_day), float(total), status))

        if paid_full:
            first = money(total * Decimal("0.45"))
            amounts = [first, total - first]
        elif partly_paid:
            amounts = [money(total * Decimal("0.35" if invoice_id % 2 else "0.60"))]
        else:
            amounts = []
        for index, amount in enumerate(amounts):
            payment_day = plus(inv_day, 7 + index * 5)
            assert payment_day < DATA_AS_OF
            payments.append((payment_id, invoice_id, iso(payment_day), float(amount),
                             ["ACH", "Card", "Check", "Cash"][payment_id % 4],
                             f"SAMPLE-{payment_id:05d}"))
            payment_id += 1

    hearings = []
    for hearing_id in range(1, 26):
        if hearing_id <= 10:
            case_id = hearing_id + 30
            hearing_day = plus(date(2026, 9, 2), hearing_id)
        elif hearing_id <= 14:
            case_id = hearing_id + 10
            hearing_day = plus(date(2026, 10, 1), hearing_id - 10)
        elif hearing_id <= 17:
            case_id = hearing_id - 14
            hearing_day = plus(date(2026, 11, 20), hearing_id - 15)
        elif hearing_id <= 23:
            case_id = hearing_id - 14
            hearing_day = plus(REFERENCE_DATE, [0, 2, 4, 7, 11, 13][hearing_id - 18])
        else:
            case_id = hearing_id - 14
            hearing_day = plus(REFERENCE_DATE, 14 if hearing_id == 24 else 19)
        outcome = (rng.choice(["Continued", "Granted", "Denied", "Settled", "Dismissed"])
                   if hearing_day < DATA_AS_OF else None)
        hearings.append((hearing_id, case_id, (hearing_id - 1) % 4 + 1, iso(hearing_day),
                         f"{9 + hearing_id % 6:02d}:00", "Status conference" if hearing_id % 2 else "Motion hearing",
                         outcome))

    documents = []
    for doc_id in range(1, 61):
        case_id = (doc_id - 1) % 40 + 1
        doc_type = DOCUMENT_TYPES[(doc_id - 1) % 4]
        if case_id > 30:
            added = plus(date(2026, 8, 15), doc_id % 20)
        else:
            added = plus(date(2026, 8, 4), doc_id % 28)
        uploader = lead_ids[case_id] if doc_id <= 40 else 9 + (doc_id % 5)
        filename = doc_type.lower() + f"_{doc_id:03d}.pdf"
        documents.append((doc_id, case_id, uploader, f"{doc_type} for case {case_id:02d}",
                          doc_type, iso(added), f"documents/case_{case_id:03d}/{filename}"))

    return [
        ("Client", "client_id, government_id_last4, first_name, middle_name, last_name, dob, phone, email, address, date_registered", clients),
        ("Employee", "employee_id, first_name, middle_name, last_name, dob, phone, email, hire_date, is_active, job_role, hourly_rate, bar_number", employees),
        ("PracticeArea", "practice_area_id, area_name", practice_areas),
        ("LegalCase", "case_id, case_title, description, status, date_opened, date_closed, client_id, practice_area_id", cases),
        ("CaseAssignment", "case_id, employee_id, case_role, date_assigned, date_unassigned", assignments),
        ("Court", "court_id, court_name, court_type, address", courts),
        ("Hearing", "hearing_id, case_id, court_id, hearing_date, hearing_time, purpose, outcome", hearings),
        ("Document", "document_id, case_id, uploaded_by, title, doc_type, date_added, file_path", documents),
        ("Invoice", "invoice_id, case_id, invoice_date, due_date, total_amount, status", invoices),
        ("TimeEntry", "time_entry_id, case_id, employee_id, work_date, hours, hourly_rate, description, billing_status, invoice_id", time_entries),
        ("Payment", "payment_id, invoice_id, payment_date, amount, method, reference_number", payments),
    ]


def generate_database(db_path=DEFAULT_DB, schema_path=SCHEMA):
    db_path, schema_path = Path(db_path), Path(schema_path)
    if not schema_path.is_file():
        raise FileNotFoundError(f"Missing schema: {schema_path}")
    if db_path.suffix.lower() not in (".db", ".sqlite", ".sqlite3"):
        raise ValueError("The database filename must end in .db, .sqlite or .sqlite3.")
    if db_path.resolve() == schema_path.resolve():
        raise ValueError("The database path cannot be the schema path.")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Build separately so a failed run cannot erase the previous good database.
    descriptor, name = tempfile.mkstemp(
        prefix=f".{db_path.stem}_", suffix=".sqlite", dir=db_path.parent
    )
    os.close(descriptor)
    temporary_db = Path(name)
    conn = None
    try:
        conn = sqlite3.connect(temporary_db)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript("BEGIN IMMEDIATE;\n" + schema_path.read_text(encoding="utf-8"))
        tables = make_records(random.Random(SEED))
        for table, columns, records in tables:
            placeholders = ", ".join("?" for _ in range(len(records[0])))
            conn.executemany(
                "INSERT INTO {} ({}) VALUES ({})".format(table, columns, placeholders), records
            )
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Foreign key violations in generated records.")
        counts = {table: conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                  for table, _, _ in tables}
        conn.commit()
        conn.close()
        conn = None
        os.replace(temporary_db, db_path)
        return counts
    except Exception:
        if conn is not None:
            conn.rollback()
            conn.close()
        temporary_db.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description="Rebuild and populate the law firm sample database.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    try:
        counts = generate_database(args.db)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(1, f"Could not generate the database: {error}\n")
    print(f"Created {args.db} using seed {SEED} (data through {DATA_AS_OF}; query date {REFERENCE_DATE}).")
    for table, count in counts.items():
        print(f"{table}: {count}")


if __name__ == "__main__":
    main()
