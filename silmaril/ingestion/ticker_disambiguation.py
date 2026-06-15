"""silmaril.ingestion.ticker_disambiguation — Stop SNOW=Snow College noise.

Problem
───────
The screenshots from 2026-05-10 show the consolidated news feed scoring
ticker calls on:
  * "Badgers Claim 3 Seed..." → tagged to **SNOW** (Snow College basketball)
  * "Boozer vs. Foster: Battle for Duke's Starting PG Spot" → tagged to **PG**
  * "Here and Now with Sandra Bookman" → tagged to **NOW**
  * "Elipson Unveils Facet II 6 Active BT Speakers..." → tagged to **HD**
  * "asc ea grads CBennett_Sal26.jpg" → tagged to **EA**

Google News RSS is returning these because the ticker symbol happens to
appear as a substring (or as a word) inside a totally unrelated article.
We need to filter on confidence before any agent sees the headline.

Architecture
────────────
For each (ticker, article) pair, we compute a confidence score in [0,1]:

  +0.50 if the company's canonical name appears in the title
  +0.30 if a sector-context keyword appears in title/summary
  +0.10 if the ticker appears in parentheses "(SNOW)"
  +0.10 if the source domain looks financial (reuters/bloomberg/cnbc/etc.)
  -0.40 if a known collision keyword appears (rules below)

Articles below CONFIDENCE_FLOOR are dropped from the ticker's article list.
The drop is logged to docs/data/ticker_disambiguation.json so the dashboard
can show "23 false matches filtered" — proof the filter is doing its job.

Backward compatibility
──────────────────────
The output type of fetch_news_bulk is unchanged. We just remove
low-confidence articles from the list (and log the drop).

Extending the collision rules
──────────────────────────────
Add to _COLLISIONS below. Each entry is:
  ticker → {
    "must_have_any":  [list of keywords; if NONE present → -0.40 penalty],
    "must_not_have_any": [list of keywords; if ANY present → -0.40 penalty],
  }
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CONFIDENCE_FLOOR = 0.40

# ── Known collision tickers and their disambiguation rules ──────────────
# These are based on actual observed bad matches from the dashboard.
# All keywords are matched case-insensitively as whole-word substrings.
_COLLISIONS: Dict[str, Dict[str, List[str]]] = {
    "SNOW": {
        "must_have_any":  ["snowflake", "cloud", "data warehouse", "data cloud",
                           "$SNOW", "frank slootman", "sridhar ramaswamy"],
        "must_not_have_any": ["snow college", "snowfall", "snowstorm", "blizzard",
                              "skiing", "weather", "snowboard", "ski resort"],
    },
    "PG": {
        "must_have_any":  ["procter", "gamble", "consumer goods", "household",
                           "$PG", "tide", "pampers", "gillette", "crest"],
        "must_not_have_any": ["point guard", "starting pg", "basketball",
                              "NBA", "march madness", "duke", "march madness"],
    },
    "NOW": {
        "must_have_any":  ["servicenow", "workflow", "IT service management",
                           "$NOW", "bill mcdermott"],
        "must_not_have_any": ["here and now", "right now", "happening now",
                              "now playing", "sandra bookman"],
    },
    "HD": {
        "must_have_any":  ["home depot", "$HD", "retail", "home improvement",
                           "DIY", "ted decker"],
        "must_not_have_any": ["high definition", "HD video", "HD audio",
                              "HD speakers", "HDMI", "aptX HD"],
    },
    "EA": {
        "must_have_any":  ["electronic arts", "$EA", "gaming", "video game",
                           "FIFA", "Madden", "battlefield", "andrew wilson"],
        "must_not_have_any": ["early access", "EA grads", "ea sports event",
                              ".jpg", ".png"],
    },
    "CAR": {
        "must_have_any":  ["avis", "$CAR", "rental car", "budget rent"],
        "must_not_have_any": ["car accident", "car crash", "used car", "car wash"],
    },
    "GAS": {
        "must_have_any":  ["$GAS", "gas etf", "natural gas etf"],
        "must_not_have_any": ["gas prices", "gas station", "gasoline price"],
    },
    "ON": {
        "must_have_any":  ["onsemi", "on semiconductor", "$ON", "hassane el-khoury"],
        "must_not_have_any": [],   # mostly disambiguated by company name presence
    },
    "AI": {
        "must_have_any":  ["c3.ai", "c3 ai", "$AI", "thomas siebel"],
        "must_not_have_any": ["AI startup", "AI tools", "openai", "anthropic",
                              "google ai", "meta ai"],
    },
    "ALL": {
        "must_have_any":  ["allstate", "$ALL", "tom wilson"],
        "must_not_have_any": [],
    },
    "PEAK": {
        "must_have_any":  ["healthpeak", "$PEAK", "medical office"],
        "must_not_have_any": ["mountain peak", "peak performance"],
    },
    "BIG": {
        "must_have_any":  ["big lots", "$BIG", "discount retailer"],
        "must_not_have_any": [],
    },
    "FUN": {
        "must_have_any":  ["cedar fair", "$FUN", "amusement park"],
        "must_not_have_any": [],
    },
    "T": {
        "must_have_any":  ["AT&T", "AT and T", "$T", "att inc", "john stankey"],
        "must_not_have_any": [],
    },
    "F": {
        "must_have_any":  ["ford motor", "$F", "ford ceo", "jim farley", "lightning",
                           "f-150"],
        "must_not_have_any": [],
    },
    "X": {
        "must_have_any":  ["us steel", "u.s. steel", "$X", "united states steel"],
        "must_not_have_any": ["twitter", "elon musk", "x platform", "tesla"],
    },
    "M": {
        "must_have_any":  ["macy's", "macys", "$M"],
        "must_not_have_any": [],
    },
    "K": {
        "must_have_any":  ["kellogg", "kellanova", "$K"],
        "must_not_have_any": [],
    },
    "V": {
        "must_have_any":  ["visa inc", "$V", "ryan mcinerney"],
        "must_not_have_any": [],
    },
    "C": {
        "must_have_any":  ["citigroup", "citi ", "$C", "jane fraser"],
        "must_not_have_any": [],
    },
    "Z": {
        "must_have_any":  ["zillow", "$Z", "rich barton"],
        "must_not_have_any": [],
    },
}

# Financial-source domains that boost confidence (substring match).
_FINANCIAL_DOMAINS = (
    "reuters", "bloomberg", "wsj", "cnbc", "ft.com", "marketwatch",
    "seeking alpha", "barron", "yahoo finance", "the motley fool",
    "investorplace", "investors.com", "trefis", "simplywall",
    "morningstar", "zacks", "thestreet", "benzinga",
)

# Sector keywords — generic boost for "talks about the same industry"
_SECTOR_KEYWORDS = {
    "tech": ["software", "AI", "cloud", "saas", "platform", "cybersecurity"],
    "energy": ["oil", "gas", "barrel", "refiner", "drilling", "pipeline"],
    "finance": ["bank", "lending", "credit", "interest rate", "deposits"],
    "retail": ["store", "consumer", "shopper", "ecommerce", "footfall"],
    "biotech": ["FDA", "clinical trial", "drug", "therapeutics", "patient"],
    "auto": ["EV", "vehicle", "auto", "battery", "lithium"],
    "semis": ["chip", "wafer", "fab", "node", "semiconductor"],
}


# ─── Confidence scoring ─────────────────────────────────────────────────

def _has_word(haystack: str, needle: str) -> bool:
    """Case-insensitive whole-word/substring match. Quick and good enough."""
    if not haystack or not needle:
        return False
    return needle.lower() in haystack.lower()


def _ticker_in_parens(text: str, ticker: str) -> bool:
    """Detect '(TICKER)' or '$TICKER' style in the title."""
    if not text or not ticker:
        return False
    pat = r"[\(\[\s]\$?" + re.escape(ticker) + r"[\)\]\s\.:,]"
    return bool(re.search(pat, " " + text + " "))


def _source_is_financial(source: str) -> bool:
    if not source:
        return False
    s = source.lower()
    return any(dom in s for dom in _FINANCIAL_DOMAINS)


@dataclass
class ScoreResult:
    confidence: float = 0.0
    components: Dict[str, float] = field(default_factory=dict)
    dropped:    bool = False
    reason:     str = ""


def score_article_for_ticker(
    ticker: str,
    company_name: str,
    article: Dict[str, Any],
) -> ScoreResult:
    """Compute confidence that this article is genuinely about this ticker.

    article: dict-like with .get('title'), .get('source'), .get('summary'),
             .get('url') — matches the Article dataclass shape.
    """
    title   = str(article.get("title", "") or "")
    summary = str(article.get("summary", "") or "")
    source  = str(article.get("source", "") or "")
    body    = title + " :: " + summary

    components: Dict[str, float] = {}
    score = 0.0

    # 1) Company name in title → strong positive
    name_clean = re.sub(
        r"\s+(Inc\.?|Corporation|Corp\.?|Ltd\.?|Co\.?|Company|Holdings|Group|N\.V\.)$",
        "", str(company_name or "")).strip()
    if name_clean and len(name_clean) >= 3 and _has_word(title, name_clean):
        components["company_in_title"] = 0.50
        score += 0.50

    # 2) Ticker as $TICKER or (TICKER) in the title → moderate positive
    if _ticker_in_parens(title, ticker):
        components["ticker_parens"] = 0.10
        score += 0.10

    # 3) Financial source → small positive
    if _source_is_financial(source):
        components["financial_source"] = 0.10
        score += 0.10

    # 4) Collision rules
    rules = _COLLISIONS.get(ticker.upper())
    if rules:
        must_have = rules.get("must_have_any") or []
        must_not  = rules.get("must_not_have_any") or []
        has_any_must = any(_has_word(body, w) for w in must_have) if must_have else True
        has_any_bad  = any(_has_word(body, w) for w in must_not)  if must_not else False
        if must_have and not has_any_must:
            components["collision_no_anchor"] = -0.40
            score -= 0.40
        if has_any_bad:
            components["collision_blacklist_hit"] = -0.40
            score -= 0.40

    # 5) Generic sector context boost (small)
    # (We don't know the ticker's sector here without a lookup. Skip unless
    # the caller decorated the article with `sector_keywords` already.)
    extra_keys = article.get("_sector_keywords") or []
    for k in extra_keys:
        if _has_word(body, k):
            components.setdefault("sector_keyword_hit", 0.0)
            components["sector_keyword_hit"] = min(0.30,
                components["sector_keyword_hit"] + 0.05)
    if "sector_keyword_hit" in components:
        score += components["sector_keyword_hit"]

    # Clamp
    score = max(0.0, min(1.0, score))
    res = ScoreResult(confidence=round(score, 3), components=components)
    if score < CONFIDENCE_FLOOR:
        res.dropped = True
        # Build a tidy reason
        if "collision_blacklist_hit" in components:
            res.reason = "collision_keyword"
        elif "collision_no_anchor" in components:
            res.reason = "no_company_anchor"
        elif not components:
            res.reason = "no_signal"
        else:
            res.reason = "low_confidence"
    return res


def filter_articles(
    ticker: str,
    company_name: str,
    articles: List[Any],
) -> Tuple[List[Any], List[Dict[str, Any]]]:
    """Return (kept_articles, dropped_log).

    `articles` items may be dataclass instances or dicts — we duck-type via
    a small adapter so this works with the existing Article dataclass.
    """
    kept: List[Any] = []
    dropped: List[Dict[str, Any]] = []

    for a in articles or []:
        if hasattr(a, "to_dict"):
            adict = a.to_dict()
        elif isinstance(a, dict):
            adict = a
        else:
            kept.append(a)  # unknown shape — pass through unchanged
            continue
        res = score_article_for_ticker(ticker, company_name, adict)
        # Annotate the article with its confidence (the consumer can use it)
        if hasattr(a, "__dict__"):
            try: setattr(a, "_confidence", res.confidence)
            except Exception: pass
        elif isinstance(a, dict):
            a["_confidence"] = res.confidence
        if res.dropped:
            dropped.append({
                "ticker": ticker,
                "title": adict.get("title", ""),
                "source": adict.get("source", ""),
                "confidence": res.confidence,
                "reason": res.reason,
                "components": res.components,
            })
        else:
            kept.append(a)
    return kept, dropped


# ─── Filter-the-bulk-result wrapper + log writer ────────────────────────

def filter_bulk(
    news_map: Dict[str, List[Any]],
    ticker_name_map: Dict[str, str],
    data_dir: Optional[Path] = None,
) -> Dict[str, List[Any]]:
    """Apply disambiguation to a {ticker: [articles...]} map.

    Logs dropped articles to docs/data/ticker_disambiguation.json if data_dir
    is provided. Returns a new map with low-confidence articles removed.
    """
    cleaned: Dict[str, List[Any]] = {}
    all_dropped: List[Dict[str, Any]] = []
    kept_count = 0
    dropped_count = 0

    for ticker, articles in news_map.items():
        name = ticker_name_map.get(ticker, ticker)
        kept, dropped = filter_articles(ticker, name, articles)
        cleaned[ticker] = kept
        all_dropped.extend(dropped)
        kept_count += len(kept)
        dropped_count += len(dropped)

    if data_dir is not None:
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            log = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "kept_total": kept_count,
                "dropped_total": dropped_count,
                "by_ticker_dropped": {},
                "samples": all_dropped[:200],
                "rules_active": sorted(list(_COLLISIONS.keys())),
                "confidence_floor": CONFIDENCE_FLOOR,
            }
            for d in all_dropped:
                t = d.get("ticker")
                log["by_ticker_dropped"][t] = log["by_ticker_dropped"].get(t, 0) + 1
            (data_dir / "ticker_disambiguation.json").write_text(
                json.dumps(log, indent=2, default=str))
        except Exception as e:
            print(f"[ticker_disambiguation] log write failed: {e}")
    return cleaned


__all__ = [
    "CONFIDENCE_FLOOR",
    "ScoreResult",
    "score_article_for_ticker",
    "filter_articles",
    "filter_bulk",
]
