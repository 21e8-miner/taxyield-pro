/**
 * TaxYield Pro — Cloudflare Worker
 * Static board + Yahoo quote proxy for live marks on the public web.
 */

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";

const cache = new Map(); // symbol -> { ts, q }
const CACHE_TTL_MS = 45_000;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "access-control-allow-origin": "*",
      "cache-control": "no-store",
    },
  });
}

function parseSymbols(raw) {
  if (!raw) return [];
  const out = [];
  const seen = new Set();
  for (const part of String(raw).split(",")) {
    const s = part.trim();
    if (!s || seen.has(s)) continue;
    // allow ^TNX etc and tickers
    if (!/^[A-Za-z0-9.^=-]{1,12}$/.test(s)) continue;
    seen.add(s);
    out.push(s);
  }
  return out;
}

async function yahooQuote(symbol) {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(
    symbol
  )}?interval=1d&range=5d`;
  const res = await fetch(url, {
    headers: { "User-Agent": UA, Accept: "application/json" },
  });
  if (!res.ok) throw new Error(`yahoo ${res.status}`);
  const data = await res.json();
  const meta = data?.chart?.result?.[0]?.meta;
  const last = Number(meta?.regularMarketPrice);
  if (!last || last <= 0) throw new Error("no price");
  const prev =
    Number(meta?.chartPreviousClose || meta?.previousClose) || last;
  const chg = last - prev;
  const pct = prev ? (chg / Math.abs(prev)) * 100 : null;
  return { last, prev, chg, pct };
}

async function quotesFor(symbols) {
  const now = Date.now();
  const out = {};
  const missing = [];
  for (const s of symbols) {
    const hit = cache.get(s);
    if (hit && now - hit.ts < CACHE_TTL_MS) out[s] = hit.q;
    else missing.push(s);
  }
  // modest concurrency
  const conc = 5;
  let i = 0;
  async function worker() {
    while (i < missing.length) {
      const idx = i++;
      const s = missing[idx];
      try {
        const q = await yahooQuote(s);
        cache.set(s, { ts: Date.now(), q });
        out[s] = q;
      } catch {
        /* skip */
      }
    }
  }
  await Promise.all(
    Array.from({ length: Math.min(conc, Math.max(1, missing.length)) }, () =>
      worker()
    )
  );
  return out;
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "GET,OPTIONS",
          "access-control-allow-headers": "*",
        },
      });
    }

    const url = new URL(request.url);

    if (url.pathname === "/api/health") {
      return json({
        ok: true,
        service: "taxyield-pro",
        product: "TaxYield Pro",
        cache_size: cache.size,
      });
    }

    if (url.pathname === "/api/quotes") {
      const symbols = parseSymbols(url.searchParams.get("symbols"));
      if (!symbols.length) return json({ quotes: {}, returned: 0 });
      try {
        const quotes = await quotesFor(symbols);
        return json({
          quotes,
          returned: Object.keys(quotes).length,
          source: "yahoo-edge",
          cached: true,
        });
      } catch (e) {
        return json({ error: e.message, quotes: {} }, 502);
      }
    }

    if (url.pathname === "/api/quote") {
      const s = url.searchParams.get("s") || url.searchParams.get("symbol");
      const symbols = parseSymbols(s);
      if (!symbols.length) return json({ error: "symbol required" }, 400);
      const quotes = await quotesFor(symbols);
      return json({ quote: quotes[symbols[0]] || null, symbol: symbols[0] });
    }

    if (env.ASSETS) return env.ASSETS.fetch(request);
    return new Response("TaxYield Pro — assets missing", { status: 500 });
  },
};
