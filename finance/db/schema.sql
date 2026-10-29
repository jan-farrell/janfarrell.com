-- Jan Farrell finance ledger. SQLite 3.35+ (RETURNING, generated columns).
-- Money is stored as integer minor units (cents, pence) to avoid float drift.
-- Every row that came from a source keeps the source path so a figure can be
-- traced back to the receipt, statement line or email it came from.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- Who pays and who should pay. Jan personally, his companies, and the clients
-- that reimburse him.
CREATE TABLE IF NOT EXISTS entity (
  id            INTEGER PRIMARY KEY,
  code          TEXT NOT NULL UNIQUE,          -- JAN, BRETHIL, FARRELL_IMPORT, LIBERALIA, SQUARETRADE ...
  name          TEXT NOT NULL,
  kind          TEXT NOT NULL CHECK (kind IN ('person','company','client','other')),
  country       TEXT,                          -- ISO 3166-1 alpha-2
  tax_id        TEXT,                          -- CIF/NIF, VAT number
  home_currency TEXT NOT NULL DEFAULT 'EUR',
  notes         TEXT
);

-- Bank accounts, cards and wallets. One row per statement source.
CREATE TABLE IF NOT EXISTS account (
  id          INTEGER PRIMARY KEY,
  entity_id   INTEGER NOT NULL REFERENCES entity(id),
  code        TEXT NOT NULL UNIQUE,            -- AMEX_JAN, CAIXA_FARRELL_IMPORT ...
  provider    TEXT NOT NULL,                   -- American Express, CaixaBank, Revolut, Wise, Curve ...
  kind        TEXT NOT NULL CHECK (kind IN ('bank','card','wallet','cash')),
  currency    TEXT NOT NULL,
  iban_last4  TEXT,
  feed        TEXT NOT NULL DEFAULT 'manual' CHECK (feed IN ('manual','csv','openbanking','api','email')),
  notes       TEXT
);

-- Vendors, payees and payers, normalised once so rules attach to one row.
CREATE TABLE IF NOT EXISTS counterparty (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL UNIQUE,        -- canonical name, e.g. "Uber"
  match_pattern   TEXT,                        -- case-insensitive regex applied to sender/subject/description
  default_entity  TEXT REFERENCES entity(code), -- who normally bears this cost
  default_category TEXT,
  default_recharge_to TEXT REFERENCES entity(code), -- client normally recharged, or NULL
  country         TEXT,
  notes           TEXT
);

-- A source document: receipt, invoice, e-ticket, booking, statement, email.
CREATE TABLE IF NOT EXISTS document (
  id              INTEGER PRIMARY KEY,
  source          TEXT NOT NULL,               -- manifest, indice, amex_csv, caixa_csv, manual
  doc_date        TEXT NOT NULL,               -- ISO date the document carries
  received_date   TEXT,                        -- email date if different
  mailbox         TEXT,                        -- liberalia, brethil, janfarrell, iCloud, Gmail
  sender          TEXT,
  subject         TEXT,
  doc_type        TEXT CHECK (doc_type IN ('invoice','receipt','eticket','booking','statement','credit_note','notice','other')),
  amount_minor    INTEGER,                     -- as printed on the document, minor units
  amount_raw      TEXT,                        -- the string as harvested, kept when parsing was unsafe
  currency        TEXT,
  entity_on_doc   TEXT,                        -- company named on the document, as detected upstream
  file_name       TEXT,
  storage_path    TEXT,                        -- Dropbox path_display or local path
  content_hash    TEXT,                        -- sha256 of file when available
  counterparty_id INTEGER REFERENCES counterparty(id),
  imported_at     TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (doc_date, file_name)
);

-- The ledger. One row per money movement, expected or actual.
CREATE TABLE IF NOT EXISTS txn (
  id              INTEGER PRIMARY KEY,
  txn_date        TEXT NOT NULL,               -- date of the spend or receipt
  posted_date     TEXT,                        -- date it hit the account
  account_id      INTEGER REFERENCES account(id),
  entity_id       INTEGER NOT NULL REFERENCES entity(id),      -- who actually paid / is paying
  counterparty_id INTEGER REFERENCES counterparty(id),
  direction       TEXT NOT NULL CHECK (direction IN ('out','in')),
  amount_minor    INTEGER NOT NULL CHECK (amount_minor >= 0),
  currency        TEXT NOT NULL,
  amount_eur_minor INTEGER,                    -- converted at fx_rate for reporting
  fx_rate         REAL,
  description     TEXT,
  category        TEXT,                        -- travel.flight, travel.hotel, travel.taxi, events, software, legal, tax, fees, personal ...
  bearer_entity   TEXT REFERENCES entity(code), -- who should ultimately bear it (may differ from entity_id)
  recharge_to     TEXT REFERENCES entity(code), -- client to recharge, or NULL
  recharge_status TEXT NOT NULL DEFAULT 'none' CHECK (recharge_status IN ('none','candidate','claimed','paid','rejected')),
  claim_id        INTEGER REFERENCES claim(id),
  status          TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('expected','confirmed','settled','cancelled')),
  document_id     INTEGER REFERENCES document(id),
  bank_ref        TEXT,
  trip_id         TEXT,                        -- groups a journey: LON-2026-09-10 etc.
  notes           TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS txn_date_idx ON txn(txn_date);
CREATE INDEX IF NOT EXISTS txn_recharge_idx ON txn(recharge_to, recharge_status);

-- A recharge claim or outgoing invoice to a client (Farrell Import or Brethil
-- invoicing SquareTrade, for example). Lines link back to ledger rows.
CREATE TABLE IF NOT EXISTS claim (
  id            INTEGER PRIMARY KEY,
  issuer        TEXT NOT NULL REFERENCES entity(code),
  client        TEXT NOT NULL REFERENCES entity(code),
  invoice_no    TEXT,
  invoice_date  TEXT,
  period_start  TEXT,
  period_end    TEXT,
  currency      TEXT NOT NULL DEFAULT 'EUR',
  fee_minor     INTEGER NOT NULL DEFAULT 0,    -- the service fee part
  expenses_minor INTEGER NOT NULL DEFAULT 0,   -- the recharged expenses part
  total_minor   INTEGER,
  status        TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sent','part_paid','paid','disputed')),
  paid_minor    INTEGER NOT NULL DEFAULT 0,
  due_date      TEXT,
  storage_path  TEXT,
  notes         TEXT
);

-- Standing commitments used by the forecast: subscriptions, rent, retainers,
-- payroll, taxes. Confidence is how sure we are of amount and date.
CREATE TABLE IF NOT EXISTS recurring (
  id              INTEGER PRIMARY KEY,
  entity_id       INTEGER NOT NULL REFERENCES entity(id),
  counterparty_id INTEGER REFERENCES counterparty(id),
  label           TEXT NOT NULL,
  direction       TEXT NOT NULL CHECK (direction IN ('out','in')),
  amount_minor    INTEGER NOT NULL,
  currency        TEXT NOT NULL,
  cadence         TEXT NOT NULL CHECK (cadence IN ('weekly','monthly','quarterly','annual','irregular')),
  anchor_day      INTEGER,                     -- day of month for monthly
  next_due        TEXT,
  confidence      TEXT NOT NULL DEFAULT 'medium' CHECK (confidence IN ('high','medium','low')),
  category        TEXT,
  active          INTEGER NOT NULL DEFAULT 1,
  source          TEXT,
  notes           TEXT
);

-- One-off dated payments that are known in advance (a capital call, a wire,
-- an invoice with a due date). The forecast merges these with recurring rows
-- and with expected ledger rows.
CREATE TABLE IF NOT EXISTS scheduled (
  id            INTEGER PRIMARY KEY,
  entity_id     INTEGER NOT NULL REFERENCES entity(id),
  label         TEXT NOT NULL,
  direction     TEXT NOT NULL CHECK (direction IN ('out','in')),
  amount_minor  INTEGER,                       -- NULL when the amount is not yet known
  currency      TEXT,
  due_date      TEXT NOT NULL,
  confidence    TEXT NOT NULL DEFAULT 'medium' CHECK (confidence IN ('high','medium','low')),
  category      TEXT,
  source        TEXT,                          -- Todoist id, email, brief
  done          INTEGER NOT NULL DEFAULT 0,
  notes         TEXT
);

-- Classification rules, applied in priority order (lowest number first).
-- A rule matches when every non-NULL condition matches.
CREATE TABLE IF NOT EXISTS rule (
  id              INTEGER PRIMARY KEY,
  priority        INTEGER NOT NULL DEFAULT 100,
  name            TEXT NOT NULL,
  match_sender    TEXT,                        -- regex, case-insensitive
  match_subject   TEXT,
  match_mailbox   TEXT,
  match_entity_on_doc TEXT,
  set_counterparty TEXT,
  set_category    TEXT,
  set_bearer      TEXT REFERENCES entity(code),
  set_recharge_to TEXT REFERENCES entity(code),
  set_doc_type    TEXT,
  set_ignore      INTEGER NOT NULL DEFAULT 0,  -- 1 = not a money document (booking notice, internal chat)
  notes           TEXT
);

-- Daily FX, EUR base. Filled from the ECB reference rates.
CREATE TABLE IF NOT EXISTS fx_rate (
  rate_date TEXT NOT NULL,
  quote     TEXT NOT NULL,                     -- GBP, USD, HKD
  rate      REAL NOT NULL,                     -- 1 EUR = rate QUOTE
  PRIMARY KEY (rate_date, quote)
);

-- Convenience views -----------------------------------------------------------

CREATE VIEW IF NOT EXISTS v_recharge_candidates AS
SELECT t.id, t.txn_date, t.trip_id, e.code AS paid_by, t.recharge_to, t.category,
       c.name AS counterparty, t.description,
       t.amount_minor / 100.0 AS amount, t.currency,
       t.amount_eur_minor / 100.0 AS amount_eur,
       t.recharge_status, d.storage_path
FROM txn t
JOIN entity e ON e.id = t.entity_id
LEFT JOIN counterparty c ON c.id = t.counterparty_id
LEFT JOIN document d ON d.id = t.document_id
WHERE t.recharge_to IS NOT NULL AND t.status<>'cancelled' AND t.recharge_status IN ('candidate','claimed');

CREATE VIEW IF NOT EXISTS v_monthly_burn AS
SELECT substr(t.txn_date,1,7) AS month, e.code AS entity, t.category,
       SUM(CASE WHEN t.direction='out' THEN t.amount_eur_minor ELSE 0 END)/100.0 AS out_eur,
       SUM(CASE WHEN t.direction='in'  THEN t.amount_eur_minor ELSE 0 END)/100.0 AS in_eur,
       COUNT(*) AS n
FROM txn t JOIN entity e ON e.id = t.entity_id
WHERE t.status <> 'cancelled'
GROUP BY 1,2,3;

CREATE VIEW IF NOT EXISTS v_unclassified AS
SELECT d.* FROM document d
LEFT JOIN txn t ON t.document_id = d.id
WHERE t.id IS NULL AND d.amount_minor IS NOT NULL;
