import argparse
import sqlite3
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent

QUERY_NAMES = [
    "Open cases per attorney",
    "Unpaid invoices over 30 days overdue",
    "Billable hours by practice area",
    "Upcoming hearings in the next 14 days",
    "Clients ranked by total billed",
]


def load_queries():
    sql = (HERE / "queries.sql").read_text(encoding="utf-8")
    queries = [statement.strip() for statement in sql.split(";")
               if statement.strip()]

    if len(queries) != len(QUERY_NAMES):
        raise ValueError("queries.sql should contain exactly five queries.")

    return queries


def display_results(cursor):
    headers = [column[0] for column in cursor.description]
    rows = cursor.fetchall()

    if not rows:
        print("No results.")
        return

    values = [
        ["" if value is None else str(value) for value in row]
        for row in rows
    ]
    widths = [
        max(len(header), max(len(row[index]) for row in values))
        for index, header in enumerate(headers)
    ]

    print(" | ".join(
        header.ljust(width)
        for header, width in zip(headers, widths)
    ))
    print("-+-".join("-" * width for width in widths))

    for row in values:
        print(" | ".join(
            value.ljust(width)
            for value, width in zip(row, widths)
        ))

    print(f"\nRows returned: {len(rows)}")


def run_queries(conn, as_of):
    # A fixed date keeps our report results repeatable.
    date.fromisoformat(as_of)
    print(f"Reference date: {as_of}")

    for number, (name, query) in enumerate(
        zip(QUERY_NAMES, load_queries()), start=1
    ):
        print(f"\n{number}. {name}")
        cursor = conn.execute(query, {"as_of": as_of})
        display_results(cursor)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default="2026-12-01")
    parser.add_argument("--db", type=Path, default=HERE / "bayou.db")
    args = parser.parse_args()

    conn = None

    try:
        date.fromisoformat(args.as_of)

        # Open the existing database so a wrong path is caught.
        database_uri = args.db.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(database_uri)
        conn.execute("PRAGMA foreign_keys = ON")
        run_queries(conn, args.as_of)
    except (sqlite3.Error, OSError, ValueError) as error:
        parser.exit(1, f"Could not run queries: {error}\n")
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
