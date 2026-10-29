"""Import the weekly receipt manifests produced by the Mac receipts tool
(Facturas Vanesa/manifest_*.csv) and the quarterly index export."""
from __future__ import annotations
import csv
import hashlib
import re
import sqlite3
from pathlib import Path
from .money import parse_amount, fix_mojibake


def _hash(*parts: str) -> str:
    return hashlib.sha256("|".join(p or "" for p in parts).encode()).hexdigest()[:16]


def import_manifest(con: sqlite3.Connection, path: Path, source: str = "manifest") -> dict:
    stats = {"rows": 0, "inserted": 0, "skipped": 0}
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            stats["rows"] += 1
            date = (row.get("date") or "").strip()
            if not date:
                stats["skipped"] += 1
                continue
            files = [f.strip() for f in (row.get("files") or "").split(";") if f.strip()]
            file_name = files[0] if files else _hash(date, row.get("from", ""), row.get("subject", ""))
            raw_amt = (row.get("amount") or "").strip()
            minor, cur = parse_amount(raw_amt)
            # The harvester splits on commas: "€2,232.37" arrives as "€2", "£3,750" as "£3".
            # A bare one or two digit figure with no decimals is unsafe: keep the string, drop the number.
            if minor is not None and re.fullmatch(r"[^\d]*\d{1,2}", fix_mojibake(raw_amt)):
                minor = None
            sender = fix_mojibake((row.get("from") or "").strip().strip('"'))
            subject = fix_mojibake((row.get("subject") or "").strip())
            try:
                con.execute(
                    """INSERT INTO document(source, doc_date, received_date, mailbox, sender, subject,
                       amount_minor, amount_raw, currency, file_name, storage_path, content_hash)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (source, date, date, row.get("mailbox"), sender, subject, minor, raw_amt or None, cur,
                     file_name, f"Facturas Vanesa/{row.get('week','')}/{file_name}",
                     _hash(date, file_name)),
                )
                stats["inserted"] += 1
            except sqlite3.IntegrityError:
                stats["skipped"] += 1
    con.commit()
    return stats


_FILE_RX = re.compile(r"\.(pdf|html?|csv|xlsx?|png|jpe?g|eml)$|_attachment(_\d+)?$|_\d+\.html$", re.IGNORECASE)
_MONEY_RX = re.compile(r"^(?:(?:€|£|\$|EUR|GBP|USD|HK\$)\s*)?[-+]?\d[\d.,\s]*\s*(?:€|£|\$|EUR|GBP|USD)?$", re.IGNORECASE)
_FOLDER_RX = re.compile(r"^\d (Emitidas|Recibidas|A nombre|Sin empresa)", re.IGNORECASE)
_MAILBOXES = {"liberalia", "brethil", "janfarrell", "icloud", "gmail"}


def _split_indice_row(parts: list[str]) -> dict | None:
    """Columns in the 'Recibidas' sheet drift when the sender is blank, so fields
    are recognised by shape rather than position."""
    if len(parts) < 5 or not re.match(r"\d{4}-\d{2}-\d{2}$", parts[0]):
        return None
    row = {"date": parts[0], "company": parts[1] or None, "file": None, "folder": None,
           "mailbox": None, "amount": None, "rest": []}
    for f in parts[2:]:
        if not f:
            continue
        if row["file"] is None and _FILE_RX.search(f) and " " not in f:
            row["file"] = f
        elif _FOLDER_RX.match(f):
            row["folder"] = f
        elif f.lower() in _MAILBOXES:
            row["mailbox"] = f
        elif row["amount"] is None and _MONEY_RX.match(f) and "_" not in f:
            row["amount"] = f
        else:
            row["rest"].append(f)
    if row["file"] is None:
        return None
    return row


def import_indice_tsv(con: sqlite3.Connection, path: Path) -> dict:
    """The quarterly 'Índice' workbook exported as tab-separated text. Only the
    'Recibidas' sheet is imported; 'Emitidas' rows are outgoing invoices (claims)."""
    stats = {"rows": 0, "inserted": 0, "updated": 0, "skipped": 0}
    section = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            raw = line.rstrip("\n")
            if raw and not raw.startswith("\t"):
                section = raw.strip()
                continue
            if section != "Recibidas":
                continue
            parts = [p.strip() for p in raw.split("\t")]
            while parts and parts[0] == "":
                parts = parts[1:]
            row = _split_indice_row(parts)
            if row is None:
                continue
            stats["rows"] += 1
            minor, cur = parse_amount(row["amount"]) if row["amount"] else (None, None)
            if minor is not None and re.fullmatch(r"[^\d]*\d{1,2}", fix_mojibake(row["amount"])):
                minor = None                      # same truncation guard as the manifests
            sender = fix_mojibake(row["rest"][0]) if row["rest"] else None
            subject = fix_mojibake(" | ".join(row["rest"][1:])) if len(row["rest"]) > 1 else sender
            company = row["company"] if row["company"] not in (None, "Sin empresa") else None
            existing = con.execute("SELECT id FROM document WHERE doc_date=? AND file_name=?",
                                   (row["date"], row["file"])).fetchone()
            if existing:
                con.execute("""UPDATE document SET entity_on_doc=COALESCE(entity_on_doc, ?),
                               amount_minor=COALESCE(amount_minor, ?), currency=COALESCE(currency, ?),
                               amount_raw=COALESCE(amount_raw, ?) WHERE id=?""",
                            (company, minor, cur, row["amount"], existing["id"]))
                stats["updated"] += 1
                continue
            con.execute(
                """INSERT INTO document(source, doc_date, mailbox, sender, subject, amount_minor, amount_raw, currency,
                   entity_on_doc, file_name, storage_path, content_hash)
                   VALUES('indice',?,?,?,?,?,?,?,?,?,?,?)""",
                (row["date"], row["mailbox"], sender, subject, minor, row["amount"], cur, company, row["file"],
                 f"Facturas Vanesa/T3 2026 (julio a septiembre)/{row['folder'] or ''}/{row['file']}",
                 _hash(row["date"], row["file"])),
            )
            stats["inserted"] += 1
    con.commit()
    return stats
