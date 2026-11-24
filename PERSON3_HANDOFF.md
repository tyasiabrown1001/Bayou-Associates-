# Person 3 handoff — Brandon Avila

## Completed

- `db_connection.py`: the shared helper. `get_connection()` opens `bayou.db` next to the scripts with foreign keys ON and `sqlite3.Row` rows (columns readable by name). It refuses to create a new empty file if the database is missing. Joy's `hearing_document.py` already imports it and now uses it instead of its fallback.
- `client_management.py`: add a client, search/list (name, email, or phone), view details with the client's cases, update contact info (phone, email, address), and delete a client only when they have no cases.
- `case_management.py`: open a case for an existing client (the Lead attorney is assigned in the same step), list cases, view case details (team, history, activity counts), update title/description/practice area/status, assign an attorney, change the Lead, remove an assignment, close a case, and reopen a closed case.
- `test_person3.py`: 19 tests on a temporary database built from `schema.sql`, so `bayou.db` is never modified.

## Run from the repository root

```bash
python generate_data.py          # Joy's script: builds bayou.db with sample data
python db_connection.py          # quick check: connects and lists the 11 tables
python client_management.py      # Client Management menu
python case_management.py        # Case Management menu
python -m unittest -v test_person3
```

All teams' tests together: `python -m unittest test_person3 test_person4 test_person5` (73 passed on 2026-11-24).

## Integration notes (for Ty'Asia's main menu)

```python
from db_connection import get_connection
from client_management import client_menu
from case_management import case_menu

conn = get_connection()
client_menu(conn)   # or case_menu(conn)
```

- Both menus take an open connection and return when the user picks 0 (or hits Ctrl+C / end of input).
- Changes use SQLite savepoints, same pattern as Joy's module, so they never commit a transaction the main menu opened.
- All SQL uses parameters for user input.

## Rules enforced in the case module

| Rule | How |
|---|---|
| A case needs at least one assigned employee | Opening a case inserts the case and its Lead assignment together. If either fails, neither is saved. |
| Only active attorneys are assigned | Paralegals, staff, inactive attorneys, and attorneys without a rate are rejected (time entries need a rate). |
| One active Lead per case | A second Lead is refused; "Change Lead attorney" swaps roles and makes the old Lead an Associate. |
| The Lead can't be removed | Change the Lead first, then remove the old one. |
| Remove an assignment without losing history | Sets `date_unassigned`; the row stays. The date must be after that attorney's last logged time on the case, so Ceionna's time-entry check stays consistent. |
| Returning attorney | Reuses the same `(case_id, employee_id)` row (it's the primary key) and clears `date_unassigned`. |
| Closing | Sets `status = 'Closed'` and `date_closed` together (matches the schema CHECK). Closed cases can't be edited or assigned until reopened. |
| Invalid references | Missing clients, practice areas, employees, and cases get a clear message instead of a crash. The database FK constraints back this up. |
| Deleting clients | Only clients with no cases; everyone else is kept (cases with history get closed, not deleted). |
| Dates | `YYYY-MM-DD`, real calendar dates, not in the future, and never before the case opened. |

## Report-ready text (Person 3 contribution)

**Relational schema section (draft — check it against Kiersten's final `schema.sql`):**

The relational schema was built straight from the E-R diagram, so each entity set became its own table and the many-to-many relationship between employees and cases became the CaseAssignment table. CaseAssignment uses the pair (case_id, employee_id) as its primary key, and it also carries the attorney's role on the case and the dates they were assigned and unassigned. Every table uses an integer primary key, and every relationship is enforced with a foreign key that blocks deletes (ON DELETE RESTRICT), which basically means a record can't be removed while something else still points to it. CHECK constraints handle the business rules the database can enforce by itself, like a case only being Closed when it has a close date, hours being between 0 and 24, and attorneys being the only employees with a bar number. The rules that need more than one table, like an attorney having to be assigned to a case before logging time on it, are enforced in the application instead.

**Case and client interface illustration:**

The client and case management interfaces are command-line menus. The client menu lets staff add a client, search by name, email, or phone, update contact information, and delete a client only if they have no cases on file. The case menu lets staff open a case for an existing client, assign attorneys, change the Lead attorney, remove an assignment, update the case, and close or reopen it. The most important rule here is that a case is opened together with its Lead attorney, so a case can never exist without someone assigned to it. Removing an attorney doesn't delete anything; it records the date they came off the case so their logged hours still make sense.

Screenshots to capture for the report: `python case_management.py` → option 3 (view case details) on a case with a removed attorney, and option 1 (open a new case). For clients: option 2 (search) and the refusal message when deleting a client that has cases.
