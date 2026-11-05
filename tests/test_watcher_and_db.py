from pathlib import Path

import pytest

from rss_watcher.db import Database
from rss_watcher.feeds import parse_feed
from rss_watcher.watcher import check_subscription, format_item, remember_current

RSS = (Path(__file__).parent / "fixtures" / "jobs.rss").read_bytes()


class FakeSource:
    """Serves a feed; `items` can be changed between checks to simulate new posts."""

    def __init__(self, content: bytes):
        self.title, self.items = parse_feed(content)

    async def fetch(self, url):
        return self.title, list(self.items)


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


async def test_only_new_posts_are_sent(db):
    source = FakeSource(RSS)
    sub = await db.add_subscription(1, "https://x/feed", source.title, ["python"])
    await remember_current(sub, source.items, db)
    sent = []

    async def notify(s, item):
        sent.append(item.title)

    assert await check_subscription(sub, source, db, notify) == 0  # nothing new yet

    # a new post appears on top of the feed
    new_item = source.items[0].__class__(
        key="job-104", title="Python Bot Developer", link="https://x/104",
        summary="aiogram", published=None, feed_title=source.title,
    )
    source.items.insert(0, new_item)
    assert await check_subscription(sub, source, db, notify) == 1
    assert sent == ["Python Bot Developer"]
    assert await check_subscription(sub, source, db, notify) == 0  # sent once


async def test_keyword_filter_and_order(db):
    source = FakeSource(RSS)
    sub = await db.add_subscription(1, "https://x/feed", source.title, ["python"], ["senior"])
    sent = []

    async def notify(s, item):
        sent.append(item.key)

    # without remember_current everything is "new": only matching ones, oldest first
    await check_subscription(sub, source, db, notify)
    assert sent == ["job-103"]


async def test_failed_notify_does_not_stop(db):
    source = FakeSource(RSS)
    sub = await db.add_subscription(1, "https://x/feed", source.title)

    async def notify(s, item):
        if item.key == "job-102":
            raise RuntimeError("telegram down")

    assert await check_subscription(sub, source, db, notify) == 2


async def test_crud_and_describe(db):
    sub = await db.add_subscription(7, "https://x/feed", "Jobs", ["python", "bot"], ["senior"])
    assert sub.keywords == ["python", "bot"] and sub.exclude == ["senior"]
    assert "🔑 python, bot" in sub.describe() and "🚫 senior" in sub.describe()
    assert await db.count_active(7) == 1
    assert await db.set_active(sub.id, 7, False) and await db.count_active(7) == 0
    assert not await db.delete_subscription(sub.id, 8)  # someone else's
    assert await db.delete_subscription(sub.id, 7)
    assert await db.list_subscriptions(7) == []


def test_format_item_escapes_html():
    _, items = parse_feed(RSS)
    item = items[0].__class__(
        key="k", title="<script>x</script> & co", link="https://x/?a=1&b=2",
        summary="", published=None, feed_title="F",
    )
    from rss_watcher.db import Subscription
    from datetime import datetime

    sub = Subscription(1, 1, "u", "Jobs", [], [], True, datetime.now())
    text = format_item(sub, item)
    assert "&lt;script&gt;x&lt;/script&gt; &amp; co" in text
    assert 'href="https://x/?a=1&amp;b=2"' in text
