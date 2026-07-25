# TaxYield Pro

After-tax yield dashboard for bond / cash ETFs — **stated yield · duration · state tax efficiency**.

**→ [Open TaxYield Pro](https://21e8-miner.github.io/taxyield-pro/)**

## Views

| Mode | What you get |
|------|----------------|
| **Scatter** | Yield vs duration (color = state-tax treatment) |
| **Table** | Sortable after-tax book for your state rate |
| **Duration ladder** | Bucket averages for curve positioning |

After-tax math: **37% federal** + state slider × (1 − exempt%).

## Data

| Layer | Source |
|-------|--------|
| Fund book | `data/funds.json` |
| Weekday auto-update | GitHub Action `Update Yields` (~9am ET) |
| Local live quotes | optional `python3 server.py` on **:8775** |

```bash
cd taxyield-pro
python3 server.py          # http://127.0.0.1:8775/
python3 scripts/update_yields.py
```

Not investment advice. Internal research only.
