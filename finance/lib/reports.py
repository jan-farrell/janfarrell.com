"""Reports: recharge schedule, N-day forecast, monthly burn. Markdown out."""
from __future__ import annotations
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from .money import fmt
from . import fx


def _eur(con, minor, cur, on):
    e, _ = fx.to_eur_minor(con, minor, cur, on)
    return e


def recharge(con: sqlite3.Connection, client: str, start: str, end: str,
             statuses=("candidate", "claimed")) -> str:
    rows = con.execute(
        """SELECT t.*, c.name AS cp, e.code AS bearer_code, d.storage_path, d.subject
           FROM txn t LEFT JOIN counterparty c ON c.id=t.counterparty_id
           JOIN entity e ON e.id=t.entity_id LEFT JOIN document d ON d.id=t.document_id
           WHERE t.recharge_to=? AND t.txn_date BETWEEN ? AND ? AND t.status<>'cancelled' AND t.recharge_status IN (%s)
           ORDER BY t.trip_id, t.txn_date, t.category""" % ",".join("?" * len(statuses)),
        (client, start, end, *statuses)).fetchall()
    out = [f"# Recharge to {client}: {start} to {end}", ""]
    if not rows:
        out.append("No candidate lines in this period.")
        return "\n".join(out)
    by_trip = defaultdict(list)
    for r in rows:
        by_trip[r["trip_id"] or "(no trip)"].append(r)
    grand = defaultdict(int)
    grand_eur = 0
    missing_fx = False
    for trip, items in by_trip.items():
        out += [f"## {trip}", "", "| Date | Category | Counterparty | Description | Amount | EUR | Paid by | Status | Source |",
                "|---|---|---|---|---:|---:|---|---|---|"]
        sub = defaultdict(int)
        for r in items:
            eur = r["amount_eur_minor"] or _eur(con, r["amount_minor"], r["currency"], r["txn_date"])
            if eur is None:
                missing_fx = True
            sub[r["currency"]] += r["amount_minor"]
            grand[r["currency"]] += r["amount_minor"]
            grand_eur += eur or 0
            out.append(f"| {r['txn_date']} | {r['category'] or ''} | {r['cp'] or ''} | {(r['description'] or '')[:60]} | "
                       f"{fmt(r['amount_minor'], r['currency'])} | {fmt(eur, 'EUR') if eur is not None else '?'} | "
                       f"{r['bearer_code']} | {r['recharge_status']} | {r['storage_path'] or ''} |")
        out.append("")
        out.append("Subtotal: " + ", ".join(fmt(v, k) for k, v in sub.items()))
        out.append("")
    out.append("## Totals")
    out.append("")
    for k, v in grand.items():
        out.append(f"- {fmt(v, k)}")
    out.append(f"- Indicative total in EUR at ECB reference rates: {fmt(grand_eur, 'EUR')}"
               + (" (some lines lack a rate)" if missing_fx else ""))
    rates = con.execute("SELECT quote, rate, rate_date FROM fx_rate ORDER BY rate_date DESC").fetchall()
    out.append("")
    out.append("Rates used: " + (", ".join(f"1 EUR = {r['rate']} {r['quote']} ({r['rate_date']})" for r in rates[:3]) or "none loaded")
               + ". Invoice the EUR amount the card actually charged, not a reference rate: Amex's rate differs by 1 to 3 percent.")
    return "\n".join(out)


def _expand_recurring(con, start: date, end: date):
    for r in con.execute("SELECT r.*, e.code AS entity FROM recurring r JOIN entity e ON e.id=r.entity_id WHERE r.active=1").fetchall():
        due = None
        if r["next_due"]:
            due = date.fromisoformat(r["next_due"])
        elif r["cadence"] == "monthly" and r["anchor_day"]:
            d = start.replace(day=1)
            while d <= end:
                cand = d.replace(day=min(r["anchor_day"], 28))
                if start <= cand <= end:
                    yield r, cand
                d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
            continue
        if due and start <= due <= end:
            yield r, due


def forecast(con: sqlite3.Connection, start: date, days: int = 10) -> str:
    end = start + timedelta(days=days)
    out = [f"# Outgoings and ingoings, {start.isoformat()} to {end.isoformat()}", ""]
    lines = []
    for s in con.execute("""SELECT s.*, e.code AS entity FROM scheduled s JOIN entity e ON e.id=s.entity_id
                            WHERE s.done=0 AND s.due_date BETWEEN ? AND ? ORDER BY s.due_date""",
                         (start.isoformat(), end.isoformat())).fetchall():
        lines.append((s["due_date"], s["entity"], s["direction"], s["label"], s["amount_minor"], s["currency"],
                      s["confidence"], s["category"], s["source"], s["notes"]))
    for r, due in _expand_recurring(con, start, end):
        lines.append((due.isoformat(), r["entity"], r["direction"], r["label"], r["amount_minor"], r["currency"],
                      r["confidence"], r["category"], r["source"], r["notes"]))
    for t in con.execute("""SELECT t.*, e.code AS entity FROM txn t JOIN entity e ON e.id=t.entity_id
                            WHERE t.status='expected' AND t.txn_date BETWEEN ? AND ?""",
                         (start.isoformat(), end.isoformat())).fetchall():
        lines.append((t["txn_date"], t["entity"], t["direction"], t["description"], t["amount_minor"], t["currency"],
                      "medium", t["category"], "ledger", t["notes"]))
    lines.sort(key=lambda x: (x[0], x[2], x[1]))
    out += ["| Due | Entity | Dir | What | Amount | EUR | Confidence | Source |", "|---|---|---|---|---:|---:|---|---|"]
    totals = defaultdict(lambda: defaultdict(int))
    eur_tot = defaultdict(int)
    unknown = []
    for d, ent, dirn, label, minor, cur, conf, cat, src, notes in lines:
        if minor is None:
            unknown.append((d, ent, dirn, label, src, notes))
            out.append(f"| {d} | {ent} | {dirn} | {label} | amount not yet known | | {conf} | {src or ''} |")
            continue
        eur = _eur(con, minor, cur, d)
        totals[dirn][cur] += minor
        eur_tot[dirn] += eur or 0
        out.append(f"| {d} | {ent} | {dirn} | {label} | {fmt(minor, cur)} | {fmt(eur, 'EUR') if eur is not None else '?'} | {conf} | {src or ''} |")
    out.append("")
    out.append("## Totals (lines with a known amount)")
    out.append("")
    for dirn in ("out", "in"):
        if totals[dirn]:
            out.append(f"- {dirn}: " + ", ".join(fmt(v, k) for k, v in totals[dirn].items())
                       + f" (about {fmt(eur_tot[dirn], 'EUR')})")
    out.append(f"- net: {fmt(eur_tot['in'] - eur_tot['out'], 'EUR')}")
    recv = con.execute("""SELECT * FROM claim WHERE status IN ('sent','part_paid','disputed') ORDER BY invoice_date""").fetchall()
    if recv:
        out += ["", "## Open receivables (not dated: chase, do not count on them in the window)", "",
                "| Invoice | Issuer | Client | Date | Total | Paid | Outstanding | Status | Notes |", "|---|---|---|---|---:|---:|---:|---|---|"]
        tot_out = defaultdict(int)
        for c in recv:
            outstanding = (c["total_minor"] or 0) - (c["paid_minor"] or 0)
            tot_out[c["currency"]] += outstanding
            out.append(f"| {c['invoice_no']} | {c['issuer']} | {c['client']} | {c['invoice_date'] or ''} | {fmt(c['total_minor'], c['currency'])} | "
                       f"{fmt(c['paid_minor'], c['currency'])} | {fmt(outstanding, c['currency'])} | {c['status']} | {c['notes'] or ''} |")
        out.append("")
        out.append("Outstanding: " + ", ".join(fmt(v, k) for k, v in tot_out.items()))
    if unknown:
        out.append("")
        out.append("## Dated but amount unknown")
        out.append("")
        for d, ent, dirn, label, src, notes in unknown:
            out.append(f"- {d} {ent} {dirn}: {label}" + (f". {notes}" if notes else ""))
    return "\n".join(out)


def burn(con: sqlite3.Connection, months: int = 4) -> str:
    rows = con.execute("SELECT * FROM v_monthly_burn ORDER BY month DESC, entity, out_eur DESC").fetchall()
    out = ["# Monthly burn by entity and category (EUR, ECB reference rates)", "",
           "| Month | Entity | Category | Out | In | Lines |", "|---|---|---|---:|---:|---:|"]
    seen_months = []
    for r in rows:
        if r["month"] not in seen_months:
            seen_months.append(r["month"])
        if len(seen_months) > months:
            break
        out.append(f"| {r['month']} | {r['entity']} | {r['category'] or 'unclassified'} | {r['out_eur'] or 0:,.2f} | {r['in_eur'] or 0:,.2f} | {r['n']} |")
    tot = con.execute("""SELECT substr(txn_date,1,7) m, bearer_entity, SUM(CASE WHEN direction='out' THEN amount_eur_minor ELSE 0 END)/100.0 o
                         FROM txn WHERE status<>'cancelled' GROUP BY 1,2 ORDER BY 1 DESC""").fetchall()
    out += ["", "## Out per month per bearer", ""]
    for r in tot[: months * 6]:
        out.append(f"- {r['m']} {r['bearer_entity']}: {r['o'] or 0:,.2f} EUR")
    return "\n".join(out)
