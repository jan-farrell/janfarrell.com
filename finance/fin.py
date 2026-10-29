#!/usr/bin/env python3
"""Command line for the finance ledger.

  fin.py init                              create or refresh the database and seed rules
  fin.py import-manifests PATH...          import Facturas Vanesa manifest CSVs
  fin.py import-indice PATH.tsv            import a quarterly index exported as TSV
  fin.py import-statement PROFILE ACCOUNT PATH.csv
  fin.py classify [--all]                  turn documents into ledger rows, cancel thread duplicates
  fin.py import-items PATH.csv...          hand-curated items (receipts read one by one)
  fin.py fx-set DATE CUR RATE              set a rate by hand (1 EUR = RATE CUR)
  fin.py fx                                refresh ECB rates and fill EUR amounts
  fin.py load-plan PATH.toml...            load scheduled and recurring commitments
  fin.py recharge CLIENT START END         recharge schedule, markdown
  fin.py forecast [START] [DAYS]           outgoings and ingoings ahead
  fin.py burn [MONTHS]                     monthly burn by entity and category
  fin.py invoice N DATE LABEL DAYS FEE START END NAME [--lords]   invoice + annex, html and pdf
  fin.py sql "SELECT ..."                  ad hoc query

Set FIN_DB to use another database file. Default: finance/data/ledger.sqlite
"""
from __future__ import annotations
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import db, manifests, statements, rules, fx, plan, reports, manual, invoice  # noqa: E402


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    con = db.connect(os.environ.get("FIN_DB", db.DEFAULT_DB))
    cmd, args = argv[0], argv[1:]
    if cmd == "init":
        db.init(con); print("database ready:", con.execute("PRAGMA database_list").fetchone()[2])
    elif cmd == "import-manifests":
        for p in args:
            print(p, manifests.import_manifest(con, Path(p)))
    elif cmd == "import-indice":
        print(manifests.import_indice_tsv(con, Path(args[0])))
    elif cmd == "import-statement":
        profile, account, path = args
        print(statements.import_statement(con, Path(path), profile, account))
    elif cmd == "classify":
        print(rules.classify_all(con, only_new="--all" not in args))
        print("duplicates cancelled:", rules.dedupe(con))
    elif cmd == "import-items":
        for p in args:
            print(p, manual.import_items(con, Path(p)))
    elif cmd == "fx-set":
        # fin.py fx-set 2026-10-26 GBP 0.8712   (manual rate when the ECB feed is unreachable)
        con.execute("INSERT OR REPLACE INTO fx_rate(rate_date, quote, rate) VALUES(?,?,?)", (args[0], args[1], float(args[2])))
        con.commit(); print("rate set")
    elif cmd == "fx":
        try:
            print("rates loaded:", fx.refresh(con))
        except Exception as exc:  # offline is fine, use cached rates
            print("ECB fetch failed, using cached rates:", exc)
        print("eur filled:", fx.fill_missing(con))
    elif cmd == "load-plan":
        for p in args:
            print(p, plan.load_plan(con, Path(p)))
    elif cmd == "recharge":
        client, start, end = args[:3]
        print(reports.recharge(con, client, start, end))
    elif cmd == "forecast":
        start = date.fromisoformat(args[0]) if args else date.today()
        days = int(args[1]) if len(args) > 1 else 10
        print(reports.forecast(con, start, days))
    elif cmd == "burn":
        print(reports.burn(con, int(args[0]) if args else 4))
    elif cmd == "invoice":
        # fin.py invoice NUMBER ISSUE_DATE PERIOD_LABEL DAYS FEE START END OUT_BASENAME [--lords]
        number, issue, label, days, fee, start, end, out = args[:8]
        from lib.money import parse_amount
        fee_minor, _ = parse_amount(fee)
        extra = []
        excl = ("HOL-2026-09-10",)
        if "--lords" in args:
            lords = sum(r["amount_eur_minor"] or 0 for r in con.execute(
                "SELECT amount_eur_minor FROM txn WHERE trip_id='HOL-2026-09-10' AND status<>'cancelled' AND recharge_status='candidate'"))
            extra = [("Events – House of Lords, 10 September 2026 (deposit and pre-payment, Attlee Room)", lords)]
            excl = ()
        note = ("GBP amounts converted at 1 EUR = 0.8555 GBP, the rate printed on the Iberia ticket of 28 August 2026, "
                "pending the EUR amounts on the American Express statement. Receipts available on request.")
        doc, summary = invoice.render(con, number=int(number), issue_date=date.fromisoformat(issue), period_label=label,
                                      days=int(days), fee_minor=fee_minor, start=start, end=end,
                                      extra_lines=extra, trips_exclude=excl, fx_note=note)
        outp = Path("data/out") / out
        outp.with_suffix(".html").write_text(doc, encoding="utf-8")
        try:
            invoice.to_pdf(outp.with_suffix(".html"), outp.with_suffix(".pdf"))
            print("pdf:", outp.with_suffix(".pdf"))
        except Exception as exc:
            print("pdf failed, html written:", exc)
        print(summary)
    elif cmd == "sql":
        cur = con.execute(args[0])
        if cur.description:
            for row in cur.fetchall():
                print(dict(row))
        else:
            con.commit(); print("rows affected:", cur.rowcount)
    else:
        print("unknown command", cmd); print(__doc__); return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
