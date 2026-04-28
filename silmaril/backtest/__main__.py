"""
silmaril.backtest.__main__

Command-line entry point. Run with:

  python -m silmaril.backtest --start 2022-01-01 --end 2026-01-01 --universe demo
  python -m silmaril.backtest --start 2022-01-01 --end 2026-01-01 --universe full
  python -m silmaril.backtest --walk-forward --splits 4 --start 2022-01-01 --end 2026-01-01

Universes:
  demo  — ~25 curated tickers (fast)
  full  — full SILMARIL 348-ticker universe (slow, but real)
  custom — pass --tickers SPY,QQQ,AAPL,...

Outputs:
  docs/data/backtest_predictions.json  — every prediction with outcome
  docs/data/backtest_report.json       — leaderboards + regime/asset slices
  docs/data/backtest_walk_forward.json — out-of-sample stability (if --walk-forward)
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


# Curated demo universe — fast to backtest, hits every asset class
DEMO_UNIVERSE = [
    # major indices
    "SPY", "QQQ", "IWM", "DIA",
    # mega-cap equities
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA",
    # sector ETFs
    "XLE", "XLF", "XLK", "XLV", "XLY",
    # commodities / bonds
    "GLD", "SLV", "USO", "TLT", "HYG",
    # crypto
    "BTC-USD", "ETH-USD",
    # FX
    "UUP",
]


def _load_full_universe() -> List[str]:
    """Try to import the real universe from silmaril.universe.core. Falls back to demo."""
    try:
        from silmaril.universe.core import all_entries  # type: ignore
        return [e["ticker"] if isinstance(e, dict) else e for e in all_entries()]
    except Exception as e:
        print(f"[backtest] could not load full universe ({e}); using demo")
        return DEMO_UNIVERSE


def _load_agents(agent_names: List[str]):
    """Load agent instances by name. Falls back to a stub set if real agents
    aren't importable (e.g., when running this module standalone)."""
    try:
        # The real silmaril module exposes these from silmaril.agents
        from silmaril.agents import (  # type: ignore
            AEGIS, FORGE, HEX, KESTREL, ZENITH, JADE, OBSIDIAN,
            VESPA, SYNTH, MAGUS, TALON, THUNDERHEAD, WEAVER,
            VEIL, SPECK,
        )
        registry = {
            "AEGIS": AEGIS, "FORGE": FORGE, "HEX": HEX, "KESTREL": KESTREL,
            "ZENITH": ZENITH, "JADE": JADE, "OBSIDIAN": OBSIDIAN, "VESPA": VESPA,
            "SYNTH": SYNTH, "MAGUS": MAGUS, "TALON": TALON, "THUNDERHEAD": THUNDERHEAD,
            "WEAVER": WEAVER, "VEIL": VEIL, "SPECK": SPECK,
        }
        # also try to load the new v2 agents
        try:
            from silmaril.agents.kestrel_plus import KESTREL_PLUS  # type: ignore
            registry["KESTREL_PLUS"] = KESTREL_PLUS
        except Exception:
            pass
        try:
            from silmaril.agents.atlas import ATLAS  # type: ignore
            registry["ATLAS"] = ATLAS
        except Exception:
            pass
        try:
            from silmaril.agents.shepherd import SHEPHERD  # type: ignore
            registry["SHEPHERD"] = SHEPHERD
        except Exception:
            pass

        if agent_names == ["all"]:
            return [cls() for cls in registry.values()]
        out = []
        for n in agent_names:
            if n in registry:
                out.append(registry[n]())
            else:
                print(f"[backtest] unknown agent '{n}', skipping")
        return out
    except ImportError as e:
        print(f"[backtest] could not import real agents ({e}). Using STUB agents for demo.")
        return _stub_agents()


def _stub_agents():
    """Lightweight demo agents for when real silmaril imports are unavailable.
    Useful for verifying the backtest framework end-to-end on a fresh machine."""
    from dataclasses import dataclass

    @dataclass
    class Verdict:
        signal: str
        conviction: float
        rationale: str

    class StubAgent:
        name = "STUB"
        def judge(self, ctx):
            return Verdict("HOLD", 0.0, "stub")

    class TrendStub(StubAgent):
        name = "TREND_STUB"
        def judge(self, ctx):
            if ctx.sma_20 and ctx.sma_50 and ctx.sma_20 > ctx.sma_50:
                return Verdict("BUY", 0.6, "SMA20 > SMA50")
            return Verdict("HOLD", 0.0, "no trend")

    class MeanRevStub(StubAgent):
        name = "MEANREV_STUB"
        def judge(self, ctx):
            if ctx.rsi_14 is not None and ctx.rsi_14 < 30:
                return Verdict("BUY", 0.7, "RSI oversold")
            if ctx.rsi_14 is not None and ctx.rsi_14 > 70:
                return Verdict("SELL", 0.7, "RSI overbought")
            return Verdict("HOLD", 0.0, "neutral RSI")

    return [TrendStub(), MeanRevStub()]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="SILMARIL historical backtest")
    p.add_argument("--start", default="2022-01-01", help="ISO date (default 2022-01-01)")
    p.add_argument("--end",   default=date.today().isoformat(), help="ISO date (default today)")
    p.add_argument("--universe", choices=["demo", "full", "custom"], default="demo")
    p.add_argument("--tickers", default="", help="Comma-sep tickers (only with --universe custom)")
    p.add_argument("--agents",  default="all", help="Comma-sep agent names, or 'all'")
    p.add_argument("--walk-forward", action="store_true", help="Also run walk-forward validation")
    p.add_argument("--splits", type=int, default=4, help="Walk-forward windows (default 4)")
    p.add_argument("--out-dir", default="docs/data", help="Output directory for JSON")
    p.add_argument("--no-cache", action="store_true", help="Disable on-disk price cache")
    args = p.parse_args(argv)

    start = datetime.fromisoformat(args.start).date()
    end = datetime.fromisoformat(args.end).date()

    if args.universe == "full":
        tickers = _load_full_universe()
    elif args.universe == "custom":
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
        if not tickers:
            print("--universe custom requires --tickers", file=sys.stderr)
            return 2
    else:
        tickers = DEMO_UNIVERSE

    agent_list = ["all"] if args.agents == "all" else [a.strip() for a in args.agents.split(",")]
    agents = _load_agents(agent_list)
    if not agents:
        print("No agents loaded. Exiting.", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = BacktestConfig(
        tickers=tickers,
        start=start,
        end=end,
        agents=agents,
        use_cache=not args.no_cache,
        output_path=str(out_dir / "backtest_predictions.json"),
    )
    engine = BacktestEngine(cfg)
    result = engine.run()

    print()
    print(result.summary())

    # Score predictions
    scores = score_backtest([p.to_dict() for p in result.predictions])
    print(render_leaderboard(scores))

    write_report_json(
        [p.to_dict() for p in result.predictions],
        str(out_dir / "backtest_report.json"),
    )

    if args.walk_forward:
        wf = walk_forward_validation(
            [p.to_dict() for p in result.predictions],
            n_splits=args.splits,
        )
        wf_path = out_dir / "backtest_walk_forward.json"
        with open(wf_path, "w") as f:
            json.dump(wf, f, indent=2, default=str)
        print(f"\n[backtest] wrote walk-forward report to {wf_path}")
        print("\nStability classification (per agent):")
        for name, stab in wf.get("stability_summary", {}).items():
            print(f"  {name:18s}  {stab.get('stability','?'):<18s}  "
                  f"mean_wr={stab.get('mean_win_rate','-')}  spread={stab.get('win_rate_spread','-')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
