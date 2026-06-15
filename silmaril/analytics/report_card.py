"""
silmaril.analytics.report_card — judgement, judged. Then that judgement, judged.

Three layers, exactly as demanded:
  1. THE PICKS: every cycle, snapshot the desk's top BUY-side names (ticker,
     consensus score, price). On every later run, re-grade every recent
     snapshot against today's prices — so "how did Wednesday's picks do?" is a
     number on the page, not a feeling. Daily cohort stats (avg / median /
     hit-rate) form a graphable series, archived forever.
  2. THE JUDGE, JUDGED: calibration on CLEAN scored outcomes only — bucket
     every agent call by conviction and ask whether higher conviction actually
     earned higher forward returns. If the 0.7+ bucket doesn't beat the 0.3
     bucket, the judge has no signal and the page says so.
  3. THE AGENTS, ON CLEAN EVIDENCE: per-agent clean-only record (calls, hit
     rate, avg return) — the same table the Sunday senate and the amnesty read.

Deterministic, stdlib-only, additive. Old snapshots roll to the permanent
archive instead of being deleted.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional

from .archive import archive_then_trim

TOP_N = 8                 # picks per snapshot (mirrors the briefing wantgot list)
GRADE_WINDOW_DAYS = 10    # keep re-grading snapshots this fresh
KEEP_SNAPSHOTS = 60       # runtime file keeps ~3 months; older -> archive
CONV_BUCKETS = [(0.0, 0.4, "low <0.4"), (0.4, 0.55, "mid 0.4–0.55"),
                (0.55, 0.7, "solid 0.55–0.7"), (0.7, 1.01, "high 0.7+")]


def _load(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _price_map(signals: Dict[str, Any]) -> Dict[str, float]:
    out = {}
    for d in signals.get("debates") or []:
        try:
            t, px = str(d.get("ticker")), float(d.get("price") or 0)
            if t and px > 0:
                out[t] = px
        except Exception:
            continue
    return out


def build_report_card(out_dir: str) -> Dict[str, Any]:
    out = Path(out_dir)
    signals = _load(out / "signals.json", {})
    scoring = _load(out / "scoring.json", {})
    prev = _load(out / "report_card.json", {})
    ledger = _load(out / "decision_ledger.json", {})
    deals = _load(out / "deal_journal.json", {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prices = _price_map(signals)

    # ── 1. snapshot today's top BUY-side picks (once per day) ──────────────
    snapshots: List[Dict[str, Any]] = list(prev.get("snapshots") or [])
    if not any(s.get("date") == today for s in snapshots):
        cands = []
        for d in signals.get("debates") or []:
            c = d.get("consensus") or {}
            if c.get("signal") in ("BUY", "STRONG_BUY"):
                try:
                    cands.append({"ticker": d.get("ticker"),
                                  "signal": c.get("signal"),
                                  "score": round(float(c.get("score") or 0), 3),
                                  "price": float(d.get("price") or 0)})
                except Exception:
                    continue
        cands = [c for c in cands if c["price"] > 0]
        cands.sort(key=lambda x: x["score"], reverse=True)
        if cands:
            snap = {"date": today, "picks": cands[:TOP_N]}
            # THE WOULDN'T COHORT: names the engine wanted but OUR gates held
            # back today. Graded alongside the picks, so the page answers:
            # did the gates save us or cost us?
            GATE_CATS = {"blocked_correlation_book", "deferred_order_quality",
                         "blocked_composite_halt", "blocked_no_session_match",
                         "deferred_submit_market_closed"}
            seen = set()
            wouldnt = []
            for r in (ledger.get("rows") or []):
                if (str(r.get("ts", "")).startswith(today)
                        and r.get("category") in GATE_CATS):
                    t = str(r.get("ticker") or "").upper()
                    if t and t not in seen and prices.get(t):
                        seen.add(t)
                        wouldnt.append({"ticker": t, "gate": r.get("category"),
                                        "price": prices[t]})
            if wouldnt:
                snap["wouldnt"] = wouldnt[:TOP_N]
            snapshots.append(snap)

    # ── re-grade every recent snapshot against today's prices ──────────────
    for s in snapshots:
        try:
            age = (datetime.fromisoformat(today)
                   - datetime.fromisoformat(s["date"])).days
        except Exception:
            age = 999
        if age > GRADE_WINDOW_DAYS:
            continue
        rets = []
        for p in s.get("picks") or []:
            cur = prices.get(p.get("ticker"))
            if cur and p.get("price"):
                p["ret_pct"] = round((cur / p["price"] - 1.0) * 100, 3)
                p["graded_at"] = today
            if p.get("ret_pct") is not None:
                rets.append(p["ret_pct"])
        wrets = []
        for p in s.get("wouldnt") or []:
            cur = prices.get(p.get("ticker"))
            if cur and p.get("price"):
                p["ret_pct"] = round((cur / p["price"] - 1.0) * 100, 3)
            if p.get("ret_pct") is not None:
                wrets.append(p["ret_pct"])
        if wrets:
            s["cohort_wouldnt"] = {"n": len(wrets),
                                   "avg_ret_pct": round(sum(wrets) / len(wrets), 3),
                                   "hit_rate": round(sum(1 for r in wrets if r > 0)
                                                     / len(wrets), 3)}
        if rets:
            s["cohort"] = {"n": len(rets),
                           "avg_ret_pct": round(sum(rets) / len(rets), 3),
                           "median_ret_pct": round(median(rets), 3),
                           "hit_rate": round(sum(1 for r in rets if r > 0)
                                             / len(rets), 3),
                           "days_held": age}

    snapshots = archive_then_trim(out, "report_card_snapshots",
                                  snapshots, KEEP_SNAPSHOTS)
    series = [{"date": s["date"], **(s.get("cohort") or {})}
              for s in snapshots if s.get("cohort")]

    # ── 2. the judge, judged: conviction calibration on CLEAN outcomes ─────
    outs = [o for o in (scoring.get("outcomes") or [])
            if not o.get("stale_price_suspected")
            and isinstance(o.get("return_pct"), (int, float))
            and o.get("signal") in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL")]
    calib = []
    for lo, hi, label in CONV_BUCKETS:
        # directional return: a SELL call "wins" when the stock falls
        rs = [(-o["return_pct"] if str(o.get("signal", "")).endswith("SELL")
               else o["return_pct"])
              for o in outs if lo <= float(o.get("conviction") or 0) < hi]
        if rs:
            calib.append({"bucket": label, "n": len(rs),
                          "avg_dir_ret_pct": round(sum(rs) / len(rs), 3),
                          "hit_rate": round(sum(1 for r in rs if r > 0)
                                            / len(rs), 3)})
    verdict = "not enough clean evidence yet"
    if len(calib) >= 2 and calib[0].get("n", 0) >= 30 and calib[-1].get("n", 0) >= 30:
        edge = calib[-1]["avg_dir_ret_pct"] - calib[0]["avg_dir_ret_pct"]
        if edge > 0.10:
            verdict = (f"conviction is EARNING: high-conviction calls beat "
                       f"low by {edge:+.2f}% — the judge has signal")
        elif edge < -0.10:
            verdict = (f"INVERTED: high conviction is doing WORSE by "
                       f"{edge:+.2f}% — the judge is miscalibrated and the "
                       f"belief loop should be doing the heavy lifting")
        else:
            verdict = (f"flat ({edge:+.2f}%): conviction isn't predictive yet "
                       f"— treat scores as opinions, not edges")

    # ── 3. agents on clean evidence (the senate/amnesty table) ─────────────
    per: Dict[str, Dict[str, Any]] = {}
    for o in outs:
        a = str(o.get("agent") or "?")
        d = per.setdefault(a, {"agent": a, "n": 0, "wins": 0, "sum_ret": 0.0})
        r = (-o["return_pct"] if str(o.get("signal", "")).endswith("SELL")
             else o["return_pct"])
        d["n"] += 1
        d["wins"] += 1 if r > 0 else 0
        d["sum_ret"] += r
    agents_clean = sorted(
        ({"agent": d["agent"], "clean_calls": d["n"],
          "hit_rate": round(d["wins"] / d["n"], 3),
          "avg_dir_ret_pct": round(d["sum_ret"] / d["n"], 3)}
         for d in per.values() if d["n"] >= 5),
        key=lambda x: x["avg_dir_ret_pct"], reverse=True)

    # ── HEADLINE EDGE, ON TRIAL: Wilson 95% intervals decide whether the
    # news-backed vs silent split is EVIDENCE or still HYPOTHESIS. ──────────
    def _wilson(w: int, n: int):
        if n <= 0:
            return (0.0, 0.0, 1.0)
        z = 1.96
        p = w / n
        den = 1 + z * z / n
        ctr = (p + z * z / (2 * n)) / den
        rad = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
        return (p, max(0.0, ctr - rad), min(1.0, ctr + rad))

    headline_edge = None
    try:
        nvs = deals.get("news_vs_silence") or {}
        nb = (deals.get("news_backed") or nvs.get("news_backed")
              or nvs.get("news-backed") or {})
        sl = deals.get("silent") or nvs.get("silent") or {}
        n1, n0 = int(nb.get("n") or 0), int(sl.get("n") or 0)
        if n1 and n0:
            w1 = int(round(float(nb.get("win_rate") or 0) * n1))
            w0 = int(round(float(sl.get("win_rate") or 0) * n0))
            p1, lo1, hi1 = _wilson(w1, n1)
            p0, lo0, hi0 = _wilson(w0, n0)
            sep = lo1 > hi0 or lo0 > hi1
            verdict = ("EVIDENCE: the intervals separate — headline deals are "
                       "genuinely different" if sep else
                       f"HYPOTHESIS, not edge yet: win-rate CIs overlap "
                       f"({lo1:.0%}–{hi1:.0%} vs {lo0:.0%}–{hi0:.0%}); at this "
                       f"gap you need roughly {max(0, 120 - n1)} more headline "
                       f"deals before the intervals can separate")
            headline_edge = {
                "news_backed": {"n": n1, "win_rate": round(p1, 3),
                                "ci": [round(lo1, 3), round(hi1, 3)],
                                "avg_return": nb.get("avg_return")},
                "silent": {"n": n0, "win_rate": round(p0, 3),
                           "ci": [round(lo0, 3), round(hi0, 3)],
                           "avg_return": sl.get("avg_return")},
                "avg_return_gap_pp": round(float(nb.get("avg_return") or 0)
                                           - float(sl.get("avg_return") or 0), 3),
                "verdict": verdict,
            }
    except Exception:
        headline_edge = None

    # ── DEPLOYMENT-ADJUSTED truth for "vs the market": beating a falling
    # benchmark while mostly cash is beta avoidance, not selection alpha.
    # alpha_adj = portfolio_ret − deployment × benchmark_ret. ───────────────
    deployment_adjusted = None
    try:
        eq = cash = 0.0
        for fn in ("alpaca_paper_state.json", "alpaca_h3_state.json",
                   "alpaca_h5_state.json"):
            a = (_load(out / fn, {}) or {}).get("account") or {}
            eq += float(a.get("equity") or 0)
            cash += float(a.get("cash") or 0)
        if eq > 0:
            deployed = (eq - cash) / eq
            port_ret_mo = (eq / 30000.0 - 1.0) * 100
            deployment_adjusted = {
                "deployed_frac": round(deployed, 3),
                "combined_equity": round(eq, 2),
                "port_ret_vs_principal_pct": round(port_ret_mo, 2),
                "note": ("alpha_adj = port_ret − deployed×benchmark_ret; at "
                         f"{deployed:.0%} deployment, cash alone explains "
                         f"~{(1-deployed)*100:.0f}% of any outperformance vs a "
                         "falling index — the briefing's Δ-vs-SPY is mostly "
                         "defense until this number says otherwise"),
            }
    except Exception:
        deployment_adjusted = None

    # THE GATES, JUDGED: aggregate every graded blocked name per gate.
    gate_bench = {}
    for s_ in snapshots:
        for w in s_.get("wouldnt") or []:
            r = w.get("ret_pct")
            if r is None:
                continue
            g = w.get("gate") or "?"
            acc = gate_bench.setdefault(g, {"n": 0, "s": 0.0, "h": 0})
            acc["n"] += 1
            acc["s"] += float(r)
            acc["h"] += 1 if r > 0 else 0
    gate_bench = {g: {"n": v["n"],
                      "avg_ret_pct": round(v["s"] / v["n"], 3),
                      "hit_rate": round(v["h"] / v["n"], 3)}
                  for g, v in gate_bench.items() if v["n"]}

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": today,
        "snapshots": snapshots,
        "series": series,
        "calibration": {"buckets": calib, "verdict": verdict,
                        "clean_outcomes_used": len(outs)},
        "agents_clean": agents_clean,
        "gate_bench": gate_bench,
        "headline_edge": headline_edge,
        "deployment_adjusted": deployment_adjusted,
        "note": ("Picks are graded against live prices on every run; the judge "
                 "is graded on clean outcomes only; nothing here is ever "
                 "deleted — old rows live in docs/data/archive/."),
    }
    (out / "report_card.json").write_text(json.dumps(payload, indent=2))
    latest = next((s.get("cohort") for s in reversed(snapshots)
                   if s.get("cohort")), None)
    return {"snapshots": len(snapshots),
            "latest_cohort_avg": (latest or {}).get("avg_ret_pct"),
            "clean_outcomes": len(outs),
            "verdict": verdict[:60]}
