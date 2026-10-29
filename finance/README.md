# Finance: a ledger that supervises the spend

Private finance tooling for Jan Farrell: Brethil Investment (holding), Farrell Import (work company that invoices Square Trade Limited), Liberalia (operating business, kept separate), and personal spend. Built on 27 October 2026. The code is public because this repository is served by GitHub Pages. **No data is committed**: `finance/.gitignore` excludes `data/`, every database and every CSV, and `_config.yml` keeps `finance/` off the published site. Move this folder to the private `claud` repository before adding anything beyond code.

## What it does today

1. **Ingests** the weekly receipt manifests the Mac already produces (`Facturas Vanesa/manifest_*.csv`) and the quarterly index exported as TSV. Hand-read receipts go in through a small CSV.
2. **Classifies** every document by counterparty and rule (`rules/rules.toml`): who bears the cost (Jan, Brethil, Farrell Import, Liberalia), what it is, and whether it is a candidate to recharge to a client. Thread repeats (Re:, Fwd:) are cancelled as duplicates. Harvested amounts that were split on a comma ("€2" for €2,232.37) are dropped rather than trusted.
3. **Reports**: a recharge schedule per client and period, an N-day forecast of outgoings and ingoings (dated one-offs, standing commitments, open receivables), and monthly burn by entity and category.
4. **Stores** everything in one SQLite file with traceability to the source receipt.

## Why SQLite, and when to move

SQLite is the right database for this for now: one user, one Mac, a few thousand rows a year, transactions, constraints, zero operations, Python's standard library, and the file can be backed up by copying it. It keeps financial data on the machine where the receipts already are.

Move to PostgreSQL (Supabase or Neon) only when one of these becomes true: a second writer (Vanesa, a private secretary) needs live access, a web dashboard is wanted, or Open Banking feeds start pushing hourly. The schema is plain SQL and ports in an afternoon. Do not use Notion, Airtable or a spreadsheet as the ledger: none of them enforce the constraints that stop double counting.

Keep the database outside Dropbox (for example `~/.claud-data/ledger.sqlite`) and export CSV reports into Dropbox. Syncing a live SQLite file through Dropbox risks corruption.

## Running it

```sh
cd finance
python3 fin.py init                                          # schema + seed from rules/rules.toml
python3 fin.py import-manifests "~/Dropbox/J Farrell/Facturas Vanesa/manifest_*.csv"
python3 fin.py import-indice data/in/indice_T3_2026.tsv      # quarterly index, exported as TSV
python3 fin.py import-items data/in/items_2026-09_travel.csv # receipts read one by one
python3 fin.py classify                                      # documents -> ledger, cancel duplicates
python3 fin.py fx                                            # ECB rates (needs network) and EUR fill
python3 fin.py load-plan data/in/plan_2026-10-27.toml        # dated payments, recurring, receivables
python3 fin.py recharge SQUARETRADE 2026-09-01 2026-09-30
python3 fin.py forecast 2026-10-27 10
python3 fin.py burn 4
```

Python 3.11 or later, standard library only. `FIN_DB=/path/to/ledger.sqlite` overrides the database location.

## Data model (short)

`entity` (who pays or should pay) → `account` (cards and banks) → `txn` (one row per money movement, with `bearer_entity`, `recharge_to`, `recharge_status`, `trip_id`) ← `document` (the receipt). `claim` is an outgoing invoice to a client with its paid amount. `scheduled` and `recurring` feed the forecast. `rule` and `counterparty` hold the classification, loaded from `rules/rules.toml`. Money is integer minor units. See `db/schema.sql`.

## Connections: what is real

See `docs/connections.md`. Short version: Amex and CaixaBank are reachable through a licensed Open Banking (PSD2) aggregator or by statement export, never by scraping a login. Uber, Iberia and British Airways have no consumer transaction API; their receipts arrive by email and the Mac harvester already files them. Revolut Business and Wise have official APIs.

## Roadmap

- **Now**: statement import for Amex and CaixaBank (`lib/statements.py` profiles are written; the first real export will need the column names checked), reconciliation of receipts against statement lines, a weekly "unclassified and unreceipted" list.
- **Next**: Open Banking feed for Amex and CaixaBank through one aggregator; a nightly run on the Mac (launchd, like `claud-sync.sh`) that imports, classifies and writes the three reports into `Claud/Finance/`; the Instauratio brief reads the forecast.
- **Then**: invoice generation for Farrell Import and Brethil (fee + expenses annex with receipt links), burn-rate targets per entity with alerts, and the Liberalia books kept out of Jan's personal figures by default.

## Rules of the house

- Amounts come from documents, never from memory. Where two documents disagree, the one addressed to the payer wins and the discrepancy is noted.
- A recharge candidate is not a claim until a human approves it. The report says "candidate".
- Personal spend invoiced to a company (a family hotel on Farrell Import's name) is flagged, not hidden.
