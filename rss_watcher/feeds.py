"""Downloading RSS/Atom feeds and turning them into clean `Item` objects."""

from __future__ import annotations

import asyncio
import html
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser
import httpx

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "rss-watcher-bot/1.0 (+https://github.com/)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
}
_TAG_RE = re.compile(r"<[^>]+>")


class FeedError(RuntimeError):
    """The URL could not be fetched or is not an RSS/Atom feed."""


@dataclass(frozen=True)
class Item:
    key: str  # stable unique id: guid, else link, else title
    title: str
    link: str
    summary: str
    published: datetime | None
    feed_title: str


def _clean(text: str, limit: int = 300) -> str:
    """Strip HTML tags/entities and collapse whitespace."""
    text = html.unescape(_TAG_RE.sub(" ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _published(entry: feedparser.FeedParserDict) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def parse_feed(content: bytes | str) -> tuple[str, list[Item]]:
    """Parse RSS/Atom content. Returns (feed title, items). Raises FeedError if not a feed."""
    parsed = feedparser.parse(content)
    # feedparser accepts almost anything; a real feed has a detected version (rss20, atom10…)
    if not parsed.get("version") and not parsed.entries:
        raise FeedError("This doesn't look like an RSS/Atom feed.")
    feed_title = _clean(parsed.feed.get("title", ""), 80) or "Feed"
    items: list[Item] = []
    for entry in parsed.entries:
        title = _clean(entry.get("title", ""), 200)
        link = entry.get("link", "")
        key = entry.get("id") or link or title
        if not key:
            continue
        items.append(
            Item(
                key=str(key),
                title=title or "(no title)",
                link=link,
                summary=_clean(entry.get("summary", "")),
                published=_published(entry),
                feed_title=feed_title,
            )
        )
    return feed_title, items


def normalize(text: str) -> str:
    """Lowercase and strip diacritics, so 'Poznań' == 'poznan'."""
    text = text.lower().replace("ł", "l")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def split_words(raw: str | None) -> list[str]:
    """'python, junior ,  remote' -> ['python', 'junior', 'remote']"""
    if not raw:
        return []
    return [w.strip() for w in raw.split(",") if w.strip()]


def _contains(text: str, phrase: str) -> bool:
    """Whole-word match: 'ai' matches 'AI tools' but not 'said' or 'email'.
    Words may start a longer form: 'bot' also matches 'bots'."""
    return re.search(rf"(?<!\w){re.escape(normalize(phrase))}", text) is not None


def matches(item: Item, keywords: list[str], exclude: list[str]) -> bool:
    """True if any keyword is in title/summary (or no keywords) and no excluded word is."""
    text = normalize(f"{item.title} {item.summary}")
    if any(_contains(text, w) for w in exclude):
        return False
    return not keywords or any(_contains(text, w) for w in keywords)


class FeedClient:
    """Small async client with retries. Reuse one instance for the whole app."""

    def __init__(
        self,
        timeout: float = 20.0,
        retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            headers=HEADERS, timeout=timeout, follow_redirects=True, transport=transport
        )
        self._retries = retries

    async def fetch(self, url: str) -> tuple[str, list[Item]]:
        delay = 2.0
        for attempt in range(1, self._retries + 1):
            try:
                resp = await self._client.get(url)
                if 400 <= resp.status_code < 500:  # client errors won't fix themselves
                    raise FeedError(f"The site answered {resp.status_code} for this URL.")
                resp.raise_for_status()
                return parse_feed(resp.content)
            except httpx.HTTPError as exc:
                log.warning("Fetch failed %s (attempt %d/%d): %s", url, attempt, self._retries, exc)
                if attempt == self._retries:
                    raise FeedError(f"Could not download the feed: {exc}") from exc
                await asyncio.sleep(delay)
                delay *= 2
        return "", []

    async def close(self) -> None:
        await self._client.aclose()
