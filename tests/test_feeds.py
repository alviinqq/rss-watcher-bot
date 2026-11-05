from pathlib import Path

import httpx
import pytest

from rss_watcher.feeds import FeedClient, FeedError, matches, normalize, parse_feed, split_words

FIX = Path(__file__).parent / "fixtures"
RSS = (FIX / "jobs.rss").read_bytes()
ATOM = (FIX / "releases.atom").read_bytes()


def test_parse_rss():
    title, items = parse_feed(RSS)
    assert title == "Remote Jobs Board"
    assert [i.key for i in items] == ["job-103", "job-102", "https://jobs.example.com/jobs/101"]
    first = items[0]
    assert first.title == "Junior Python Developer (Remote, Poland)"
    assert first.summary == "We are looking for a junior Python dev. Telegram bots a plus."  # HTML stripped
    assert first.published.year == 2026 and first.published.tzinfo is not None


def test_parse_atom():
    title, items = parse_feed(ATOM)
    assert title == "Release notes from aiogram"
    assert items[0].link.endswith("/v3.22.0") and items[0].summary == "New features and fixes"


def test_not_a_feed():
    with pytest.raises(FeedError):
        parse_feed(b"<html><body>Just a page</body></html>")


def test_keywords_and_exclude():
    _, items = parse_feed(RSS)
    junior, senior, support = items
    assert matches(junior, ["python"], [])
    assert matches(senior, ["python"], [])
    assert not matches(senior, ["python"], ["senior", "crypto"])
    assert not matches(support, ["python"], [])
    assert matches(support, [], [])  # no keywords = everything
    assert matches(support, ["poznan"], [])  # diacritics-insensitive


def test_helpers():
    assert split_words(" python, junior ,, remote ") == ["python", "junior", "remote"]
    assert split_words(None) == []
    assert normalize("Łódź Poznań") == "lodz poznan"


async def test_client_fetch_and_errors():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "missing" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, content=RSS)

    client = FeedClient(transport=httpx.MockTransport(handler))
    title, items = await client.fetch("https://jobs.example.com/feed")
    assert title == "Remote Jobs Board" and len(items) == 3
    with pytest.raises(FeedError, match="404"):
        await client.fetch("https://jobs.example.com/missing")
    await client.close()
    assert len(calls) == 2  # 404 is not retried


def test_whole_word_matching():
    from rss_watcher.feeds import Item

    item = Item("k", "He said the email was fine", "", "", None, "F")
    assert not matches(item, ["ai"], [])
    item2 = Item("k2", "New AI tools for Telegram bots", "", "", None, "F")
    assert matches(item2, ["ai"], []) and matches(item2, ["bot"], [])
