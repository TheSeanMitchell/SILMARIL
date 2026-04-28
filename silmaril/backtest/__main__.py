"""
silmaril.backtest.__main__

Command-line entry point. Run with:

  python -m silmaril.backtest --start 2022-01-01 --end 2026-01-01 --universe demo
  python -m silmaril.backtest --start 2022-01-01 --end 2026-01-01 --universe full
  python -m silmaril.backtest --walk-forward --splits 4 --start 2022-01-01 --end 2026-01-01

Universes:
  demo   - ~25 curated tickers (fast, ~5-10 min)
  full   - full SILMARIL ~360-ticker universe (~30-60 min)
  custom - pass --tickers SPY,QQQ,AAPL,...

Outputs:
  docs/data/backtest_predictions.json  - every prediction with outcome
  docs/data/backtest_report.json       - leaderboards + regime/asset slices
  docs/data/backtest_walk_forward.json - out-of-sample stability (if --walk-forward)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import List

from .engine import BacktestEngine, BacktestConfig
from .metrics import score_backtest, render_leaderboard, write_report_json
from .walk_forward import walk_forward_validation


# Curated demo universe - fast to backtest, hits every asset class
DEMO_UNIVERSE = [
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA",
    "XLE", "XLF", "XLK", "XLV", "XLY",
    "GLD", "SLV", "USO", "TLT", "HYG",
    "BTC-USD", "ETH-USD",
    "UUP",
]


def _normalize_universe_entry(entry) -> str:
    """Extract a ticker string from whatever shape all_entries() returns.

    SILMARIL's all_entries() returns list of (ticker, name, sector) tuples.
    Older code may return dicts or plain strings. This handles all three.
    """
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return entry.get("ticker") or entry.get("symbol") or ""
    if isinstance(entry, (tuple, list)) and len(entry) > 0:
        return str(entry[0])
    return str(entry)


def _load_full_universe() -> List[str]:
    """Load the full SILMARIL universe as a list of ticker strings."""
    try:
        from silmaril.universe.core import all_entries  # type: ignore
        raw = all_entries()
        tickers = [_normalize_universe_entry(e) for e in raw]
        # drop any empty strings, dedupe, preserve order
        seen = set()
        out = []
        for t in tickers:
            if t and t not in seen:
                seen.add(t)
                out.append(t)
        return out
    except Exception as e:
        print(f"[backtest] could not load full universe ({e}); using demo")
        return DEMO_UNIVERSE


def _load_agents(agent_names: List[str]):
    """Load real SILMARIL agent instances.

    SILMARIL's agents are exported as lowercase singletons from each module
    (e.g. `from silmaril.agents.aegis import aegis`). They are already
    instantiated; we just collect the references.
    """
    registry: dict = {}

    # Original 15 main voters
    original_modules = [
        ("AEGIS",      "silmaril.agents.aegis",      "aegis"),
        ("FORGE",      "silmaril.agents.forge",      "forge"),
        ("THUNDERHEAD","silmaril.agents.thunderhead","thunderhead"),
        ("JADE",       "silmaril.agents.jade",       "jade"),
        ("VEIL",       "silmaril.agents.veil",       "veil"),
        ("KESTREL",    "silmaril.agents.kestrel",    "kestrel"),
        ("OBSIDIAN",   "silmaril.agents.obsidian",   "obsidian"),
        ("ZENITH",     "silmaril.agents.zenith",     "zenith"),
        ("WEAVER",     "silmaril.agents.weaver",     "weaver"),
        ("HEX",        "silmaril.agents.hex_agent",  "hex_agent"),
        ("SYNTH",      "silmaril.agents.synth",      "synth"),
        ("SPECK",      "silmaril.agents.speck",      "speck"),
        ("VESPA",      "silmaril.agents.vespa",      "vespa"),
        ("MAGUS",      "silmaril.agents.magus",      "magus"),
        ("TALON",      "silmaril.agents.talon",      "talon"),
    ]
    # 7 v2 agents
    v2_modules = [
        ("ATLAS",      "silmaril.agents.atlas",      "atlas"),
        ("NIGHTSHADE", "silmaril.agents.nightshade", "nightshade"),
        ("CICADA",     "silmaril.agents.cicada",     "cicada"),
        ("SHEPHERD",   "silmaril.agents.shepherd",   "shepherd"),
        ("NOMAD",      "silmaril.agents.nomad",      "nomad"),
        ("BARNACLE",   "silmaril.agents.barnacle",   "barnacle"),
        ("KESTREL+",   "silmaril.agents.kestrel_plus", "kestrel_plus"),
    ]

    import importlib
    for label, mod_path, attr in original_modules + v2_modules:
        try:
            mod = importlib.import_module(mod_path)
            inst = getattr(mod, attr)
            registry[label] = inst
        except Exception as e:
            print(f"[backtest] could not load {label}: {e}")

    if not registry:
        print("[backtest] no agents loaded - falling back to STUB agents")
        return _stub_agents()

    print(f"[backtest] loaded {len(registry)} real agents: {', '.join(registry.keys())}")

    # Filter to requested set
    if agent_names == ["all"]:
        return list(registry.values())
    out = []
    for n in agent_names:
        if n in registry:
            out.append(registry[n])
        else:
            print(f"[backtest] unknown agent: {n}")
    return out


def _stub_agents():
    """Fallback set of 2 simple stub agents for standalone testing."""
    from .replay import BacktestContext

    class _Stub:
        def __init__(self, name): self.codename = name
        def applies_to(self, ctx): return True

    class TrendStub(_Stub):
        def __init__(self): super().__init__("TREND_STUB")
        def evaluate(self, ctx):
            from silmaril.agents.base import Verdict, Signal
            mom = getattr(ctx, "momentum_20d", 0) or 0
            if mom > 0.02:
                return Verdict(agent=self.codename, ticker=ctx.ticker,
                               signal=Signal.BUY, conviction=0.5,
                               rationale=f"momentum {mom:+.1%}")
            return Verdict(agent=self.codename, ticker=ctx.ticker,
                           signal=Signal.HOLD, conviction=0.0, rationale="flat")

    class MeanRevStub(_Stub):
        def __init__(self): super().__init__("MEANREV_STUB")
        def evaluate(self, ctx):
            from silmaril.agents.base import Verdict, Signal
            rsi = getattr(ctx, "rsi_14", 50) or 50
            if rsi >= 75:
                return Verdict(agent=self.codename, ticker=ctx.ticker,
                               signal=Signal.SELL, conviction=0.5, rationale=f"RSI {rsi:.0f}")
            if rsi <= 25:
                return Verdict(agent=self.codename, ticker=ctx.ticker,
                               signal=Signal.BUY, conviction=0.5, rationale=f"RSI {rsi:.0f}")
            return Verdict(agent=self.codename, ticker=ctx.ticker,
                           signal=Signal.HOLD, conviction=0.0, rationale="neutral")

    return [TrendStub(), MeanRevStub()]


def main():
    parser = argparse.ArgumentParser(description="SILMARIL backtest framework")
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="2026-01-01")
    parser.add_argument("--universe", choices=["demo", "full", "custom"], default="demo")
    parser.add_argument("--tickers", default="", help="comma-separated tickers (custom only)")
    parser.add_argument("--agents", default="all", help="comma-separated agent names, or 'all'")
    parser.add_argument("--walk-forward", action="store_true")
    parser.add_argument("--splits", type=int, default=4)
    parser.add_argument("--out-dir", default="docs/data")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    # Resolve universe (always returns flat list of ticker strings)
    if args.universe == "demo":
        tickers = DEMO_UNIVERSE
    elif args.universe == "full":
        tickers = _load_full_universe()
    else:
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
        if not tickers:
            print("[backtest] --tickers required for custom universe")
            sys.exit(2)

    agent_names = ["all"] if args.agents == "all" else [a.strip() for a in args.agents.split(",")]
    agents = _load_agents(agent_names)
    if not agents:
        print("[backtest] no agents loaded - aborting")
        sys.exit(1)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    config = BacktestConfig(
        start=datetime.strptime(args.start, "%Y-%m-%d").date(),
        end=datetime.strptime(args.end, "%Y-%m-%d").date(),
        tickers=tickers,
        agents=agents,
        use_cache=not args.no_cache,
        output_path=out_dir / "backtest_predictions.json",
    )

    engine = BacktestEngine(config)
    result = engine.run()
    print(f"[backtest] {len(result.predictions)} predictions written to {config.output_path}")

    # The scoring/walk-forward code reads predictions as dicts (p["agent"], p["signal"], ...)
    # so convert the Prediction dataclasses once here.
    pred_dicts = [p.to_dict() for p in result.predictions]

    # Score and write report
    scores = score_backtest(pred_dicts)
    report_path = out_dir / "backtest_report.json"
    write_report_json(pred_dicts, str(report_path))
    print(f"[backtest] report written to {report_path}")
    print()
    print(render_leaderboard(scores))

    # Walk-forward
    if args.walk_forward:
        wf_path = out_dir / "backtest_walk_forward.json"
        wf = walk_forward_validation(pred_dicts, n_splits=args.splits)
        with wf_path.open("w") as f:
            json.dump(wf, f, indent=2, default=str)
        print(f"[backtest] walk-forward report written to {wf_path}")


if __name__ == "__main__":
    sys.exit(main())
