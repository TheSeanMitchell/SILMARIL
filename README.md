"""
silmaril.ingestion.news — News ingestion via free RSS feeds.

Two free sources, zero API keys, zero rate-limit headaches:

  1. Google News RSS — one search per ticker via news.google.com/rss/search
  2. SEC EDGAR RSS   — 8-K filings stream for material-event awareness

Both are public, both are RSS, both work from any IP with no auth.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import quote

log = logging.getLogger("silmaril.news")


@dataclass
class Article:
    """Normalized article record."""
    id: str
    ticker: Optional[str]
    title: str
    source: str
    url: str
    published_iso: Optional[str] = None
    summary: str = ""

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "title": self.title,
            "source": self.source,
            "url": self.url,
            "published": self.published_iso,
            "summary": self.summary,
        }


# ─────────────────────────────────────────────────────────────────
# Google News RSS (per ticker)
# ─────────────────────────────────────────────────────────────────

GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search"
    "?q={query}&hl=en-US&gl=US&ceid=US:en"
)


def fetch_ticker_news(
    ticker: str,
    name: str,
    max_articles: int = 6,
    polite_delay: float = 0.4,
) -> List[Article]:
    """Fetch recent news for one ticker via Google News RSS.

    polite_delay: seconds between requests when called in a loop (be kind).
    """
    try:
        import feedparser
    except ImportError:
        log.error("feedparser not installed; run: pip install feedparser")
        return []

    # Build a strong query: ticker symbol OR company name
    name_clean = re.sub(r"\s+(Inc\.?|Corporation|Corp\.?|Ltd\.?|Co\.?|Company|Holdings|Group)$", "", name).strip()
    query = f'"{ticker}" OR "{name_clean}"' if name_clean and name_clean != ticker else ticker
    url = GOOGLE_NEWS_RSS.format(query=quote(query))

    try:
        feed = feedparser.parse(url)
    except Exception as e:
        log.warning("Google News RSS failed for %s: %s", ticker, e)
        return []

    articles: List[Article] = []
    for entry in feed.entries[:max_articles]:
        title = entry.get("title", "").strip()
        if not title:
            continue

        # Google News titles come as "Headline - Source Name"
        source = "Google News"
        if " - " in title:
            parts = title.rsplit(" - ", 1)
            if len(parts) == 2 and len(parts[1]) < 60:
                title, source = parts[0].strip(), parts[1].strip()

        link = entry.get("link", "")
        published = entry.get("published", "") or entry.get("updated", "")
        aid = _article_id(ticker, title, source)

        articles.append(Article(
            id=aid,
            ticker=ticker,
            title=title,
            source=source,
            url=link,
            published_iso=published or None,
            summary=(entry.get("summary", "") or "")[:500],
        ))

    if polite_delay > 0:
        time.sleep(polite_delay)

    return articles


def fetch_news_bulk(
    ticker_name_pairs: List[tuple],
    max_articles_per: int = 5,
) -> Dict[str, List[Article]]:
    """Fetch news for many tickers sequentially (with polite delays).

    Returns {ticker: [Article, ...]}. Tickers with no news return [].
    """
    results: Dict[str, List[Article]] = {}
    for i, (ticker, name) in enumerate(ticker_name_pairs):
        try:
            results[ticker] = fetch_ticker_news(ticker, name, max_articles=max_articles_per)
        except Exception as e:
            log.warning("News fetch failed for %s: %s", ticker, e)
            results[ticker] = []
        if i % 10 == 9:
            log.info("News fetched: %d/%d tickers", i + 1, len(ticker_name_pairs))
    return results


# ─────────────────────────────────────────────────────────────────
# SEC EDGAR RSS — 8-K filings stream
# ─────────────────────────────────────────────────────────────────

EDGAR_8K_RSS = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcurrent&type=8-K&company=&dateb=&owner=include&count=40&output=atom"
)


def fetch_recent_8k_filings(limit: int = 40) -> List[Article]:
    """Fetch recent 8-K filings (material events) from EDGAR's public RSS.

    SEC requires a User-Agent header with contact info — we set one below.
    """
    try:
        import feedparser
    except ImportError:
        return []

    # feedparser supports request_headers in recent versions
    try:
        feed = feedparser.parse(
            EDGAR_8K_RSS,
            request_headers={"User-Agent": "SILMARIL Research contact@silmaril.local"},
        )
    except Exception as e:
        log.warning("EDGAR RSS failed: %s", e)
        return []

    articles: List[Article] = []
    for entry in feed.entries[:limit]:
        title = entry.get("title", "").strip()
        if not title:
            continue
        aid = _article_id("SEC", title, "EDGAR")
        articles.append(Article(
            id=aid,
            ticker=_extract_ticker_from_title(title),
            title=title,
            source="SEC EDGAR",
            url=entry.get("link", ""),
            published_iso=entry.get("updated") or entry.get("published"),
            summary=(entry.get("summary", "") or "")[:500],
        ))
    return articles


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

_TICKER_RE = re.compile(r"\(([A-Z]{1,5})\)")


def _extract_ticker_from_title(title: str) -> Optional[str]:
    m = _TICKER_RE.search(title)
    return m.group(1) if m else None


def _article_id(ticker: str, title: str, source: str) -> str:
    raw = f"{ticker}|{title}|{source}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def dedupe_articles(articles: List[Article]) -> List[Article]:
    """Remove duplicate articles by ID."""
    seen = set()
    out = []
    for a in articles:
        if a.id in seen:
            continue
        seen.add(a.id)
        out.append(a)
    return out
