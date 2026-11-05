"""Background loop: checks every active subscription and reports new items.

Independent from Telegram (receives a `notify` callback), so the core logic is
easy to test without a real bot.
"""

from __future__ import annotations

import asyncio
import html
import logging
from typing import Awaitable, Callable, Protocol

from .db import Database, Subscription
from .feeds import FeedError, Item, matches

log = logging.getLogger(__name__)

Notify = Callable[[Subscription, Item], Awaitable[None]]
MAX_PER_CHECK = 10  # protects users from a flood after a long downtime


class FeedSource(Protocol):
    async def fetch(self, url: str) -> tuple[str, list[Item]]: ...


def format_item(sub: Subscription, item: Item) -> str:
    """HTML message for Telegram."""
    lines = [f"🆕 <b>{html.escape(item.title)}</b>"]
    if item.summary:
        lines.append(html.escape(item.summary))
    lines.append(f"📰 {html.escape(sub.title)}")
    if item.link:
        lines.append(f'<a href="{html.escape(item.link, quote=True)}">Open →</a>')
    return "\n".join(lines)


async def remember_current(sub: Subscription, items: list[Item], db: Database) -> None:
    """Mark everything currently in the feed as seen, so only future items are sent."""
    await db.mark_seen(sub.id, [i.key for i in items])


async def check_subscription(
    sub: Subscription, source: FeedSource, db: Database, notify: Notify
) -> int:
    """Check one subscription. Returns how many new items were sent."""
    _, items = await source.fetch(sub.url)
    unseen = await db.filter_unseen(sub.id, [i.key for i in items])
    # Feeds list newest first; send oldest first so the chat reads chronologically.
    fresh = [i for i in reversed(items) if i.key in unseen and matches(i, sub.keywords, sub.exclude)]

    sent = 0
    for item in fresh[-MAX_PER_CHECK:]:
        try:
            await notify(sub, item)
            sent += 1
        except Exception:  # one failed message must not stop the loop
            log.exception("Failed to notify chat %s about %s", sub.chat_id, item.key)

    await db.mark_seen(sub.id, [i.key for i in items])
    log.info(
        "Feed #%s %r: %d items, %d new, %d sent", sub.id, sub.title, len(items), len(unseen), sent
    )
    return sent


async def run_forever(
    source: FeedSource, db: Database, notify: Notify, interval: int, pause_between: float = 1.0
) -> None:
    """Check all active subscriptions every `interval` seconds until cancelled."""
    log.info("Watcher started, interval=%ss", interval)
    while True:
        for sub in await db.active_subscriptions():
            try:
                await check_subscription(sub, source, db, notify)
            except FeedError as exc:
                log.warning("Feed #%s: %s", sub.id, exc)
            except Exception:
                log.exception("Feed #%s failed", sub.id)
            await asyncio.sleep(pause_between)
        await asyncio.sleep(interval)
