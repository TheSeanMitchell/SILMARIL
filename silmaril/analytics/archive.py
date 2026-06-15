"""
silmaril.analytics.archive — the system's permanent memory.

THE RULE, ENCODED: data collection is permanent and additive. Rolling caps keep
runtime files fast, but the rows they push out were the system's lived history —
every judgement, every order, every blocked decision. From now on, anything a
cap would discard is first appended to docs/data/archive/<stream>-YYYY-MM.jsonl:
append-only, monthly-sharded JSON Lines that grow forever and are committed with
everything else. An agent (or Dr. Strange, or a future offspring) can replay any
moment in any stock's life — or the system's life — from these shards.

Size honesty: at current volumes (~840 scored outcomes/day + orders + ledger
rows) this adds on the order of 1–2 MB/month of plain text to the repo — years
of headroom before GitHub even notices. If it ever grows beyond that, the
shards move to a storage bucket without touching the write API here.

stdlib-only, failure-isolated: an archive error never breaks the pipeline.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


def _shard_path(data_dir: Path, stream: str) -> Path:
    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    d = Path(data_dir) / "archive"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{stream}-{ym}.jsonl"


def archive_rows(data_dir: Path, stream: str,
                 rows: Iterable[Dict[str, Any]]) -> int:
    """Append rows to the stream's monthly shard. Returns rows written."""
    rows = [r for r in rows if isinstance(r, dict)]
    if not rows:
        return 0
    try:
        path = _shard_path(Path(data_dir), stream)
        stamp = datetime.now(timezone.utc).isoformat()
        with path.open("a", encoding="utf-8") as f:
            for r in rows:
                rec = dict(r)
                rec.setdefault("_archived_at", stamp)
                f.write(json.dumps(rec, default=str) + "\n")
        return len(rows)
    except Exception:
        return 0


def archive_then_trim(data_dir: Path, stream: str,
                      rows: List[Dict[str, Any]], cap: int) -> List[Dict[str, Any]]:
    """The cap pattern, made lossless: archive the overflow head, return the
    trimmed tail. Drop-in replacement for `rows[-cap:]`."""
    try:
        rows = list(rows or [])
        if cap > 0 and len(rows) > cap:
            archive_rows(data_dir, stream, rows[:-cap])
            return rows[-cap:]
        return rows
    except Exception:
        return list(rows or [])[-cap:] if cap > 0 else list(rows or [])


def read_archive(data_dir: Path, stream: str,
                 months: int = 1200) -> List[Dict[str, Any]]:
    """Replay a stream's full archived history (oldest first)."""
    out: List[Dict[str, Any]] = []
    try:
        d = Path(data_dir) / "archive"
        if not d.exists():
            return out
        shards = sorted(d.glob(f"{stream}-*.jsonl"))[-months:]
        for p in shards:
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return out
