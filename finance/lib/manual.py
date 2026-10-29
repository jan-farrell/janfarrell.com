"""Hand-curated items (for example receipts read one by one) from a CSV with columns:
date,counterparty,description,amount,currency,bearer,category,recharge_to,trip_id,storage_path,notes
Amount may carry a sign or currency symbol. Rows whose (date, description, amount) already exist are skipped."""
from __future__ import annotations
import csv
import sqlite3
from pathlib import Path
from .money import parse_amount


def import_items(con: sqlite3.Connection, path: Path, source: str = "manual") -> dict:
    stats = {"rows": 0, "inserted": 0, "skipped": 0}
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            stats["rows"] += 1
            minor, cur = parse_amount(row.get("amount"))
            cur = (row.get("currency") or cur or "EUR").upper()
            if minor is None or not row.get("date"):
                stats["skipped"] += 1
                continue
            desc = (row.get("description") or "").strip()
            if con.execute("SELECT 1 FROM txn WHERE txn_date=? AND description=? AND amount_minor=? AND currency=?",
                           (row["date"], desc, abs(minor), cur)).fetchone():
                stats["skipped"] += 1
                continue
            cp = None
            if row.get("counterparty"):
                r = con.execute("SELECT id FROM counterparty WHERE name=?", (row["counterparty"],)).fetchone()
                if r is None:
                    con.execute("INSERT INTO counterparty(name) VALUES(?)", (row["counterparty"],))
                    r = con.execute("SELECT id FROM counterparty WHERE name=?", (row["counterparty"],)).fetchone()
                cp = r["id"]
            bearer = (row.get("bearer") or "JAN").strip()
            ent = con.execute("SELECT id FROM entity WHERE code=?", (bearer,)).fetchone()
            if ent is None:
                raise SystemExit(f"unknown bearer {bearer} in {path}")
            doc_id = None
            if row.get("storage_path"):
                cur_doc = con.execute("INSERT OR IGNORE INTO document(source, doc_date, subject, amount_minor, currency, file_name, storage_path, counterparty_id) VALUES(?,?,?,?,?,?,?,?)",
                                      (source, row["date"], desc, abs(minor), cur, Path(row["storage_path"]).name, row["storage_path"], cp))
                doc_id = con.execute("SELECT id FROM document WHERE doc_date=? AND file_name=?",
                                     (row["date"], Path(row["storage_path"]).name)).fetchone()["id"]
            recharge = (row.get("recharge_to") or "").strip() or None
            con.execute(
                """INSERT INTO txn(txn_date, entity_id, counterparty_id, direction, amount_minor, currency, description,
                   category, bearer_entity, recharge_to, recharge_status, status, document_id, trip_id, notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (row["date"], ent["id"], cp, "in" if minor < 0 else "out", abs(minor), cur, desc,
                 row.get("category") or None, bearer, recharge, "candidate" if recharge else "none",
                 "confirmed", doc_id, row.get("trip_id") or None, row.get("notes") or None),
            )
            stats["inserted"] += 1
    # A curated line supersedes any harvested line on the same document.
    sup = con.execute("""UPDATE txn SET status='cancelled', recharge_status=CASE WHEN recharge_status='candidate' THEN 'rejected' ELSE recharge_status END,
                         notes=COALESCE(notes||'; ','')||'superseded by curated item'
                         WHERE bank_ref IS NULL AND status<>'cancelled'
                           AND document_id IN (SELECT document_id FROM txn WHERE document_id IS NOT NULL AND notes IS NOT NULL AND trip_id IS NOT NULL)
                           AND trip_id IS NULL""").rowcount
    stats["superseded"] = sup
    con.commit()
    return stats
