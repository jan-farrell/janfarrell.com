"""Load dated one-off payments and standing commitments from TOML plan files
in data/in/. These are the forecast's inputs alongside the ledger."""
from __future__ import annotations
import sqlite3
import tomllib
from pathlib import Path
from .money import parse_amount


def load_plan(con: sqlite3.Connection, path: Path) -> dict:
    with open(path, "rb") as fh:
        cfg = tomllib.load(fh)
    stats = {"scheduled": 0, "recurring": 0}
    for s in cfg.get("scheduled", []):
        minor, cur = parse_amount(s.get("amount")) if s.get("amount") else (None, None)
        cur = s.get("currency", cur)
        ent = con.execute("SELECT id FROM entity WHERE code=?", (s["entity"],)).fetchone()
        if not ent:
            raise SystemExit(f"scheduled '{s['label']}' names unknown entity {s['entity']}")
        existing = con.execute("SELECT id FROM scheduled WHERE label=? AND due_date=?", (s["label"], s["due"])).fetchone()
        vals = (ent["id"], s["label"], s.get("direction", "out"), minor, cur, s["due"],
                s.get("confidence", "medium"), s.get("category"), s.get("source"), int(s.get("done", False)), s.get("notes"))
        if existing:
            con.execute("""UPDATE scheduled SET entity_id=?,label=?,direction=?,amount_minor=?,currency=?,due_date=?,
                           confidence=?,category=?,source=?,done=?,notes=? WHERE id=?""", vals + (existing["id"],))
        else:
            con.execute("""INSERT INTO scheduled(entity_id,label,direction,amount_minor,currency,due_date,confidence,
                           category,source,done,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?)""", vals)
        stats["scheduled"] += 1
    for r in cfg.get("recurring", []):
        minor, cur = parse_amount(r["amount"])
        cur = r.get("currency", cur)
        ent = con.execute("SELECT id FROM entity WHERE code=?", (r["entity"],)).fetchone()
        if not ent:
            raise SystemExit(f"recurring '{r['label']}' names unknown entity {r['entity']}")
        cp = None
        if r.get("counterparty"):
            row = con.execute("SELECT id FROM counterparty WHERE name=?", (r["counterparty"],)).fetchone()
            cp = row["id"] if row else None
        existing = con.execute("SELECT id FROM recurring WHERE label=?", (r["label"],)).fetchone()
        vals = (ent["id"], cp, r["label"], r.get("direction", "out"), minor, cur, r.get("cadence", "monthly"),
                r.get("anchor_day"), r.get("next_due"), r.get("confidence", "medium"), r.get("category"),
                int(r.get("active", True)), r.get("source"), r.get("notes"))
        if existing:
            con.execute("""UPDATE recurring SET entity_id=?,counterparty_id=?,label=?,direction=?,amount_minor=?,currency=?,
                           cadence=?,anchor_day=?,next_due=?,confidence=?,category=?,active=?,source=?,notes=? WHERE id=?""",
                        vals + (existing["id"],))
        else:
            con.execute("""INSERT INTO recurring(entity_id,counterparty_id,label,direction,amount_minor,currency,cadence,
                           anchor_day,next_due,confidence,category,active,source,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", vals)
        stats["recurring"] += 1
    for c in cfg.get("claim", []):
        total, cur = parse_amount(c["total"])
        paid, _ = parse_amount(c.get("paid", "0"))
        existing = con.execute("SELECT id FROM claim WHERE issuer=? AND invoice_no=?", (c["issuer"], c["invoice_no"])).fetchone()
        vals = (c["issuer"], c["client"], c["invoice_no"], c.get("date"), c.get("period_start"), c.get("period_end"),
                c.get("currency", cur or "EUR"), total, c.get("status", "sent"), paid or 0, c.get("due"), c.get("notes"))
        if existing:
            con.execute("""UPDATE claim SET issuer=?,client=?,invoice_no=?,invoice_date=?,period_start=?,period_end=?,currency=?,
                           total_minor=?,status=?,paid_minor=?,due_date=?,notes=? WHERE id=?""", vals + (existing["id"],))
        else:
            con.execute("""INSERT INTO claim(issuer,client,invoice_no,invoice_date,period_start,period_end,currency,total_minor,
                           status,paid_minor,due_date,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", vals)
        stats["claim"] = stats.get("claim", 0) + 1
    con.commit()
    return stats
