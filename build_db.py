import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = os.path.join(HERE, "schema.sql")
DB = os.path.join(HERE, "bayou.db")

# Start fresh each time so schema changes never leave stale tables behind.
if os.path.exists(DB):
    os.remove(DB)

conn = sqlite3.connect(DB)
conn.execute("PRAGMA foreign_keys = ON")
with open(SCHEMA, encoding="utf-8") as f:
    conn.executescript(f.read())
conn.commit()

tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
print(f"Built {DB}")
print(f"{len(tables)} tables: {', '.join(tables)}")
conn.close()