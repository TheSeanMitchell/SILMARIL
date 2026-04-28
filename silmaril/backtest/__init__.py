"""
silmaril.backtest — historical replay framework.

Validates agent edge against 2-5 years of yfinance OHLC data BEFORE going live.
No predictions accumulate forever; agents earn or lose their seat at the table
based on out-of-sample performance over a real historical window.

Quick start:
    python -m silmaril.backtest --start 2022-01-01 --end 2026-01-01 --universe demo

Walk-forward validation (out-of-sample testing):
    python -m silmaril.backtest --walk-forward --splits 4 --start 2022-01-01 --end 2026-01-01
"""
from .engine import BacktestEngine, BacktestConfig
from .metrics import score_backtest, regime_sliced_metrics
from .walk_forward import walk_forward_validation

__all__ = [
    "BacktestEngine",
    "BacktestConfig",
    "score_backtest",
    "regime_sliced_metrics",
    "walk_forward_validation",
]
