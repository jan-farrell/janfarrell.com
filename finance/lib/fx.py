"""EUR reference rates from the ECB, cached in fx_rate. Conversion picks the
latest rate on or before the transaction date."""
from __future__ import annotations
import sqlite3
import urllib.request
import xml.etree.ElementTree as ET

ECB_DAILY = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
ECB_90D = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
NS = {"g": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
WANT = {"GBP", "USD", "HKD", "CHF"}


def refresh(con: sqlite3.Connection, history: bool = True) -> int:
    url = ECB_90D if history else ECB_DAILY
    with urllib.request.urlopen(url, timeout=30) as resp:
        root = ET.fromstring(resp.read())
    n = 0
    for day in root.iterfind(".//g:Cube[@time]", NS):
        d = day.get("time")
        for c in day.iterfind("g:Cube", NS):
            if c.get("currency") in WANT:
                con.execute("INSERT OR REPLACE INTO fx_rate(rate_date, quote, rate) VALUES(?,?,?)",
                            (d, c.get("currency"), float(c.get("rate"))))
                n += 1
    con.commit()
    return n


def rate(con: sqlite3.Connection, quote: str, on: str) -> float | None:
    if quote == "EUR":
        return 1.0
    row = con.execute("SELECT rate FROM fx_rate WHERE quote=? AND rate_date<=? ORDER BY rate_date DESC LIMIT 1",
                      (quote, on)).fetchone()
    if row is None:
        row = con.execute("SELECT rate FROM fx_rate WHERE quote=? ORDER BY rate_date ASC LIMIT 1", (quote,)).fetchone()
    return row["rate"] if row else None


def to_eur_minor(con: sqlite3.Connection, minor: int, cur: str, on: str) -> tuple[int | None, float | None]:
    r = rate(con, cur, on)
    if r is None:
        return None, None
    return round(minor / r), r


def fill_missing(con: sqlite3.Connection) -> int:
    n = 0
    for t in con.execute("SELECT id, amount_minor, currency, txn_date FROM txn WHERE amount_eur_minor IS NULL").fetchall():
        eur, r = to_eur_minor(con, t["amount_minor"], t["currency"], t["txn_date"])
        if eur is not None:
            con.execute("UPDATE txn SET amount_eur_minor=?, fx_rate=? WHERE id=?", (eur, r, t["id"]))
            n += 1
    con.commit()
    return n
