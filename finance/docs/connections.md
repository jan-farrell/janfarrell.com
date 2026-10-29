# Connecting the accounts: what works and what does not

Written 27 October 2026. Checked against what the institutions offer, not against marketing pages.

## Principles

1. Never give a bank password to an automation, a chat, or a scraper. Both Amex and CaixaBank require a second factor on the phone, so a scripted login fails and can trigger a fraud lock. Scraping also breaks their terms.
2. Use the regulated route: in the EU and UK, PSD2 and Open Banking oblige banks and card issuers to expose transactions to licensed aggregators with the customer's consent. Consent is renewed every 90 to 180 days from the bank's own app. Nothing else is needed from you.
3. Where no API exists, the receipt email is the source of truth, and the Mac harvester already files it.

## By institution

| Institution | Feed that works | How | Notes |
|---|---|---|---|
| American Express (Spain) | Open Banking via a licensed aggregator; or monthly CSV/Excel export from the Amex web app | Aggregator: one consent in the Amex app; the ledger pulls transactions daily. Export: "Statements and activity" → download → drop the file in `data/in/` → `fin.py import-statement amex_es AMEX_JAN file.csv` | Amex shows charges as positive numbers; the `amex_es` profile handles it. The EUR amount Amex charged is the figure to recharge, not a reference rate. |
| CaixaBank | Open Banking (PSD2) via aggregator; or export from CaixaBankNow (Excel or CSV) | Same as above; profile `caixabank` | Receives SquareTrade payments: the import marks incoming lines so receivables can be matched to invoices 7, 12 and 13. |
| Revolut Business | Official Business API | API key from the Revolut Business dashboard, read-only scope | Vanesa has asked for this account to be in the books. |
| Wise Business | Official API | Read-only token | |
| Curve | None | Email receipts | Curve forwards the underlying card, so the charge also appears on that card: deduplicate by amount and date. |
| Uber | None for consumers | Email trip receipts (already harvested). Uber for Business has a CSV export of trips if the Liberalia account is used | Tipped trips produce a second receipt; the ledger keeps the later one. |
| Iberia | None | E-ticket PDF by email (already harvested). Iberia Plus activity export from the website for Avios | Vouchers show as "MS" form of payment: no cash moved. |
| British Airways | None | Booking confirmation and e-ticket emails (already harvested) | The booking email states the total; the fare line alone understates it. Billing name is often Liberalia Assistance: change it in the BA profile to Farrell Import for work bookings. |
| Booking.com, Soho House, Travelodge | None | Email confirmations and folios | Soho House folios are the document to recharge; the booking confirmation deposit is inside the folio. |
| Todoist | MCP connector (already connected) | Payments appear as tasks with labels Promised, Expected, Waiting | The forecast plan file is built from these. |
| Dropbox | MCP connector (already connected) | The harvested receipts and manifests | Rate limited under heavy use; read in batches. |
| Microsoft 365 (jan@menako.capital) | MCP connector (already connected) | 17 emails since July, none financial | Not a useful source for this ledger. Menako is not Jan's personal burn. |

## Choosing an aggregator

Any PSD2-licensed account information service covers CaixaBank and American Express Europe. The differences are price, consent handling and whether they offer a free tier for one personal user. Pick one that: is licensed by a European regulator, offers a sandbox, returns raw transaction descriptions (not pre-categorised), and lets you revoke consent from the bank's app. Two consents (Amex, CaixaBank), renewed quarterly, is the whole operational burden.

## What this session could and could not reach

Could: Dropbox (receipts, manifests, index, memory), Todoist (dated payments), Microsoft 365 (the Menako mailbox only). Could not: any bank, card or airline account; the ECB rates feed (blocked by the container's network policy); Apple Mail, iCloud and Gmail (Mac only). The GBP rate used in the first reports is the one printed on the Iberia ticket of 28 August 2026 (1 EUR = 0.8555 GBP); `fin.py fx` replaces it with ECB rates when run from a machine with network access.
