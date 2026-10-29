"""SQLite connection, schema and seed data."""
from __future__ import annotations
import sqlite3
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SCHEMA = HERE / "db" / "schema.sql"
RULES = HERE / "rules" / "rules.toml"
DEFAULT_DB = HERE / "data" / "ledger.sqlite"


def connect(path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    seed(con)
    con.commit()


def load_rules_file(path: Path | str = RULES) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def seed(con: sqlite3.Connection, rules_path: Path | str = RULES) -> None:
    cfg = load_rules_file(rules_path)
    for e in cfg.get("entity", []):
        con.execute(
            """INSERT INTO entity(code,name,kind,country,tax_id,home_currency,notes)
               VALUES(:code,:name,:kind,:country,:tax_id,:home_currency,:notes)
               ON CONFLICT(code) DO UPDATE SET name=excluded.name, kind=excluded.kind,
               country=excluded.country, tax_id=excluded.tax_id,
               home_currency=excluded.home_currency, notes=excluded.notes""",
            {"country": None, "tax_id": None, "home_currency": "EUR", "notes": None, **e},
        )
    for a in cfg.get("account", []):
        ent = con.execute("SELECT id FROM entity WHERE code=?", (a["entity"],)).fetchone()
        if not ent:
            raise SystemExit(f"account {a['code']} refers to unknown entity {a['entity']}")
        con.execute(
            """INSERT INTO account(entity_id,code,provider,kind,currency,iban_last4,feed,notes)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(code) DO UPDATE SET provider=excluded.provider, kind=excluded.kind,
               currency=excluded.currency, feed=excluded.feed, notes=excluded.notes""",
            (ent["id"], a["code"], a["provider"], a["kind"], a["currency"],
             a.get("iban_last4"), a.get("feed", "manual"), a.get("notes")),
        )
    for c in cfg.get("counterparty", []):
        con.execute(
            """INSERT INTO counterparty(name,match_pattern,default_entity,default_category,default_recharge_to,country,notes)
               VALUES(:name,:match,:bearer,:category,:recharge_to,:country,:notes)
               ON CONFLICT(name) DO UPDATE SET match_pattern=excluded.match_pattern,
               default_entity=excluded.default_entity, default_category=excluded.default_category,
               default_recharge_to=excluded.default_recharge_to, notes=excluded.notes""",
            {"match": None, "bearer": None, "category": None, "recharge_to": None,
             "country": None, "notes": None, **c},
        )
    con.execute("DELETE FROM rule")
    for r in cfg.get("rule", []):
        con.execute(
            """INSERT INTO rule(priority,name,match_sender,match_subject,match_mailbox,match_entity_on_doc,
               set_counterparty,set_category,set_bearer,set_recharge_to,set_doc_type,set_ignore,notes)
               VALUES(:priority,:name,:match_sender,:match_subject,:match_mailbox,:match_entity_on_doc,
               :set_counterparty,:set_category,:set_bearer,:set_recharge_to,:set_doc_type,:set_ignore,:notes)""",
            {"priority": 100, "match_sender": None, "match_subject": None, "match_mailbox": None,
             "match_entity_on_doc": None, "set_counterparty": None, "set_category": None,
             "set_bearer": None, "set_recharge_to": None, "set_doc_type": None,
             "set_ignore": 0, "notes": None, **r},
        )
    con.commit()


def entity_id(con: sqlite3.Connection, code: str) -> int:
    row = con.execute("SELECT id FROM entity WHERE code=?", (code,)).fetchone()
    if not row:
        raise KeyError(f"unknown entity {code}")
    return row["id"]
