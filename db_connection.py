"""Shared database connection helper for the Bayou & Associates application.

Every module opens the database through get_connection() so that all of them
get the same settings: foreign keys enforced and rows readable by column name.
"""
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "bayou.db"


def get_connection(db_path=DB):
    """Open the existing database with foreign keys ON and sqlite3.Row rows.

    The file must already exist (run build_db.py or generate_data.py first),
    so a typo in the path never silently creates an empty database.
    """
    path = Path(db_path).resolve()
    if not path.exists():
        raise sqlite3.OperationalError(
            f"Database not found at {path}. Run 'python generate_data.py' first."
        )
    conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=10)
    conn.execute("PRAGMA foreign_keys = ON")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        conn.close()
        raise sqlite3.OperationalError("SQLite foreign key enforcement could not be enabled.")
    conn.row_factory = sqlite3.Row
    return conn


if __name__ == "__main__":
    check = get_connection()
    try:
        tables = [r["name"] for r in check.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        print(f"Connected to {DB} (foreign keys ON)")
        print(f"{len(tables)} tables: {', '.join(tables)}")
    finally:
        check.close()
