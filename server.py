#!/usr/bin/env python3
"""
TaxYield Pro — local quote backend.

Serves the board and proxies Yahoo Finance via yfinance so the browser
does not depend on broken public CORS proxies.

  python3 server.py
  → http://127.0.0.1:8765/

Endpoints:
  GET /                 → index.html
  GET /api/health       → {ok, service, cache_size}
  GET /api/quotes?symbols=CL=F,DHT,...
                        → {quotes: {SYM: {last, prev, chg, pct}}, source, cached}
  GET /api/quote?s=CL=F → single-symbol shape
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
HTML_FILE = BASE_DIR / "index.html"
sys.path.insert(0, str(BASE_DIR))
PORT = 8775
CACHE_TTL = 45.0  # seconds — desk board, not HFT

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_CACHE: dict[str, dict] = {}
_CACHE_LOCK = threading.Lock()
_FETCH_LOCK = threading.Lock()

try:
    import yfinance as yf
    import pandas as pd
except ImportError:
    print("Installing yfinance (one-time)…", flush=True)
    import subprocess

    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--quiet", "yfinance", "pandas"],
    )
    import yfinance as yf
    import pandas as pd


def _parse_symbols(raw: str | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        s = part.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _from_closes(closes) -> dict | None:
    closes = closes.dropna()
    if len(closes) == 0:
        return None
    last = float(closes.iloc[-1])
    prev = float(closes.iloc[-2]) if len(closes) > 1 else None
    if not (last == last):  # NaN
        return None
    out: dict = {"last": last, "prev": prev}
    if prev is not None and prev != 0:
        out["chg"] = last - prev
        out["pct"] = (out["chg"] / abs(prev)) * 100.0
    return out


def fetch_quotes(symbols: list[str]) -> tuple[dict[str, dict], str]:
    """Return ({sym: quote}, source_label). Uses short TTL cache."""
    if not symbols:
        return {}, "empty"

    now = time.time()
    result: dict[str, dict] = {}
    missing: list[str] = []

    with _CACHE_LOCK:
        for s in symbols:
            hit = _CACHE.get(s)
            if hit and now - hit["ts"] <= CACHE_TTL:
                result[s] = {k: v for k, v in hit["q"].items()}
            else:
                missing.append(s)

    if not missing:
        return result, "cache"

    # Serialize upstream pulls so concurrent browser tabs don't stampede Yahoo
    with _FETCH_LOCK:
        now = time.time()
        still: list[str] = []
        with _CACHE_LOCK:
            for s in missing:
                hit = _CACHE.get(s)
                if hit and now - hit["ts"] <= CACHE_TTL:
                    result[s] = {k: v for k, v in hit["q"].items()}
                else:
                    still.append(s)
        if still:
            fresh = _pull_yfinance(still)
            with _CACHE_LOCK:
                for s, q in fresh.items():
                    _CACHE[s] = {"ts": time.time(), "q": q}
                    result[s] = dict(q)

    return result, "yfinance"


def _pull_yfinance(symbols: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not symbols:
        return out

    try:
        data = yf.download(
            symbols,
            period="5d",
            interval="1d",
            group_by="ticker",
            threads=True,
            progress=False,
            auto_adjust=True,
        )
        for sym in symbols:
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    if sym not in data.columns.get_level_values(0):
                        continue
                    closes = data[sym]["Close"]
                else:
                    closes = data["Close"]
                q = _from_closes(closes)
                if q:
                    out[sym] = q
            except Exception:
                continue
    except Exception as e:
        print(f"[quotes] batch download failed: {e}", flush=True)

    # Retry misses one-by-one (international tickers, thin names)
    for sym in symbols:
        if sym in out:
            continue
        try:
            h = yf.Ticker(sym).history(period="5d", auto_adjust=True)
            if h is None or h.empty:
                continue
            q = _from_closes(h["Close"])
            if q:
                out[sym] = q
        except Exception as e:
            print(f"[quotes] {sym}: {e}", flush=True)

    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "TheMiddle/1.0"

    def log_message(self, fmt, *args):
        # Quiet default access log; keep errors.
        if args and str(args[0]).startswith(("4", "5")):
            super().log_message(fmt, *args)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")
        self.send_header("Cache-Control", "no-store")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path in ("/api/health", "/health", "/status"):
            with _CACHE_LOCK:
                n = len(_CACHE)
            self._json(
                {
                    "ok": True,
                    "status": "ok",
                    "service": "taxyield-quotes",
                    "port": self.server.server_address[1],
                    "cache_size": n,
                    "cache_ttl_s": CACHE_TTL,
                    "yfinance": True,
                    
                }
            )
            return


        if path in ("/api/quotes", "/quotes"):
            symbols = _parse_symbols((qs.get("symbols") or qs.get("s") or [""])[0])
            if not symbols:
                self._json({"error": "missing symbols"}, status=400)
                return
            t0 = time.time()
            quotes, source = fetch_quotes(symbols)
            self._json(
                {
                    "quotes": quotes,
                    "source": source,
                    "requested": len(symbols),
                    "returned": len(quotes),
                    "missing": [s for s in symbols if s not in quotes],
                    "elapsed_ms": int((time.time() - t0) * 1000),
                    "ts": time.time(),
                }
            )
            return

        if path in ("/api/quote", "/quote"):
            sym = (qs.get("s") or qs.get("symbol") or [""])[0].strip()
            if not sym:
                self._json({"error": "missing s"}, status=400)
                return
            quotes, source = fetch_quotes([sym])
            q = quotes.get(sym)
            if not q:
                self._json({"error": "not found", "symbol": sym, "source": source}, status=404)
                return
            self._json({"symbol": sym, "source": source, **q})
            return

        if path in ("/api/funds", "/funds"):
            target = BASE_DIR / "data" / "funds.json"
            if target.exists():
                body = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self._cors()
                self.end_headers()
                self.wfile.write(body)
                return
            self._json({"error": "funds.json missing"}, status=404)
            return

        # Static data (fund book JSON for Pages + local)
        if path.startswith("/data/"):
            rel = path.lstrip("/")
            # path traversal guard
            target = (BASE_DIR / rel).resolve()
            if not str(target).startswith(str(BASE_DIR.resolve())):
                self.send_error(403)
                return
            if target.is_file():
                body = target.read_bytes()
                ctype = "application/json; charset=utf-8" if target.suffix == ".json" else "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self._cors()
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_error(404)
            return

        if path in ("/", "/index.html"):
            if not HTML_FILE.exists():
                self.send_error(404, "index.html not found")
                return
            body = HTML_FILE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        self.send_error(404)

    def _json(self, obj, status=200):
        body = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)


def main():
    port = PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass

    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        port = PORT + 1
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)

    url = f"http://127.0.0.1:{port}/"
    print("═" * 56)
    print("  TAXYIELD PRO — quote backend")
    print(f"  board   {url}")
    print(f"  health  {url}api/health")
    print(f"  quotes  {url}api/quotes?symbols=SGOV,TLT,^TNX")
    print("═" * 56)

    if "--no-open" not in sys.argv:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] stopped")
        httpd.server_close()


if __name__ == "__main__":
    main()
