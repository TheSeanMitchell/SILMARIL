"""
silmaril.learning.news_quality

Single-source news (one outlet) is much weaker signal than cross-source
confirmation (3+ outlets reporting). VEIL/SENTIMENT should weigh accordingly.

This module:
  1. Tracks reliability of each news source by historical signal-to-noise
  2. Computes a confirmation score per news event (how many outlets reported)
  3. Boosts/dampens sentiment by quality

Storage: docs/data/news_source_quality.json (PROTECTED)
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


# Default reliability priors by source (rough quality tier)
SOURCE_PRIORS = {
    "reuters.com":           {"alpha": 8, "beta": 2},
    "bloomberg.com":         {"alpha": 8, "beta": 2},
    "wsj.com":               {"alpha": 7, "beta": 3},
    "ft.com":                {"alpha": 7, "beta": 3},
    "cnbc.com":              {"alpha": 5, "beta": 5},
    "marketwatch.com":       {"alpha": 4, "beta": 6},
    "seekingalpha.com":      {"alpha": 3, "beta": 7},
    "yahoo.com":             {"alpha": 4, "beta": 6},
    "benzinga.com":          {"alpha": 3, "beta": 7},
    "twitter.com":           {"alpha": 2, "beta": 8},
    "x.com":                 {"alpha": 2, "beta": 8},
    "stocktwits.com":        {"alpha": 1, "beta": 9},
}


def _normalize_headline(headline: str) -> str:
    """Aggressive normalization for cross-source matching."""
    s = (headline or "").lower()
    s = re.sub(r'[^\w\s]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _topic_hash(headline: str) -> str:
    """Hash of first 8 normalized tokens — rough topic identity."""
    tokens = _normalize_headline(headline).split()
    sig = ' '.join(sorted(set(tokens[:8])))
    return hashlib.md5(sig.encode()).hexdigest()[:16]


def confirmation_score(news_items: List[dict]) -> Dict[str, dict]:
    """
    Group news items by topic and score each by cross-source confirmation.
    Input items: [{ticker, headline, source, published_at}, ...]
    Output: {topic_hash: {n_sources, sources, n_items, avg_quality, ...}}
    """
    by_topic: Dict[str, dict] = {}
    for item in news_items:
        headline = item.get("headline", "")
        if not headline:
            continue
        topic = _topic_hash(headline)
        bucket = by_topic.setdefault(topic, {
            "topic_hash": topic,
            "headlines": [],
            "sources": set(),
            "items": [],
        })
        source = (item.get("source") or "").lower()
        if source:
            bucket["sources"].add(source)
        bucket["items"].append(item)
        bucket["headlines"].append(headline)

    out = {}
    for topic, b in by_topic.items():
        sources = list(b["sources"])
        n_sources = len(sources)
        avg_quality = (
            sum(_source_score(s) for s in sources) / max(1, n_sources)
        )
        out[topic] = {
            "topic_hash": topic,
            "n_sources": n_sources,
            "sources": sources,
            "n_items": len(b["items"]),
            "avg_source_quality": round(avg_quality, 3),
            "sample_headline": b["headlines"][0],
            # Confirmation multiplier: 1.0 single source, 1.5 two, 2.0 three+
            "confirmation_multiplier": (
                1.0 if n_sources == 1 else
                1.5 if n_sources == 2 else
                2.0
            ),
        }
    return out


def _source_score(source: str) -> float:
    s = (source or "").lower()
    for known, prior in SOURCE_PRIORS.items():
        if known in s:
            return prior["alpha"] / (prior["alpha"] + prior["beta"])
    return 0.5  # unknown = neutral prior


def update_source_reliability(
    quality_path: Path,
    source: str,
    signal_was_correct: bool,
) -> None:
    """Update Bayesian reliability of a source based on signal outcome."""
    data = {}
    if quality_path.exists():
        try:
            data = json.loads(quality_path.read_text())
        except Exception:
            data = {}

    s = (source or "").lower()
    if s not in data:
        # Pull prior if known
        prior = next((p for k, p in SOURCE_PRIORS.items() if k in s), {"alpha": 1, "beta": 1})
        data[s] = {"alpha": prior["alpha"], "beta": prior["beta"]}

    if signal_was_correct:
        data[s]["alpha"] += 1
    else:
        data[s]["beta"] += 1

    quality_path.parent.mkdir(parents=True, exist_ok=True)
    quality_path.write_text(json.dumps(data, indent=2))
