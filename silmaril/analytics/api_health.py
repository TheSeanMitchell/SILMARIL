"""
silmaril.analytics.api_health — the data-plumbing health matrix.

Answers "are our feeds working, and are we burning out?" with what the system
can actually observe, deterministically:

  FRESHNESS  Every key data product's generated_at vs now — a feed that stopped
             writing shows up as stale here first.
  NEWS       Distinct sources and per-source article counts feeding this cycle's
             debates — if a news provider dies or rate-limits us out, its source
             count collapses and the matrix shows it.
  PRICES     Coverage: how many universe names came back with a real price this
             cycle. A price-feed outage reads as a coverage drop.
  BROKER     Per-account: configured flag, last_run age, error backlog.

Note on quotas: most providers don't expose remaining-minutes via API, so true
"X calls left" isn't observable. What IS observable — and what actually matters
— is whether each feed is DELIVERING. Coverage + freshness + error capture is
the honest meter; a provider that rate-limits us manifests here immediately.

Writes docs/data/api_health.json. Read-only; touches nothing else.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

VERSION = "api-health-1.3"  # +storage meter, +cron_pressure (ALPHA 1.0)

# data product -> max healthy age (hours)
FRESHNESS_BUDGET = {
    "signals.json": 24, "scoring.json": 24, "deal_journal.json": 24,
    "alpaca_paper_state.json": 24, "alpaca_h3_state.json": 24, "alpaca_h5_state.json": 24,
    "timing_fingerprint.json": 24, "news_fingerprint.json": 24,
    "drift_sentinel.json": 24, "catalyst_learning.json": 36,
    "market_leaders.json": 36, "debug_stream.json": 24,
}


def _load(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _dump(path: Path, obj: Any) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2, allow_nan=False)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _age_hours(iso: str, now: datetime) -> float:
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return round((now - t).total_seconds() / 3600.0, 1)
    except Exception:
        return math.inf




# ── ALPHA 1.0: storage + cron-aggressiveness meters ─────────────────

def _dir_size_mb(p: Path) -> float:
    total = 0
    try:
        for root, _dirs, files in os.walk(p):
            for fn in files:
                try:
                    total += (Path(root) / fn).stat().st_size
                except OSError:
                    pass
    except Exception:
        return -1.0
    return round(total / (1024 * 1024), 1)


def _storage_block(data_dir: Path) -> Dict[str, Any]:
    """GitHub free-tier storage meter. GitHub recommends repos < 1 GB and
    starts pushing back well before 5 GB; GitHub Pages sites are capped at
    1 GB. We measure what we can see (the working checkout) and grade it.
    The archive layer is the growth engine — its share is shown so the
    migration decision ("trim archive vs move hosts") is informed."""
    data_mb = _dir_size_mb(data_dir)
    archive_mb = _dir_size_mb(data_dir / "archive")
    repo_root = data_dir.resolve().parent.parent  # docs/data -> repo root
    repo_mb = _dir_size_mb(repo_root)
    if repo_mb < 0:
        repo_mb = data_mb
    # THE BREAKDOWN THAT MAKES THE WARNING ACTIONABLE: high-frequency
    # commits of large JSONs compound inside .git far beyond the worktree.
    # worktree tells you what to slim; git_history tells you when to run
    # the compact_history workflow (see REPO_CLEANUP_AUDIT.md).
    git_mb = _dir_size_mb(repo_root / ".git")
    worktree_mb = round(repo_mb - git_mb, 1) if git_mb > 0 else repo_mb
    if repo_mb < 500:
        status, note = "ok", "comfortably inside GitHub free limits"
    elif repo_mb < 1024:
        status, note = "watch", ("approaching the 1 GB Pages/repo comfort "
                                 "line — plan archive compaction")
    elif repo_mb < 2048:
        status, note = "warn", ("over 1 GB: Pages may refuse to build soon; "
                                "compact docs/data/archive or move history "
                                "to a release asset / external store")
    else:
        status, note = "critical", ("migrate now: repo size risks Pages "
                                    "build failures and push warnings")
    return {
        "repo_mb": repo_mb,
        "worktree_mb": worktree_mb,
        "git_history_mb": (git_mb if git_mb > 0 else None),
        "data_dir_mb": data_mb, "archive_mb": archive_mb,
        "archive_share_pct": (round(archive_mb / data_mb * 100.0, 1)
                              if data_mb and data_mb > 0 and archive_mb >= 0
                              else None),
        "status": status, "note": note,
        "limits_reference": {"pages_site_gb": 1, "repo_recommended_gb": 1,
                             "repo_pushback_gb": 5},
    }


# Known free-tier DAILY budgets (static reference; verify on a networked
# pass — providers change terms). est_calls_per_cycle is an engineering
# estimate of this codebase's per-run usage, labeled as such.
_PROVIDER_BUDGETS = {
    "marketaux":     {"free_per_day": 100,  "est_calls_per_cycle": 2},
    "newsapi":       {"free_per_day": 100,  "est_calls_per_cycle": 2},
    "finnhub":       {"free_per_day": 86400, "est_calls_per_cycle": 6,
                      "note": "60/min limit, effectively per-day huge"},
    "alpha_vantage": {"free_per_day": 25,   "est_calls_per_cycle": 0.2},
    "fmp":           {"free_per_day": 250,  "est_calls_per_cycle": 2},
    "twelve_data":   {"free_per_day": 800,  "est_calls_per_cycle": 2},
    "tiingo":        {"free_per_day": 1000, "est_calls_per_cycle": 2},
    "coingecko":     {"free_per_day": 10000, "est_calls_per_cycle": 3},
    "alpaca_paper":  {"free_per_day": 200 * 60 * 24, "est_calls_per_cycle": 30,
                      "note": "200/min — never the binding constraint"},
}


def _cron_pressure_block(clocks: Dict[str, Any]) -> Dict[str, Any]:
    """How aggressive is the cron, really? Observed cycles today (from the
    domain-clock budget counters — every run touches the valuables domain)
    x estimated per-cycle provider calls vs known free-tier budgets.
    HONESTY: per-provider call counts are not individually instrumented
    yet; these are labeled estimates. 'riding the limit' = >70% of budget;
    'over' means expect rate-limit responses — which also show up as
    delivery collapse in the news block above (the real meter)."""
    today = (clocks.get("today_budget") or {}) if isinstance(clocks, dict) else {}
    runs_today = 0
    v = today.get("valuables") or {}
    runs_today = int(v.get("allowed", 0)) + int(v.get("skipped", 0))
    stocks = today.get("stocks") or {}
    stock_runs = int(stocks.get("allowed", 0))
    providers = {}
    worst = "headroom"
    rank = {"headroom": 0, "riding": 1, "over": 2}
    for name, b in _PROVIDER_BUDGETS.items():
        runs = stock_runs if name in ("marketaux", "newsapi", "fmp",
                                       "alpha_vantage") else runs_today
        est = round(runs * float(b["est_calls_per_cycle"]), 1)
        lim = b["free_per_day"]
        pct = round(est / lim * 100.0, 1) if lim else None
        st = ("over" if pct and pct >= 100 else
              "riding" if pct and pct >= 70 else "headroom")
        if rank[st] > rank[worst]:
            worst = st
        providers[name] = {"est_calls_today": est, "free_per_day": lim,
                           "pct_of_budget": pct, "status": st,
                           **({"note": b["note"]} if b.get("note") else {})}
    return {
        "runs_observed_today": runs_today,
        "stock_window_runs_today": stock_runs,
        "providers": providers,
        "overall": worst,
        "doctrine": ("ride the limit, never cross it: push cadence until a "
                     "provider reads 'riding', and treat 'over' + a delivery "
                     "collapse in the news block as the back-off signal"),
        "estimates_note": ("per-cycle call counts are engineering estimates "
                           "until per-provider instrumentation lands "
                           "(roadmap C)"),
    }


def build_api_health(data_dir: Path) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    data_dir = Path(data_dir)

    # 1) freshness of every key product
    files = {}
    fresh_ok = 0
    for name, budget in FRESHNESS_BUDGET.items():
        p = data_dir / name
        if not p.exists():
            files[name] = {"status": "missing", "age_hours": None, "budget_hours": budget}
            continue
        doc = _load(p, {})
        gen = doc.get("generated_at") or doc.get("last_run") or doc.get("ts")
        age = _age_hours(gen, now) if gen else round(
            (now.timestamp() - p.stat().st_mtime) / 3600.0, 1)
        ok = age is not None and age <= budget
        fresh_ok += 1 if ok else 0
        files[name] = {"status": "fresh" if ok else "stale",
                       "age_hours": (None if age == math.inf else age),
                       "budget_hours": budget}

    # 2) news source coverage from this cycle's debates
    sig = _load(data_dir / "signals.json", {})
    debates = sig.get("debates") or []
    src_counts: Dict[str, int] = {}
    art_total = 0
    priced = 0
    for d in debates:
        if isinstance(d.get("price"), (int, float)) and d["price"] > 0:
            priced += 1
        for h in (d.get("recent_headlines") or []):
            s = (h or {}).get("source") or "unknown"
            src_counts[s] = src_counts.get(s, 0) + 1
            art_total += 1
    top_sources = dict(sorted(src_counts.items(), key=lambda kv: -kv[1])[:12])

    # 3) broker plumbing per account
    accounts = {}
    for label, fn in (("LEGACY", "alpaca_paper_state.json"),
                      ("HARVEST_3", "alpaca_h3_state.json"),
                      ("HARVEST_5", "alpaca_h5_state.json")):
        s = _load(data_dir / fn, {})
        errs = s.get("errors") or []
        # AGE-AWARE: a pre-fix error from days ago is HISTORY, not health.
        # recent = last 48h; the UI should read errors_recent_48h and show
        # the historic count dimly. last_error carries its age explicitly.
        def _err_age_h(e):
            try:
                t = str((e if isinstance(e, dict) else {}).get("time")
                        or str(e)[10:36])
                return _age_hours(t[:32], now)
            except Exception:
                return None
        recent = [e for e in errs
                  if (_err_age_h(e) is not None and _err_age_h(e) <= 48)]
        last_age = _err_age_h(errs[-1]) if errs else None
        accounts[label] = {
            "configured": bool(s.get("configured")),
            "last_run_age_hours": _age_hours(s.get("last_run"), now) if s.get("last_run") else None,
            "errors_logged": len(errs),
            "errors_recent_48h": len(recent),
            "last_error": (str(errs[-1])[:160] if errs else None),
            "last_error_age_hours": (round(last_age, 1)
                                     if last_age is not None else None),
            "errors_note": ("all errors historic (none in 48h) — plumbing "
                            "currently clean" if errs and not recent else
                            None),
            "equity": ((s.get("account") or {}).get("equity")),
        }

    n_files = len(FRESHNESS_BUDGET)

    # ── ALPHA 1.0 item #1: domain-clock budgets ─────────────────────
    # Check-only snapshot (never consumes an interval). When the stocks
    # domain is CLOSED this run was an off-window 24/7-cron tick: empty
    # equity news is BY DESIGN, not degradation — don't punish `overall`.
    try:
        from .domain_clock import domain_clock_report
        clocks = domain_clock_report(data_dir, now=now)
    except Exception as e:  # noqa: BLE001
        clocks = {"error": str(e)}
    stocks_gated = not ((clocks.get("domains") or {})
                        .get("stocks", {}).get("open", True))

    news_ok = (len(src_counts) >= 2 and art_total >= 20) or stocks_gated
    price_cov = round(priced / len(debates) * 100.0, 1) if debates else 0.0
    overall = ("healthy" if (fresh_ok == n_files and news_ok and price_cov >= 80)
               else "degraded" if (fresh_ok >= n_files - 2 and price_cov >= 50)
               else "impaired")

    payload = {
        "version": VERSION,
        "generated_at": now.isoformat(),
        "overall": overall,
        "freshness": {"ok": fresh_ok, "total": n_files, "files": files},
        "news": {"distinct_sources": len(src_counts), "articles_in_cycle": art_total,
                 "top_sources": top_sources,
                 "gated_by_domain_clock": stocks_gated,
                 "note": ("Quota note: providers don't expose remaining minutes; "
                          "delivery (sources x volume) is the real meter — a "
                          "rate-limited feed collapses here first.")},
        "prices": {"coverage_pct": price_cov, "priced": priced, "universe": len(debates)},
        "broker": accounts,
        "domain_clocks": clocks,
        "storage": _storage_block(data_dir),
        "cron_pressure": _cron_pressure_block(clocks),
    }
    _dump(data_dir / "api_health.json", payload)
    return {"overall": overall, "fresh": f"{fresh_ok}/{n_files}",
            "sources": len(src_counts), "price_cov": price_cov}


if __name__ == "__main__":  # pragma: no cover
    import sys
    print(json.dumps(build_api_health(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")), indent=2))
