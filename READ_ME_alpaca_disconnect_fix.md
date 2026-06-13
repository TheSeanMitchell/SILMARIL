# SILMARIL — Alpaca disconnect + deployment drop

The disconnect was two problems wearing one coat, plus a reason cash sat idle.
All fixes below. Drag each file into place via the GitHub web UI (paths preserved).

## Files
1. silmaril/execution/alpaca_paper.py   — (a) SYNC: prune position_meta to the broker's
   actual holdings each cycle, guarded by fetch-success, so phantom positions stop
   showing on the site; (b) record Alpaca's real order response (status / filled_qty /
   type / limit_price) so the orders log reflects what actually happened.
2. silmaril/portfolios/order_quality.py — defer→LIMIT. Volatile/thin-but-tradeable names
   now enter with a limit order instead of being skipped (the reason chosen trades weren't
   reaching Alpaca in a volatile tape). Outright skip only above ~9% ATR or <10% liquidity.
   Position-cap / cash / concentration / conviction gates are all UNCHANGED.
3. silmaril/analytics/suite.py           — adds the market_leaders ingestion step.
4. silmaril/ingestion/market_leaders.py  — NEW. Daily gainers/losers/most-active + megacaps
   via FMP / Alpha Vantage / Polygon (keys you already have), stockanalysis.com fallback.
   Cross-references each mover against the system's universe/holdings. Writes
   docs/data/market_leaders.json.
5. docs/index.html      — (a) richer "How the news moved decisions" card; (b) the
   "What it traded" card now tags each trade "in Alpaca" / "not held" so you can see which
   chosen trades are actually positions right now.
6. docs/briefing.html   — same richer news card.
7. .github/workflows/daily.yml — adds FMP/AV/Polygon env to the analytics step.

## Verified before delivery
- py_compile on all 4 modules: OK
- order_quality: 6%/8% ATR now LIMIT (was skip); 10% ATR & <10% liq still skip; verified
- full analytics suite vs real docs/data: 5/5 OK; market_leaders degrades gracefully w/o keys
- daily.yml valid YAML, single analytics step; both HTML JS bundles pass `node --check`

## You still need to (can't be done in code)
- Set ALPACA_API_KEY_H5 / ALPACA_SECRET_H5 in repo secrets so HARVEST_5 stops sitting flat
  (configured:false = secrets unset; it has $9,655 idle and sends zero orders without them).
