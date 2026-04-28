"""verify_v2.py — local sanity check for the SILMARIL v2.0 install.

Run this from the repo root after dropping the v2 files in:

    python verify_v2.py

It checks (without making any network calls):
1. Every v2 file is on disk where it should be.
2. Every v2 module imports without error.
3. The 7 new agents instantiate and respond to their interface.
4. The catalysts that need no API key produce sane output.
5. cli.py can be imported and contains the v2 wiring.

Exit code 0 = all green, push with confidence.
Exit code 1 = something is wrong, message tells you what.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


def _ok(msg):
    print(f"  \u2713 {msg}")


def _fail(msg):
    print(f"  \u2717 {msg}")


def main() -> int:
    print("=" * 60)
    print("SILMARIL v2.0 install verification")
    print("=" * 60)

    failures: list[str] = []

    # ------------------------------------------------------------------
    # 1. Files on disk
    # ------------------------------------------------------------------
    print("\n[1/5] Checking files exist on disk...")
    expected = [
        "silmaril/agents/atlas.py",
        "silmaril/agents/nightshade.py",
        "silmaril/agents/cicada.py",
        "silmaril/agents/shepherd.py",
        "silmaril/agents/nomad.py",
        "silmaril/agents/barnacle.py",
        "silmaril/agents/kestrel_plus.py",
        "silmaril/backtest/__init__.py",
        "silmaril/backtest/__main__.py",
        "silmaril/backtest/data_loader.py",
        "silmaril/backtest/engine.py",
        "silmaril/backtest/metrics.py",
        "silmaril/backtest/replay.py",
        "silmaril/backtest/walk_forward.py",
        "silmaril/scoring/__init__.py",
        "silmaril/scoring/regime_sliced.py",
        "silmaril/handoff/multi_llm_consensus.py",
        "silmaril/catalysts/opex.py",
        "silmaril/catalysts/index_rebalance.py",
        "silmaril/catalysts/macro_releases.py",
        "silmaril/catalysts/crypto_unlocks.py",
        "silmaril/catalysts/ex_dividend.py",
        "silmaril/catalysts/earnings_calendar.py",
    ]
    repo = Path(".")
    for p in expected:
        if (repo / p).exists():
            _ok(p)
        else:
            _fail(f"MISSING: {p}")
            failures.append(p)
    if failures:
        print("\nSome v2 files aren't where they should be. Re-check the drop.")
        return 1

    # ------------------------------------------------------------------
    # 2. Imports
    # ------------------------------------------------------------------
    print("\n[2/5] Checking imports...")
    modules = [
        "silmaril.agents.atlas",
        "silmaril.agents.nightshade",
        "silmaril.agents.cicada",
        "silmaril.agents.shepherd",
        "silmaril.agents.nomad",
        "silmaril.agents.barnacle",
        "silmaril.agents.kestrel_plus",
        "silmaril.backtest",
        "silmaril.scoring",
        "silmaril.scoring.regime_sliced",
        "silmaril.handoff.multi_llm_consensus",
        "silmaril.catalysts.opex",
        "silmaril.catalysts.index_rebalance",
        "silmaril.catalysts.macro_releases",
        "silmaril.catalysts.crypto_unlocks",
    ]
    for m in modules:
        try:
            importlib.import_module(m)
            _ok(m)
        except Exception as e:
            _fail(f"IMPORT FAIL {m}: {e}")
            failures.append(m)
    if failures:
        print("\nImport errors above mean a file landed in the wrong place")
        print("or has unfilled dependencies. Fix and re-run.")
        return 1

    # ------------------------------------------------------------------
    # 3. Agent instances respond to interface
    # ------------------------------------------------------------------
    print("\n[3/5] Checking new agents respond to applies_to/evaluate...")
    from silmaril.agents.atlas import atlas
    from silmaril.agents.nightshade import nightshade
    from silmaril.agents.cicada import cicada
    from silmaril.agents.shepherd import shepherd
    from silmaril.agents.nomad import nomad
    from silmaril.agents.barnacle import barnacle
    from silmaril.agents.kestrel_plus import kestrel_plus

    new_agents = [atlas, nightshade, cicada, shepherd, nomad, barnacle, kestrel_plus]
    for a in new_agents:
        for attr in ("codename", "bio", "applies_to", "evaluate"):
            if not hasattr(a, attr):
                _fail(f"{a.__class__.__name__} missing .{attr}")
                failures.append(a.codename)
                break
        else:
            _ok(f"{a.codename:12s} -- bio: {a.bio[:50]}...")

    if failures:
        return 1

    # ------------------------------------------------------------------
    # 4. Catalysts that need no API key
    # ------------------------------------------------------------------
    print("\n[4/5] Checking offline catalysts produce data...")
    from silmaril.catalysts.opex import fetch_opex_calendar
    from silmaril.catalysts.index_rebalance import fetch_index_rebalances
    from silmaril.catalysts.macro_releases import fetch_macro_calendar
    from silmaril.catalysts.crypto_unlocks import fetch_crypto_unlocks

    try:
        opex = fetch_opex_calendar(days_ahead=60) or []
        _ok(f"OPEX: {len(opex)} events in next 60 days")
    except Exception as e:
        _fail(f"OPEX failed: {e}")
        failures.append("opex")
    try:
        idx = fetch_index_rebalances(days_ahead=180) or []
        _ok(f"Index rebalances: {len(idx)} in next 180 days")
    except Exception as e:
        _fail(f"Index rebalance failed: {e}")
        failures.append("index_rebalance")
    try:
        macro = fetch_macro_calendar(days_ahead=60) or []
        _ok(f"Macro releases: {len(macro)} in next 60 days")
    except Exception as e:
        _fail(f"Macro releases failed: {e}")
        failures.append("macro_releases")
    try:
        unlocks = fetch_crypto_unlocks(days_ahead=180) or []
        _ok(f"Crypto unlocks/halvings: {len(unlocks)} in next 180 days")
    except Exception as e:
        _fail(f"Crypto unlocks failed: {e}")
        failures.append("crypto_unlocks")

    if failures:
        return 1

    # ------------------------------------------------------------------
    # 5. cli.py contains v2 wiring
    # ------------------------------------------------------------------
    print("\n[5/5] Checking cli.py was updated...")
    cli_src = Path("silmaril/cli.py").read_text()
    needed = [
        "from .agents.atlas import atlas",
        "from .agents.kestrel_plus import kestrel_plus",
        "atlas, nightshade, cicada, shepherd, nomad, barnacle, kestrel_plus",
        "v2 catalysts",
    ]
    for marker in needed:
        if marker in cli_src:
            _ok(f"cli.py contains: {marker[:60]}")
        else:
            _fail(f"cli.py MISSING: {marker[:60]}")
            failures.append(marker)
    if failures:
        print("\nIt looks like cli.py wasn't replaced with the v2 version.")
        print("Check that you dropped silmaril/cli.py from the v2 package.")
        return 1

    # ------------------------------------------------------------------
    # All green
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  ALL CHECKS PASSED -- v2.0 install is healthy.")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Commit and push to GitHub.")
    print("  2. Run the backtest:")
    print("     pip install yfinance pandas numpy pyarrow")
    print("     python -m silmaril.backtest \\")
    print("         --start 2022-01-01 --end 2026-01-01 \\")
    print("         --universe demo --walk-forward \\")
    print("         --out-dir docs/data")
    return 0


if __name__ == "__main__":
    sys.exit(main())
