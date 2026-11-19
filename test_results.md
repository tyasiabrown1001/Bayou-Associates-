# Person 5 Testing Results

Completed by Ceionna Mitchell

## Tests completed

Ran `python3 -m unittest -v test_person5`.

All 18 tests passed using sample records in a separate in-memory database.

The tests checked:
- Adding a valid time entry with the correct rate and billing status.
- Rejecting invalid hours, dates, blank descriptions, and missing cases.
- Rejecting employees who were not assigned to the case or had no billing rate.
- Checking assignment dates.
- Editing an unbilled entry while keeping its original rate.
- Deleting an unbilled entry.
- Preventing edits and deletions of billed or written-off entries.
- Rejecting missing entries.
- Making sure a failed addition does not save a record.
- Verifying the expected results of all five SQL queries.

I also opened the time-entry menu and checked the view option with an empty database.

## Query choices

The date-sensitive queries use December 1, 2026 as the reference date.
The hearing window includes December 1 through December 14.
Billable hours include Billed and Unbilled entries.
Draft invoices are excluded from overdue invoices and total billed amounts.
An assignment ends on date_unassigned, so that date is excluded.

## Issues found

No failures occurred in these 18 tests.

## Still needed

- Run the five queries against the final populated database.
- Save the final query outputs and verify their results.
- Test the time-entry menu after integration into the main application.
- Test logging time, creating an invoice, recording a payment, and checking the balance with the billing module.
- Record any integration defects and retest after fixes.
- Capture the time-entry screenshot for the report.
