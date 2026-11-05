"""SQLite storage for subscriptions (feed + keywords) and already-sent items."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from .feeds import split_words

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    url         TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    keywords    TEXT,
    exclude     TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS seen_items (
    subscription_id INTEGER NOT NULL,
    item_key        TEXT    NOT NULL,
    PRIMARY KEY (subscription_id, item_key),
    FOREIGN KEY (subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE
);
"""


@dataclass(frozen=True)
class Subscription:
    id: int
    chat_id: int
    url: str
    title: str
    keywords: list[str]
    exclude: list[str]
    active: bool
    created_at: datetime

    def describe(self) -> str:
        parts = [f"«{self.title}»"]
        if self.keywords:
            parts.append("🔑 " + ", ".join(self.keywords))
        if self.exclude:
            parts.append("🚫 " + ", ".join(self.exclude))
        if not self.active:
            parts.append("⏸ paused")
        return " · ".join(parts)


def _row_to_sub(row: aiosqlite.Row) -> Subscription:
    return Subscription(
        id=row["id"],
        chat_id=row["chat_id"],
        url=row["url"],
        title=row["title"],
        keywords=split_words(row["keywords"]),
        exclude=split_words(row["exclude"]),
        active=bool(row["active"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    async def add_subscription(
        self,
        chat_id: int,
        url: str,
        title: str,
        keywords: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> Subscription:
        cur = await self.conn.execute(
            "INSERT INTO subscriptions (chat_id, url, title, keywords, exclude, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                chat_id,
                url,
                title,
                ", ".join(keywords or []),
                ", ".join(exclude or []),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await self.conn.commit()
        sub = await self.get_subscription(cur.lastrowid, chat_id)
        assert sub is not None
        return sub

    async def get_subscription(self, sub_id: int, chat_id: int) -> Subscription | None:
        cur = await self.conn.execute(
            "SELECT * FROM subscriptions WHERE id = ? AND chat_id = ?", (sub_id, chat_id)
        )
        row = await cur.fetchone()
        return _row_to_sub(row) if row else None

    async def list_subscriptions(self, chat_id: int) -> list[Subscription]:
        cur = await self.conn.execute(
            "SELECT * FROM subscriptions WHERE chat_id = ? ORDER BY id", (chat_id,)
        )
        return [_row_to_sub(r) for r in await cur.fetchall()]

    async def active_subscriptions(self) -> list[Subscription]:
        cur = await self.conn.execute("SELECT * FROM subscriptions WHERE active = 1 ORDER BY id")
        return [_row_to_sub(r) for r in await cur.fetchall()]

    async def count_active(self, chat_id: int) -> int:
        cur = await self.conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE chat_id = ? AND active = 1", (chat_id,)
        )
        (count,) = await cur.fetchone()
        return int(count)

    async def set_active(self, sub_id: int, chat_id: int, active: bool) -> bool:
        cur = await self.conn.execute(
            "UPDATE subscriptions SET active = ? WHERE id = ? AND chat_id = ?",
            (int(active), sub_id, chat_id),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def delete_subscription(self, sub_id: int, chat_id: int) -> bool:
        cur = await self.conn.execute(
            "DELETE FROM subscriptions WHERE id = ? AND chat_id = ?", (sub_id, chat_id)
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def filter_unseen(self, sub_id: int, keys: list[str]) -> set[str]:
        """Return the subset of `keys` never recorded for this subscription."""
        if not keys:
            return set()
        placeholders = ",".join("?" * len(keys))
        cur = await self.conn.execute(
            f"SELECT item_key FROM seen_items WHERE subscription_id = ? "
            f"AND item_key IN ({placeholders})",
            (sub_id, *keys),
        )
        seen = {row["item_key"] for row in await cur.fetchall()}
        return set(keys) - seen

    async def mark_seen(self, sub_id: int, keys: list[str]) -> None:
        await self.conn.executemany(
            "INSERT OR IGNORE INTO seen_items (subscription_id, item_key) VALUES (?, ?)",
            [(sub_id, k) for k in keys],
        )
        await self.conn.commit()
