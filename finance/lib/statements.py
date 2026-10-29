"""Bank and card statement import from CSV exports.
Profiles map an institution's column names onto the ledger. Add a profile
rather than editing the code when a bank changes its export."""
from __future__ import annotations
import csv
import sqlite3
from datetime import datetime
from pathlib import Path
from .money import parse_amount, fix_mojibake

PROFILES = {
    # American Express Spain web export (CSV). Column names as of 2026; adjust if they move.
    "amex_es": {
        "date": ["Fecha", "Date"],
        "description": ["Descripción", "Description"],
        "amount": ["Importe", "Amount"],
        "date_formats": ["%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"],
        "sign": "positive_is_debit",   # Amex shows charges as positive numbers
        "currency": "EUR",
    },
    # CaixaBankNow movement export (CSV or Excel saved as CSV)
    "caixabank": {
        "date": ["Fecha", "F. Valor", "Fecha valor"],
        "description": ["Concepto", "Más datos", "Descripción"],
        "amount": ["Importe", "Importe (€)"],
        "date_formats": ["%d/%m/%Y", "%Y-%m-%d"],
        "sign": "negative_is_debit",   # bank statements show debits negative
        "currency": "EUR",
    },
    # Revolut Business CSV export
    "revolut": {
        "date": ["Date completed (UTC)", "Date started (UTC)", "Completed Date"],
        "description": ["Description", "Reference"],
        "amount": ["Amount", "Total amount"],
        "currency_col": ["Payment currency", "Currency"],
        "date_formats": ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"],
        "sign": "negative_is_debit",
        "currency": "EUR",
    },
}


def _pick(row: dict, names: list[str]) -> str | None:
    for n in names:
        for k in row:
            if k and k.strip().lower() == n.lower():
                return row[k]
    return None


def _date(s: str, fmts: list[str]) -> str:
    s = s.strip()
    for f in fmts:
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {s!r}")


def import_statement(con: sqlite3.Connection, path: Path, profile: str, account_code: str) -> dict:
    p = PROFILES[profile]
    acc = con.execute("SELECT a.id, a.entity_id FROM account a WHERE a.code=?", (account_code,)).fetchone()
    if not acc:
        raise SystemExit(f"unknown account {account_code}; add it to rules.toml")
    stats = {"rows": 0, "inserted": 0, "skipped": 0}
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        sample = fh.read(4096); fh.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        for row in csv.DictReader(fh, dialect=dialect):
            stats["rows"] += 1
            raw_date, desc, raw_amt = _pick(row, p["date"]), _pick(row, p["description"]), _pick(row, p["amount"])
            if not raw_date or raw_amt is None:
                stats["skipped"] += 1
                continue
            minor, cur = parse_amount(raw_amt)
            if minor is None:
                stats["skipped"] += 1
                continue
            cur = (_pick(row, p.get("currency_col", [])) or cur or p["currency"]).upper()
            debit = minor > 0 if p["sign"] == "positive_is_debit" else minor < 0
            ref = f"{profile}:{raw_date}:{raw_amt}:{(desc or '')[:40]}"
            if con.execute("SELECT 1 FROM txn WHERE bank_ref=?", (ref,)).fetchone():
                stats["skipped"] += 1
                continue
            con.execute(
                """INSERT INTO txn(txn_date, posted_date, account_id, entity_id, direction, amount_minor, currency,
                   description, status, bank_ref) VALUES(?,?,?,?,?,?,?,?,'settled',?)""",
                (_date(raw_date, p["date_formats"]), _date(raw_date, p["date_formats"]), acc["id"], acc["entity_id"],
                 "out" if debit else "in", abs(minor), cur, fix_mojibake(desc or ""), ref),
            )
            stats["inserted"] += 1
    con.commit()
    return stats
