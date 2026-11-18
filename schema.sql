PRAGMA foreign_keys = ON;

CREATE TABLE Client (
    client_id            INTEGER PRIMARY KEY,
    government_id_last4  TEXT    NOT NULL
                         CHECK (government_id_last4 GLOB '[0-9][0-9][0-9][0-9]'),
    first_name           TEXT    NOT NULL,
    middle_name          TEXT,
    last_name            TEXT    NOT NULL,
    dob                  TEXT    NOT NULL
                         CHECK (date(dob) IS dob),
    phone                TEXT    NOT NULL,
    email                TEXT    NOT NULL UNIQUE,
    address              TEXT    NOT NULL,
    date_registered      TEXT    NOT NULL DEFAULT (date('now','localtime'))
                         CHECK (date(date_registered) IS date_registered)
);

CREATE TABLE Employee(
    employee_id         INTEGER PRIMARY KEY,
    first_name          TEXT    NOT NULL,
    middle_name         TEXT,
    last_name           TEXT    NOT NULL,
    dob                 TEXT    NOT NULL
                        CHECK (date(dob) IS dob),
    phone               TEXT    NOT NULL,
    email               TEXT    NOT NULL    UNIQUE,
    hire_date           TEXT    NOT NULL    
                        DEFAULT (date('now','localtime'))
                        CHECK(date(hire_date) IS hire_date),
    is_active           TEXT    NOT NULL DEFAULT 'TRUE'
                        CHECK(is_active IN ('TRUE', 'FALSE')),
    job_role            TEXT    NOT NULL
                        CHECK (job_role IN ('Attorney', 'Paralegal', 'Receptionist', 'Billing Clerk', 'Legal Assistant')),
    hourly_rate         REAL
                        CHECK (hourly_rate IS NULL OR hourly_rate >= 0),
    bar_number          TEXT    UNIQUE,
    CHECK ((job_role = 'Attorney') = (bar_number IS NOT NULL)) 
);

CREATE TABLE PracticeArea(
    practice_area_id    INTEGER PRIMARY KEY,
    area_name           TEXT    NOT NULL UNIQUE
);

CREATE TABLE LegalCase(
    case_id             INTEGER PRIMARY KEY,
    case_title          TEXT    NOT NULL,
    description         TEXT    NOT NULL,
    status              TEXT    NOT NULL
                        CHECK( status IN ('Open','Pending','Closed')),
    date_opened         TEXT    NOT NULL
                        CHECK(date(date_opened) IS date_opened)
                        DEFAULT (date('now','localtime')),
    date_closed         TEXT
                        CHECK(date(date_closed) IS NULL OR date(date_closed) IS date_closed),
    client_id           INTEGER NOT NULL,
    practice_area_id    INTEGER NOT NULL,
    CHECK (date_closed IS NULL OR date_closed >= date_opened),
    CHECK ((status = 'Closed') = (date_closed IS NOT NULL)),
    FOREIGN KEY (client_id) REFERENCES Client(client_id) ON DELETE RESTRICT,
    FOREIGN KEY (practice_area_id) REFERENCES PracticeArea(practice_area_id) ON DELETE RESTRICT
);

CREATE TABLE CaseAssignment(
    case_id             INTEGER NOT NULL,
    employee_id         INTEGER NOT NULL,
    case_role           TEXT    NOT NULL
                        CHECK (case_role IN ('Lead','Associate', 'Consulting')),
    date_assigned       TEXT    NOT NULL
                        CHECK(date(date_assigned) IS date_assigned)
                        DEFAULT (date('now','localtime')),
    date_unassigned     TEXT
                        CHECK(date(date_unassigned) IS date_unassigned),
    PRIMARY KEY (case_id, employee_id),
    CHECK(date_unassigned IS NULL OR date_unassigned >= date_assigned),
    FOREIGN KEY (case_id) REFERENCES LegalCase(case_id) ON DELETE RESTRICT,
    FOREIGN KEY (employee_id) REFERENCES Employee(employee_id) ON DELETE RESTRICT
);

CREATE TABLE Court(
    court_id            INTEGER PRIMARY KEY,
    court_name          TEXT NOT NULL,
    court_type          TEXT NOT NULL
                        CHECK(court_type IN ('State', 'Federal', 'Municipal')),
    address             TEXT NOT NULL
);

CREATE TABLE Hearing(
    hearing_id          INTEGER PRIMARY KEY,
    case_id             INTEGER NOT NULL,
    court_id            INTEGER NOT NULL,
    hearing_date        TEXT    NOT NULL
                        CHECK(date(hearing_date) is hearing_date),
    hearing_time        TEXT    NOT NULL
                        CHECK (strftime('%H:%M', hearing_time) IS hearing_time),
    purpose             TEXT    NOT NULL,
    outcome             TEXT
                        CHECK(outcome IS NULL OR outcome IN ('Continued', 'Granted', 'Denied', 'Settled', 'Dismissed')),
    FOREIGN KEY (case_id) REFERENCES LegalCase(case_id) ON DELETE RESTRICT,
    FOREIGN KEY (court_id) REFERENCES Court(court_id) ON DELETE RESTRICT

);

CREATE TABLE Document(
    document_id         INTEGER PRIMARY KEY,
    case_id             INTEGER NOT NULL,
    uploaded_by         INTEGER    NOT NULL,
    title               TEXT    NOT NULL,   
    doc_type            TEXT    NOT NULL
                        CHECK(doc_type IN ('Pleading','Contract','Evidence','Correspondence')),
    date_added          TEXT    NOT NULL
                        DEFAULT (date('now','localtime'))
                        CHECK(date(date_added) IS date_added),
    file_path           TEXT   NOT NULL,
    FOREIGN KEY (case_id) REFERENCES LegalCase(case_id) ON DELETE RESTRICT,
    FOREIGN KEY (uploaded_by) REFERENCES Employee(employee_id) ON DELETE RESTRICT
);

CREATE TABLE Invoice(
    invoice_id      INTEGER PRIMARY KEY,
    case_id         INTEGER NOT NULL,
    invoice_date    TEXT    NOT NULL
                    CHECK(date(invoice_date) IS invoice_date)
                    DEFAULT (date('now','localtime')),
    due_date        TEXT    NOT NULL
                    CHECK(date(due_date) IS due_date),
    total_amount    REAL NOT NULL DEFAULT 0
                    CHECK(total_amount >= 0),
    status          TEXT    NOT NULL  DEFAULT 'Draft'
                    CHECK(status IN ('Draft', 'Sent', 'Paid', 'Overdue')),
    CHECK(due_date >= invoice_date),
    FOREIGN KEY (case_id) REFERENCES LegalCase(case_id) ON DELETE RESTRICT
    
    
);

CREATE TABLE TimeEntry(
    time_entry_id       INTEGER PRIMARY KEY,   
    case_id             INTEGER NOT NULL,
    employee_id         INTEGER NOT NULL,
    work_date           TEXT    NOT NULL
                        CHECK(date(work_date) is work_date)
                        DEFAULT (date('now','localtime')),
    hours               REAL NOT NULL
                        CHECK(hours > 0 AND hours <= 24),
    hourly_rate         REAL NOT NULL
                        CHECK(hourly_rate >= 0),
    description         TEXT    NOT NULL,
    billing_status      TEXT    NOT NULL DEFAULT 'Unbilled'
                        CHECK(billing_status IN ('Unbilled', 'Billed', 'Written Off')),
    invoice_id          INTEGER,
    CHECK ((billing_status = 'Billed') = (invoice_id IS NOT NULL)),
    FOREIGN KEY (case_id) REFERENCES LegalCase(case_id) ON DELETE RESTRICT,
    FOREIGN KEY (employee_id) REFERENCES Employee(employee_id) ON DELETE RESTRICT,
    FOREIGN KEY (invoice_id) REFERENCES Invoice(invoice_id) ON DELETE RESTRICT
    
);


CREATE TABLE Payment(
    payment_id          INTEGER PRIMARY KEY,
    invoice_id          INTEGER NOT NULL,
    payment_date        TEXT    NOT NULL
                        CHECK(date(payment_date) IS payment_date),
    amount              REAL    NOT NULL
                        CHECK(amount > 0),
    method              TEXT    NOT NULL
                        CHECK(method IN ('Check', 'Card', 'Cash', 'ACH')),
    reference_number    TEXT,
    FOREIGN KEY (invoice_id) REFERENCES Invoice(invoice_id) ON DELETE RESTRICT
);