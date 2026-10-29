"""Classification: documents -> ledger rows, by counterparty match then rules."""
from __future__ import annotations
import re
import sqlite3
from datetime import date
from .money import fix_mojibake


def _rx(pattern: str | None):
    return re.compile(pattern, re.IGNORECASE) if pattern else None


def load(con: sqlite3.Connection):
    cps = [dict(r) for r in con.execute("SELECT * FROM counterparty")]
    for c in cps:
        c["_rx"] = _rx(c["match_pattern"])
    rules = [dict(r) for r in con.execute("SELECT * FROM rule ORDER BY priority, id")]
    for r in rules:
        for k in ("match_sender", "match_subject", "match_mailbox", "match_entity_on_doc"):
            r["_" + k] = _rx(r[k])
    return cps, rules


def match_counterparty(cps, sender: str, subject: str):
    hay_sender = fix_mojibake(sender or "")
    hay_subject = fix_mojibake(subject or "")
    for c in cps:
        if c["_rx"] and (c["_rx"].search(hay_sender) or c["_rx"].search(hay_subject)):
            return c
    return None


def classify_document(doc: sqlite3.Row, cps, rules) -> dict | None:
    """Return a dict of ledger fields, or None when the document is not money."""
    sender = fix_mojibake(doc["sender"] or "")
    subject = fix_mojibake(doc["subject"] or "")
    out = {"counterparty_id": None, "category": None, "bearer": None,
           "recharge_to": None, "doc_type": doc["doc_type"], "ignore": False, "rules": []}

    cp = match_counterparty(cps, sender, subject)
    if cp:
        out["counterparty_id"] = cp["id"]
        out["category"] = cp["default_category"]
        out["bearer"] = cp["default_entity"]
        out["recharge_to"] = cp["default_recharge_to"]

    for r in rules:
        conds = [
            (r["_match_sender"], sender),
            (r["_match_subject"], subject),
            (r["_match_mailbox"], doc["mailbox"] or ""),
            (r["_match_entity_on_doc"], doc["entity_on_doc"] or ""),
        ]
        active = [(rx, hay) for rx, hay in conds if rx is not None]
        if not active or not all(rx.search(hay) for rx, hay in active):
            continue
        out["rules"].append(r["name"])
        if r["set_ignore"]:
            out["ignore"] = True
            return out
        # rule 30 is currency-conditional: GBP Ubers only
        if r["priority"] == 30 and (doc["currency"] or "") != "GBP":
            continue
        if r["set_category"] and (out["category"] is None or r["priority"] < 50):
            out["category"] = r["set_category"]
        if r["set_bearer"]:
            out["bearer"] = r["set_bearer"]
        if r["set_recharge_to"]:
            out["recharge_to"] = r["set_recharge_to"]
        if r["set_doc_type"]:
            out["doc_type"] = r["set_doc_type"]
    return out


def classify_all(con: sqlite3.Connection, only_new: bool = True) -> dict:
    """Create txn rows for documents that carry an amount and are not ignored."""
    cps, rules = load(con)
    q = "SELECT * FROM document"
    if only_new:
        q += " WHERE id NOT IN (SELECT document_id FROM txn WHERE document_id IS NOT NULL)"
    stats = {"seen": 0, "ignored": 0, "no_amount": 0, "created": 0, "unmatched": 0}
    for doc in con.execute(q).fetchall():
        stats["seen"] += 1
        c = classify_document(doc, cps, rules)
        if c["doc_type"] != doc["doc_type"] or c["counterparty_id"] != doc["counterparty_id"]:
            con.execute("UPDATE document SET doc_type=?, counterparty_id=? WHERE id=?",
                        (c["doc_type"], c["counterparty_id"], doc["id"]))
        if c["ignore"]:
            stats["ignored"] += 1
            continue
        if doc["amount_minor"] is None:
            stats["no_amount"] += 1
            continue
        if c["counterparty_id"] is None:
            stats["unmatched"] += 1
        bearer = c["bearer"] or "JAN"
        ent = con.execute("SELECT id FROM entity WHERE code=?", (bearer,)).fetchone()
        direction = "in" if (doc["amount_minor"] < 0 or c["doc_type"] == "credit_note"
                             or (c["category"] or "").startswith("income")) else "out"
        con.execute(
            """INSERT INTO txn(txn_date, entity_id, counterparty_id, direction, amount_minor, currency,
               description, category, bearer_entity, recharge_to, recharge_status, status, document_id, notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (doc["doc_date"], ent["id"], c["counterparty_id"], direction, abs(doc["amount_minor"]),
             doc["currency"] or "EUR", fix_mojibake(doc["subject"] or doc["sender"] or ""), c["category"],
             bearer, c["recharge_to"], "candidate" if c["recharge_to"] else "none",
             "confirmed", doc["id"], "; ".join(c["rules"]) or None),
        )
        stats["created"] += 1
    con.commit()
    return stats


_THREAD = re.compile(r"^\s*(re|fwd?|aw|rv)\s*:", re.IGNORECASE)


def dedupe(con: sqlite3.Connection, window_days: int = 45) -> int:
    """Later emails in the same thread quote the same figure (Re:, Fwd:). Cancel the
    repeats: same amount, same currency, same counterparty or sender stem, within the window."""
    n = 0
    rows = con.execute("""SELECT t.id, t.txn_date, t.amount_minor, t.currency, t.counterparty_id, t.description,
                                 d.sender FROM txn t LEFT JOIN document d ON d.id=t.document_id
                          WHERE t.status<>'cancelled' AND t.bank_ref IS NULL ORDER BY t.txn_date, t.id""").fetchall()
    seen: dict[tuple, sqlite3.Row] = {}
    for r in rows:
        stem = re.sub(r"\W+", " ", (r["description"] or "")).lower()
        stem = _THREAD.sub("", stem).strip()[:40]
        key = (r["amount_minor"], r["currency"], r["counterparty_id"] or (r["sender"] or "")[:20].lower())
        prev = seen.get(key)
        if prev is not None:
            gap = (date.fromisoformat(r["txn_date"]) - date.fromisoformat(prev["txn_date"])).days
            prev_stem = _THREAD.sub("", re.sub(r"\W+", " ", (prev["description"] or "")).lower()).strip()[:40]
            threaded = _THREAD.match(r["description"] or "") is not None or stem == prev_stem
            if gap <= window_days and threaded:
                con.execute("UPDATE txn SET status='cancelled', notes=COALESCE(notes||'; ','')||? WHERE id=?",
                            (f"duplicate of txn {prev['id']}", r["id"]))
                n += 1
                continue
        seen[key] = r
    con.commit()
    return n
