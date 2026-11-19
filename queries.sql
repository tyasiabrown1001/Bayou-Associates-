-- 1. Open cases for each attorney, including zero.
SELECT
    e.employee_id,
    e.first_name || ' ' || e.last_name AS attorney,
    COUNT(lc.case_id) AS open_cases
FROM Employee AS e
LEFT JOIN CaseAssignment AS ca
    ON ca.employee_id = e.employee_id
    AND ca.date_unassigned IS NULL
LEFT JOIN LegalCase AS lc
    ON lc.case_id = ca.case_id
    AND lc.status = 'Open'
WHERE e.job_role = 'Attorney'
GROUP BY e.employee_id, e.first_name, e.last_name
ORDER BY open_cases DESC, attorney, e.employee_id;

-- 2. Invoices over 30 days overdue that still have a balance.
WITH payment_totals AS (
    SELECT invoice_id, SUM(amount) AS paid
    FROM Payment
    GROUP BY invoice_id
)
SELECT
    i.invoice_id,
    c.first_name || ' ' || c.last_name AS client,
    i.due_date,
    ROUND(i.total_amount - COALESCE(p.paid, 0), 2)
        AS remaining_balance
FROM Invoice AS i
JOIN LegalCase AS lc ON lc.case_id = i.case_id
JOIN Client AS c ON c.client_id = lc.client_id
LEFT JOIN payment_totals AS p ON p.invoice_id = i.invoice_id
WHERE i.status <> 'Draft'
    AND DATE(i.due_date) < DATE(:as_of, '-30 days')
    AND ROUND(i.total_amount - COALESCE(p.paid, 0), 2) > 0
ORDER BY i.due_date, i.invoice_id;

-- 3. Billable hours for each practice area.
SELECT
    pa.area_name AS practice_area,
    ROUND(COALESCE(SUM(te.hours), 0), 2) AS billable_hours
FROM PracticeArea AS pa
LEFT JOIN LegalCase AS lc
    ON lc.practice_area_id = pa.practice_area_id
LEFT JOIN TimeEntry AS te
    ON te.case_id = lc.case_id
    AND te.billing_status IN ('Unbilled', 'Billed')
GROUP BY pa.practice_area_id, pa.area_name
ORDER BY billable_hours DESC, practice_area;

-- 4. Hearings during the 14-day window, starting on the reference date.
SELECT
    h.hearing_id,
    h.hearing_date,
    h.hearing_time,
    lc.case_title,
    c.court_name,
    COALESCE(
        (
            SELECT GROUP_CONCAT(
                e.first_name || ' ' || e.last_name, ', '
            )
            FROM CaseAssignment AS ca
            JOIN Employee AS e
                ON e.employee_id = ca.employee_id
            WHERE ca.case_id = h.case_id
                AND e.job_role = 'Attorney'
                AND ca.date_assigned <= h.hearing_date
                AND (
                    ca.date_unassigned IS NULL
                    OR ca.date_unassigned > h.hearing_date
                )
        ),
        'None assigned'
    ) AS assigned_attorneys
FROM Hearing AS h
JOIN LegalCase AS lc ON lc.case_id = h.case_id
JOIN Court AS c ON c.court_id = h.court_id
WHERE DATE(h.hearing_date) >= DATE(:as_of)
    AND DATE(h.hearing_date) < DATE(:as_of, '+14 days')
ORDER BY h.hearing_date, h.hearing_time, h.hearing_id;

-- 5. Clients ranked by their total billed amount.
WITH client_totals AS (
    SELECT
        c.client_id,
        c.first_name || ' ' || c.last_name AS client,
        ROUND(SUM(i.total_amount), 2) AS total_billed
    FROM Client AS c
    JOIN LegalCase AS lc ON lc.client_id = c.client_id
    JOIN Invoice AS i ON i.case_id = lc.case_id
    WHERE i.status <> 'Draft'
    GROUP BY c.client_id, c.first_name, c.last_name
)
SELECT
    DENSE_RANK() OVER (
        ORDER BY total_billed DESC
    ) AS billing_rank,
    client_id,
    client,
    total_billed
FROM client_totals
ORDER BY billing_rank, client, client_id;
