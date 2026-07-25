#!/usr/bin/env python3
"""
Update Fixed Income Pro fund yields + last prices.

Reads/writes data/funds.json. Never invents numbers:
  - If Yahoo returns a sensible fund yield, update statedYield + asOf + yieldSource=yahoo
  - Always try to refresh last price when available
  - If a ticker fails or yield is unusable (0 / null / absurd), keep the prior print

Usage:
  python3 scripts/update_yields.py
  python3 scripts/update_yields.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNDS_PATH = ROOT / "data" / "funds.json"

try:
    import yfinance as yf
except ImportError:
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "yfinance", "pandas"])
    import yfinance as yf


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_yield_pct(raw) -> float | None:
    """
    Yahoo is inconsistent: sometimes 0.0385 (fraction), sometimes 3.85 (%).
    Return percent points in a sane bond-ETF band, or None.
    """
    if raw is None:
        return None
    try:
        y = float(raw)
    except (TypeError, ValueError):
        return None
    if y != y:  # NaN
        return None
    if 0 < y < 0.25:  # fraction e.g. 0.0385
        y *= 100.0
    # Bond / cash ETF stated yields typically ~1–10% in normal regimes; allow up to 15
    if y < 0.5 or y > 15.0:
        return None
    return round(y, 2)


def fetch_yahoo(ticker: str) -> dict:
    """Return {yield_pct?, price?, source_detail}."""
    out: dict = {}
    t = yf.Ticker(ticker)

    # Prefer quote payload first (lighter than full info on some versions)
    try:
        info = t.info or {}
    except Exception as e:
        info = {}
        out["error"] = f"info: {e}"

    # Yield candidates in preference order
    for key in ("yield", "dividendYield", "trailingAnnualDividendYield"):
        if key not in info or info[key] in (None, 0, 0.0):
            continue
        y = normalize_yield_pct(info[key])
        if y is not None:
            # dividendYield on Yahoo is often already percent (3.85) while yield is fraction
            if key == "dividendYield" and info[key] and float(info[key]) > 0.25:
                y = round(float(info[key]), 2)
                if y < 0.5 or y > 15.0:
                    y = None
            if y is not None:
                out["yield_pct"] = y
                out["yield_field"] = key
                break

    # Price
    price = None
    for key in ("regularMarketPrice", "navPrice", "previousClose"):
        if info.get(key) is not None:
            try:
                price = float(info[key])
                if price == price and price > 0:
                    break
            except (TypeError, ValueError):
                pass
    if price is None:
        try:
            h = t.history(period="5d", auto_adjust=True)
            if h is not None and len(h):
                price = float(h["Close"].iloc[-1])
        except Exception:
            pass
    if price is not None and price == price and price > 0:
        out["price"] = round(price, 4)

    return out


def update_funds(data: dict, dry_run: bool = False) -> dict:
    funds = data.get("funds") or []
    today = utc_today()
    stats = {
        "yield_updated": 0,
        "yield_kept": 0,
        "price_updated": 0,
        "failed": 0,
        "details": [],
    }

    for f in funds:
        ticker = f.get("ticker")
        if not ticker:
            continue
        try:
            yq = fetch_yahoo(ticker)
            time.sleep(0.35)  # be polite to Yahoo in Actions
        except Exception as e:
            stats["failed"] += 1
            stats["details"].append(f"{ticker}: FAIL {e}")
            continue

        detail = f"{ticker}:"
        # price always welcome
        if yq.get("price") is not None:
            prev_px = f.get("price")
            f["price"] = yq["price"]
            f["priceAsOf"] = today
            stats["price_updated"] += 1
            detail += f" px={yq['price']}"
            if prev_px is not None and abs(float(prev_px) - float(yq["price"])) > 1e-6:
                detail += f" (was {prev_px})"

        y = yq.get("yield_pct")
        if y is not None:
            prev = f.get("statedYield")
            f["statedYield"] = y
            f["asOf"] = today
            f["yieldSource"] = "yahoo"
            f["yieldField"] = yq.get("yield_field")
            stats["yield_updated"] += 1
            detail += f" yld={y}% (was {prev})"
        else:
            stats["yield_kept"] += 1
            detail += " yld=kept"
            if yq.get("error"):
                detail += f" [{yq['error']}]"

        stats["details"].append(detail)

    data["updatedAt"] = utc_now_iso()
    data["lastRunStats"] = {
        "yield_updated": stats["yield_updated"],
        "yield_kept": stats["yield_kept"],
        "price_updated": stats["price_updated"],
        "failed": stats["failed"],
    }
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--path", type=Path, default=FUNDS_PATH)
    args = ap.parse_args()

    if not args.path.exists():
        print(f"missing {args.path}", file=sys.stderr)
        return 1

    data = json.loads(args.path.read_text())
    before = json.dumps(data, sort_keys=True)
    stats = update_funds(data, dry_run=args.dry_run)
    after = json.dumps(data, sort_keys=True)

    print("=== update_yields ===")
    for line in stats["details"]:
        print(" ", line)
    print(
        f"yields updated={stats['yield_updated']} kept={stats['yield_kept']} "
        f"prices={stats['price_updated']} failed={stats['failed']}"
    )

    if args.dry_run:
        print("dry-run: not writing")
        return 0

    if before == after:
        print("no changes")
        # still bump updatedAt for observability of successful runs
    args.path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"wrote {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
