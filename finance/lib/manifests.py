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


def import_indice_tsv(con: sqlite3.Connection, path: Path) -> dict:
    """The quarterly 'Índice' workbook exported as tab-separated text.
    Expected columns: Fecha, Empresa en la factura, Remitente, Asunto, Importe, Archivo, Carpeta, Buzón."""
    stats = {"rows": 0, "inserted": 0, "updated": 0, "skipped": 0}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = [p.strip() for p in line.rstrip("\n").split("\t")]
            if len(parts) < 6 or not parts[0][:4].isdigit():
                continue
            # tolerate the two shapes seen: with or without a separate 'Remitente' column
            if len(parts) >= 8:
                date, company, sender, subject, amount, file_name, folder, mailbox = parts[:8]
            else:
                date, company, subject, amount, file_name, folder = parts[:6]
                sender, mailbox = subject, None
            stats["rows"] += 1
            minor, cur = parse_amount(amount)
            existing = con.execute("SELECT id, amount_minor, entity_on_doc FROM document WHERE doc_date=? AND file_name=?",
                                   (date, file_name)).fetchone()
            if existing:
                con.execute("UPDATE document SET entity_on_doc=COALESCE(?, entity_on_doc), amount_minor=COALESCE(amount_minor, ?), currency=COALESCE(currency, ?) WHERE id=?",
                            (company or None, minor, cur, existing["id"]))
                stats["updated"] += 1
                continue
            con.execute(
                """INSERT INTO document(source, doc_date, mailbox, sender, subject, amount_minor, currency,
                   entity_on_doc, file_name, storage_path, content_hash)
                   VALUES('indice',?,?,?,?,?,?,?,?,?,?)""",
                (date, mailbox, fix_mojibake(sender), fix_mojibake(subject), minor, cur, company or None,
                 file_name, f"Facturas Vanesa/T3 2026 (julio a septiembre)/{folder}/{file_name}", _hash(date, file_name)),
            )
            stats["inserted"] += 1
    con.commit()
    return stats
