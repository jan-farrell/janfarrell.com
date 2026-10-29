"""Render a Farrell Import invoice to SquareTrade as HTML and PDF, with an
expenses annex drawn from the ledger's recharge candidates for the period.
Layout follows invoices 12 and 13: service table, 0% VAT, CaixaBank details."""
from __future__ import annotations
import html
import sqlite3
from datetime import date
from pathlib import Path
from .money import fmt
from . import fx

ISSUER = {
    "name": "FARRELL IMPORT SL",
    "tax_id": "ES-B83294744",
    "address": "Marqués de la Valdavia 42, 3-5 28100 Alcobendas - Spain",
    "tagline": "Events, Technology & Consulting",
    "bank": "CAIXA BANK",
    "iban": "ES27 2100 1908 7902 0016 8766",
    "swift": "CAIXESBBXXX",
}
CLIENT = {
    "name": "Square Trade Limited",
    "address": "C/o Fieldfisher 2 Swan Lane, London, EC4R 3TT, UK",
    "vat": "V.A.T. number GB 215332445",
    "approver": "Kevin Gillan",
}
MONTHS_ES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
             "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def es_amount(minor: int) -> str:
    v = abs(minor)
    whole, cents = v // 100, v % 100
    s = f"{whole:,}".replace(",", ".")
    return f"{'-' if minor < 0 else ''}{s},{cents:02d}€"


def es_date(d: date) -> str:
    return f"{d.day} de {MONTHS_ES[d.month - 1]} {d.year}"


def expense_lines(con: sqlite3.Connection, client: str, start: str, end: str, trips_exclude=()):
    rows = con.execute(
        """SELECT t.*, c.name AS cp, d.storage_path FROM txn t
           LEFT JOIN counterparty c ON c.id=t.counterparty_id LEFT JOIN document d ON d.id=t.document_id
           WHERE t.recharge_to=? AND t.txn_date BETWEEN ? AND ? AND t.status<>'cancelled'
             AND t.recharge_status IN ('candidate','claimed')
           ORDER BY t.trip_id, t.txn_date""", (client, start, end)).fetchall()
    out = []
    for r in rows:
        if r["trip_id"] in trips_exclude:
            continue
        eur = r["amount_eur_minor"]
        if eur is None:
            eur, _ = fx.to_eur_minor(con, r["amount_minor"], r["currency"], r["txn_date"])
        out.append({"date": r["txn_date"], "trip": r["trip_id"] or "", "category": r["category"] or "",
                    "cp": r["cp"] or "", "desc": r["description"] or "", "amount": r["amount_minor"],
                    "cur": r["currency"], "eur": eur, "src": r["storage_path"] or ""})
    return out


def render(con: sqlite3.Connection, *, number: int, issue_date: date, period_label: str, days: int,
           fee_minor: int, start: str, end: str, client: str = "SQUARETRADE",
           extra_lines: list[tuple[str, int]] | None = None, trips_exclude=(), fx_note: str = "") -> tuple[str, dict]:
    lines = expense_lines(con, client, start, end, trips_exclude)
    expenses = sum(l["eur"] or 0 for l in lines)
    missing = [l for l in lines if l["eur"] is None]
    extra_lines = extra_lines or []
    total = fee_minor + expenses + sum(m for _, m in extra_lines)

    def esc(s):
        return html.escape(str(s))

    service_rows = [
        (f"Business Development &amp; Brand Recognition – {esc(period_label)} ({days} days)", fee_minor),
        (f"Expenses – Jan (London &amp; Madrid), {esc(period_label)}", expenses),
    ] + [(esc(label), m) for label, m in extra_lines]

    rows_html = "\n".join(
        f"<tr><td>{label}</td><td class='num'>{es_amount(m)}</td><td class='num'>1</td><td class='num'>{es_amount(m)}</td></tr>"
        for label, m in service_rows)
    annex_rows = "\n".join(
        f"<tr><td>{l['date']}</td><td>{esc(l['trip'])}</td><td>{esc(l['cp'])}</td><td>{esc(l['desc'])}</td>"
        f"<td class='num'>{fmt(l['amount'], l['cur'])}</td><td class='num'>{es_amount(l['eur']) if l['eur'] is not None else '?'}</td></tr>"
        for l in lines)

    doc = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Factura {number} Farrell Import</title>
<style>
 @page {{ size: A4; margin: 18mm 16mm; }}
 body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; color: #111; font-size: 11pt; }}
 .page {{ page-break-after: always; }}
 .head {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18mm; }}
 .issuer {{ font-size: 10pt; line-height: 1.35; }}
 .issuer b {{ font-size: 13pt; letter-spacing: .5px; }}
 .meta {{ text-align: right; font-size: 10.5pt; line-height: 1.4; }}
 .meta .num {{ font-size: 20pt; font-weight: 700; }}
 .client {{ margin: 0 0 12mm; line-height: 1.4; }}
 table {{ width: 100%; border-collapse: collapse; }}
 th {{ text-align: left; font-size: 9pt; letter-spacing: 1px; border-bottom: 1.5px solid #111; padding: 6px 4px; }}
 td {{ padding: 8px 4px; border-bottom: 1px solid #ddd; vertical-align: top; }}
 td.num, th.num {{ text-align: right; white-space: nowrap; }}
 .totals {{ margin-top: 10mm; margin-left: auto; width: 60%; }}
 .totals td {{ border: none; padding: 4px; }}
 .totals .grand td {{ font-size: 15pt; font-weight: 700; border-top: 2px solid #111; padding-top: 8px; }}
 .approve {{ margin-top: 6mm; font-size: 10pt; color: #333; }}
 .pay {{ margin-top: 16mm; font-size: 10pt; line-height: 1.5; }}
 .pay b {{ letter-spacing: 1.5px; font-size: 9pt; }}
 h2 {{ font-size: 13pt; margin: 0 0 6mm; }}
 .annex td, .annex th {{ font-size: 9pt; padding: 5px 4px; }}
 .note {{ font-size: 9pt; color: #444; margin-top: 6mm; line-height: 1.4; }}
</style></head><body>
<section class="page">
 <div class="head">
  <div class="issuer"><b>{esc(ISSUER['name'])}</b><br>{esc(ISSUER['tagline'])}<br>{esc(ISSUER['tax_id'])}<br>{esc(ISSUER['address'])}</div>
  <div class="meta"><div class="num">Factura: {number}</div>{esc(es_date(issue_date))}</div>
 </div>
 <div class="client"><b>{esc(CLIENT['name'])}</b><br>{esc(CLIENT['address'])}<br>{esc(CLIENT['vat'])}</div>
 <table><thead><tr><th>SERVICIO</th><th class="num">PRECIO</th><th class="num">CANTIDAD</th><th class="num">TOTAL</th></tr></thead>
 <tbody>{rows_html}</tbody></table>
 <div class="approve">To be approved by: {esc(CLIENT['approver'])}</div>
 <table class="totals">
  <tr><td>Subtotal:</td><td class="num">{es_amount(total)}</td></tr>
  <tr><td>I.V.A. (0%):</td><td class="num">0 €</td></tr>
  <tr class="grand"><td>TOTAL:</td><td class="num">{es_amount(total)}</td></tr>
 </table>
 <div class="pay"><b>INFORMACIÓN PARA EL PAGO</b><br>{esc(ISSUER['bank'])}<br>IBAN: {esc(ISSUER['iban'])}<br>SWIFT/BIC: {esc(ISSUER['swift'])}<br>Beneficiario: {esc(ISSUER['name'])}</div>
</section>
<section>
 <h2>Anexo a la factura {number}: Expenses – Jan, {esc(period_label)}</h2>
 <table class="annex"><thead><tr><th>Date</th><th>Trip</th><th>Supplier</th><th>Detail</th><th class="num">Charged</th><th class="num">EUR</th></tr></thead>
 <tbody>{annex_rows}
 <tr><td colspan="5"><b>Total expenses</b></td><td class="num"><b>{es_amount(expenses)}</b></td></tr></tbody></table>
 <div class="note">{esc(fx_note)}</div>
</section>
</body></html>"""
    summary = {"number": number, "fee": fee_minor, "expenses": expenses, "extra": extra_lines, "total": total,
               "lines": len(lines), "missing_fx": len(missing)}
    return doc, summary


def to_pdf(html_path: Path, pdf_path: Path) -> None:
    """Chromium print via Node Playwright (lib/html2pdf.js); Python Playwright is not assumed."""
    import subprocess
    script = Path(__file__).resolve().parent / "html2pdf.js"
    subprocess.run(["node", str(script), str(html_path), str(pdf_path)], check=True, timeout=120)
