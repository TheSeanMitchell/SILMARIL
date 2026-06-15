"""
ROOT cli.py — RETIRED SHIM (June 12, 2026).

Two cli.py files had drifted apart (root: 2,996 lines / silmaril/cli.py:
3,228 lines — the LIVE one, run by every workflow via `python -m
silmaril`). Per additive law nothing is deleted: the full legacy file is
preserved at attic/cli_root_RETIRED_2026-06-12.py, and this shim forwards
any straggler invocation to the live module so the duplicate can never
drift again. Answering the operator directly: yes, the root copy was
stale; no, we don't delete — we attic and forward.
"""
from silmaril.cli import *          # noqa: F401,F403 — forward everything
from silmaril.cli import main as _main

if __name__ == "__main__":
    _main()
