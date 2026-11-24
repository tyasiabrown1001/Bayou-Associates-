# Person 4 handoff — Joy Nganga

## Completed

- `generate_data.py` rebuilds `bayou.db` using the unchanged `schema.sql`. It uses a fixed seed (4402), inserts records in foreign-key order, and preserves the previous database if a rebuild fails.
- `verify_data.py` checks row counts, SQLite integrity and foreign keys, relationships, dates, invoice totals, payments, and query demonstration cases. Use `--queries queries.sql` after Ceionna's query file is available.
- `hearing_document.py` provides add, list, detail, update, and delete options for hearings and document metadata. Input is checked, and deletions require confirmation.
- `test_person4.py` contains the unit and CLI-interaction tests. It uses a temporary database, so it does not modify the shared `bayou.db`.

## Run from the repository root

```bash
python generate_data.py
python verify_data.py
python -m unittest -v test_person4
python hearing_document.py
```

When Ceionna's files are also present:

```bash
python verify_data.py --queries queries.sql
python -m unittest -v test_person4 test_person5
python query_runner.py --as-of 2026-12-01
```

**Warning:** `generate_data.py` intentionally replaces `bayou.db` with fresh sample records. Close any program using that file first, and do not use it on a database you need to preserve. Kiersten's `build_db.py` also replaces the database, but creates empty tables.

## Report-ready text (Person 4 contribution)

I created a repeatable Python script to populate the Bayou & Associates SQLite database with fictional records. The dataset contains 30 clients, 13 employees, 4 practice areas, 40 cases, 52 case assignments, 4 courts, 25 hearings, 60 documents, 120 time entries, 35 invoices, and 31 payments. The records follow the foreign-key relationships and include open and closed cases, different invoice payment states, and hearing dates inside and outside the query reporting window. I also built a command-line menu for adding, viewing, updating, and deleting hearing and document records, including checks for valid case references and dates.

For the interface illustration in the final report, run `python hearing_document.py`, capture the Hearing and Document Management menu, then optionally capture a hearing detail or document detail screen. Document records refer to example file paths; they do not require uploading real PDFs.

## Integration notes

- Default database path: `bayou.db` beside the Python scripts.
- Main menu entry point: `from hearing_document import hearing_document_menu`, then call `hearing_document_menu(conn)` with an open SQLite connection.
- The hearing/document module has an optional `db_connection.get_connection` import with a local fallback. **TODO for Brandon/assigned helper owner:** confirm the final helper's module and function names.
- **TODO for Ty'Asia:** add `hearing_document_menu(conn)` to the unified application when the main menu exists.
- Sample data is frozen as of **November 24, 2026**; SQL query demonstrations use **December 1, 2026** as their fixed reference date. Ceionna's 14-day query covers December 1–14 (not December 15).
- `bayou.db` is intentionally ignored by `.gitignore`. The final grading ZIP must still include a populated database or clear instructions to rebuild it.
- Person 4's functions use parameterized SQL and SQLite savepoints so they do not commit a pending transaction started by another module.

## Tests and scope

- Person 4: 36 automated tests passed in the combined local environment.
- Together with Ceionna: 54 tests passed.
- Standalone hearing/document add, update, and delete operations were also executed against a disposable database copy.
- Client/case management, billing/payment management, the shared connection helper, and the overall menu are owned outside Person 4 and are not supplied here.
