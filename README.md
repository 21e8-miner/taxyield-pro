# TaxYield Pro

After-tax yield vs duration for bond / cash ETFs — **stated yield · duration · state tax efficiency · live marks**.

**→ [Open TaxYield Pro](https://21e8-miner.github.io/taxyield-pro/)**

This is the **canonical** desk. It consolidates:

| Source | What we kept |
|--------|----------------|
| **TaxYield Pro** (this repo + Pages) | Product name, full curve book (cash → ZROZ), GitHub Pages, weekday yield bot |
| **Fixed Income Pro** | Curve tape, live price column, hybrid feed, richer insights / ladder |
| **Bravias FI desk** | Optional Cloudflare Worker quote proxy for public live marks; short-book filter as **≤5y / >5y** toggle (not a hard cut) |

## Views

| Mode | What you get |
|------|----------------|
| **Scatter** | Stated yield vs duration (color = state-tax treatment) |
| **Table** | Sortable after-tax book + live price |
| **Duration ladder** | Bucket averages for curve positioning |

**Duration filter:** All · ≤5y · >5y

After-tax math: **37% federal** + state slider × (1 − exempt%).

## Data

| Layer | Source |
|-------|--------|
| Fund book | `data/funds.json` (18 names) |
| Weekday auto-update | GitHub Action **Update Yields** (~9am ET) |
| Overnight prices | Written into the fund book by the same bot |
| Live marks (local) | `python3 server.py` → **:8775** |
| Live marks (edge) | optional Worker `edge/` → `/api/quotes` |

**We never invent yields.** If Yahoo has no usable fund yield, the prior print is kept. Stale as-of dates (>45 days) light the status badge orange.

```bash
cd taxyield-pro
python3 server.py                 # http://127.0.0.1:8775/
python3 scripts/update_yields.py  # refresh data/funds.json
# optional edge:
npm install && npm run dev:edge
```

```bash
curl -s http://127.0.0.1:8775/api/health
curl -s 'http://127.0.0.1:8775/api/quotes?symbols=SGOV,TLT,^TNX' | python3 -m json.tool
```

## Layout

```
taxyield-pro/
├── index.html                 # board (GitHub Pages entry)
├── data/funds.json            # desk book (Action-updated)
├── server.py                  # local Yahoo quote relay :8775
├── scripts/update_yields.py   # weekday yield/price updater
├── .github/workflows/         # Update Yields
├── edge/worker.js             # optional Cloudflare quote API
└── package.json               # wrangler scripts
```

## Sibling repos

`fixed-income-dashboard` and `bravias-fi-desk` are superseded by this consolidation. Prefer **taxyield-pro** for new work.

## Disclaimer

Not investment advice. Internal research / client discussion only. Confirm yields and tax treatment with issuer materials and your tax advisor. Past performance does not guarantee future results.
