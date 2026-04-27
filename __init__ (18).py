"""
silmaril.analytics.sentiment — Lexicon-based sentiment scoring.

Zero LLM calls. Zero external service. Pure pattern matching over a
finance-tuned word list. Returns a score in [-1.0, +1.0] per article
and an aggregate per ticker.

This is intentionally simple. Finance vocabulary is narrow enough that
a curated lexicon captures most of the signal without the cost,
latency, or dependency hell of a model. Errors are symmetric and
average out across enough articles.
"""

from __future__ import annotations

import re
from typing import List, Tuple


# ─────────────────────────────────────────────────────────────────
# Finance-tuned lexicon
# ─────────────────────────────────────────────────────────────────

POSITIVE = {
    # Earnings & results
    "beat", "beats", "beating", "smashed", "crushed", "exceeded",
    "record", "all-time-high", "ath", "milestone",
    "surge", "surges", "surging", "soared", "soars", "jumped", "jumps",
    "rally", "rallies", "rallied", "rebound", "rebounds", "rebounded",
    "strong", "stronger", "strongest", "robust", "solid", "outperform", "outperformed",
    "upgrade", "upgraded", "upgrades", "upbeat", "bullish",
    # Business
    "profit", "profits", "profitable", "growth", "growing", "expansion",
    "launch", "launched", "breakthrough", "innovative",
    "partnership", "deal", "acquired", "acquires", "acquisition",
    "approved", "approval", "cleared",
    # Guidance
    "raised", "raises", "raising", "lifted", "boosted",
}

NEGATIVE = {
    # Earnings & results
    "miss", "missed", "misses", "missing", "disappointed", "disappointing",
    "plunge", "plunged", "plunges", "tumble", "tumbled", "tumbles",
    "slump", "slumped", "slumps", "crash", "crashed", "crashes",
    "drop", "dropped", "drops", "fall", "fell", "falls", "falling", "decline", "declined",
    "weak", "weaker", "weakest", "soft", "sluggish", "underperform", "underperformed",
    "downgrade", "downgraded", "downgrades", "bearish",
    # Business
    "loss", "losses", "losing", "loses", "unprofitable",
    "layoff", "layoffs", "cut", "cuts", "cutting", "slashed", "slashes",
    "investigation", "lawsuit", "sued", "sues", "fraud", "scandal",
    "recall", "recalled", "halted", "warning", "warned", "warns",
    "probe", "subpoena", "scrutiny",
    # Guidance
    "lowered", "lowers", "reduced", "reduces", "slashed",
    # Macro
    "recession", "inflation-risk", "selloff", "panic",
}

# Negation words that flip the next sentiment term
NEGATORS = {"not", "no", "never", "without", "avoid", "avoided", "fails", "failed", "failing"}


# ─────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────

_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z\-']+")


def score_text(text: str) -> float:
    """Return a sentiment score in [-1.0, +1.0] for a title or sentence."""
    if not text:
        return 0.0
    words = [w.lower() for w in _WORD_RE.findall(text)]
    if not words:
        return 0.0

    pos_hits, neg_hits = 0, 0
    for i, word in enumerate(words):
        negated = i > 0 and words[i - 1] in NEGATORS
        if word in POSITIVE:
            if negated:
                neg_hits += 1
            else:
                pos_hits += 1
        elif word in NEGATIVE:
            if negated:
                pos_hits += 1
            else:
                neg_hits += 1

    if pos_hits == 0 and neg_hits == 0:
        return 0.0
    # Normalize: (pos - neg) / (pos + neg), gives [-1, +1]
    return (pos_hits - neg_hits) / (pos_hits + neg_hits)


def aggregate_ticker_sentiment(
    article_titles: List[str],
) -> Tuple[float, int]:
    """Score many titles and return (avg_score, article_count).

    Zero-article tickers get (0.0, 0). Titles are weighted equally —
    recency weighting happens at the ingestion layer by limiting pulls.
    """
    scores = [score_text(t) for t in article_titles if t]
    if not scores:
        return 0.0, 0
    return sum(scores) / len(scores), len(scores)
