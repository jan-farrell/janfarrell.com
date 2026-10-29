#!/usr/bin/env bash
# Rebuild the ledger from the inputs in data/in and write the standard reports to data/out.
# Idempotent: deletes and recreates the database. Usage: ./rebuild.sh [AS_OF_DATE]
set -euo pipefail
cd "$(dirname "$0")"
AS_OF="${1:-$(date +%F)}"
DB="${FIN_DB:-data/ledger.sqlite}"
rm -f "$DB" "$DB-wal" "$DB-shm"
export FIN_DB="$DB"
python3 fin.py init
ls data/in/manifest_*.csv >/dev/null 2>&1 && python3 fin.py import-manifests data/in/manifest_*.csv
for f in data/in/indice_*.tsv; do [ -e "$f" ] && python3 fin.py import-indice "$f"; done
for f in data/in/items_*.csv; do [ -e "$f" ] && python3 fin.py import-items "$f"; done
python3 fin.py classify
# Curated September travel and the Lords invoices supersede harvested lines in the same window.
python3 fin.py sql "UPDATE txn SET status='cancelled', recharge_status='rejected', notes=COALESCE(notes||'; ','')||'superseded by curated items' WHERE trip_id IS NULL AND bank_ref IS NULL AND status<>'cancelled' AND category LIKE 'travel.%' AND txn_date BETWEEN '2026-08-25' AND '2026-09-30'"
python3 fin.py sql "UPDATE txn SET status='cancelled', recharge_status='rejected', notes=COALESCE(notes||'; ','')||'superseded by curated Lords invoices' WHERE trip_id IS NULL AND bank_ref IS NULL AND status<>'cancelled' AND counterparty_id=(SELECT id FROM counterparty WHERE name='House of Lords catering')"
for f in data/in/plan_*.toml; do [ -e "$f" ] && python3 fin.py load-plan "$f"; done
# Documentary GBP rate until the ECB feed is reachable (Iberia ticket J6Y11, 28 Aug 2026).
python3 fin.py fx-set 2026-08-28 GBP 0.8555
python3 fin.py fx || true
mkdir -p data/out
python3 fin.py recharge SQUARETRADE 2026-09-01 2026-09-30 > data/out/recharge_squaretrade_2026-09.md
python3 fin.py recharge SQUARETRADE 2026-06-01 2026-07-31 > data/out/recharge_squaretrade_HoL_prepayments.md
python3 fin.py recharge SQUARETRADE 2026-10-01 2026-10-31 > data/out/recharge_squaretrade_2026-10_preview.md
python3 fin.py forecast "$AS_OF" 10 > "data/out/forecast_${AS_OF}.md"
python3 fin.py burn 4 > data/out/burn.md
echo "reports in data/out"
