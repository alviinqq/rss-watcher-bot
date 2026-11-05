"""End-to-end handler tests: real aiogram Dispatcher, fake Telegram API session."""

from datetime import datetime

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from pathlib import Path

from rss_watcher.db import Database
from rss_watcher.feeds import FeedError, parse_feed
from rss_watcher.handlers import build_router


class RecordingSession(BaseSession):
    """Pretends to be Telegram: records every API call instead of sending it."""

    def __init__(self):
        super().__init__()
        self.calls = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            return Message(message_id=1, date=datetime.now(), chat=CHAT, text=method.text)
        return True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    async def close(self):
        pass


CHAT = Chat(id=42, type="private")
USER = User(id=42, is_bot=False, first_name="Test")


def msg_update(text: str, uid: int = 1) -> Update:
    return Update(
        update_id=uid,
        message=Message(message_id=uid, date=datetime.now(), chat=CHAT, from_user=USER, text=text),
    )


def cb_update(data: str, uid: int = 100) -> Update:
    message = Message(message_id=5, date=datetime.now(), chat=CHAT, from_user=USER, text="list")
    return Update(
        update_id=uid,
        callback_query=CallbackQuery(
            id=str(uid), from_user=USER, chat_instance="x", message=message, data=data
        ),
    )


@pytest.fixture
async def env():
    db = Database(":memory:")
    await db.connect()
    session = RecordingSession()
    bot = Bot("123:abc", session=session)
    dp = Dispatcher()
    dp.include_router(build_router())
    dp["db"] = db
    dp["max_subs"] = 2
    dp["feeds"] = FakeFeeds()
    yield bot, dp, db, session
    await db.close()


RSS = (Path(__file__).parent / "fixtures" / "jobs.rss").read_bytes()


class FakeFeeds:
    async def fetch(self, url):
        if "broken" in url:
            raise FeedError("The site answered 404 for this URL.")
        return parse_feed(RSS)


def texts(session):
    return [c.text for c in session.calls if isinstance(c, (SendMessage, EditMessageText))]


async def test_help(env):
    bot, dp, db, session = env
    await dp.feed_update(bot, msg_update("/start"))
    assert "RSS" in texts(session)[-1]


async def test_add_then_last(env):
    bot, dp, db, session = env
    await dp.feed_update(bot, msg_update("/add https://jobs.example.com/feed | python | senior"))
    assert "Watching" in texts(session)[-1] and "3 posts" in texts(session)[-1]
    sub = (await db.list_subscriptions(42))[0]
    assert sub.title == "Remote Jobs Board" and sub.exclude == ["senior"]
    # current posts are remembered -> watcher sends only future ones
    assert await db.filter_unseen(sub.id, ["job-103", "job-102"]) == set()

    await dp.feed_update(bot, msg_update("/last", 2))
    out = texts(session)
    assert "newest" in out[-2] and "Junior Python Developer" in out[-1]


async def test_add_errors_and_limit(env):
    bot, dp, db, session = env
    await dp.feed_update(bot, msg_update("/add not-a-link"))
    assert "http" in texts(session)[-1]
    await dp.feed_update(bot, msg_update("/add https://broken.example.com/rss", 2))
    assert "404" in texts(session)[-1] and await db.list_subscriptions(42) == []
    for i in range(3):
        await dp.feed_update(bot, msg_update(f"/add https://ok{i}.example.com/rss", 10 + i))
    assert "Limit reached" in texts(session)[-1]


async def test_pause_and_delete_buttons(env):
    bot, dp, db, session = env
    sub = await db.add_subscription(42, "https://x/feed", "Jobs")
    await dp.feed_update(bot, cb_update(f"pause:{sub.id}"))
    assert not (await db.get_subscription(sub.id, 42)).active
    assert any(isinstance(c, AnswerCallbackQuery) and c.text == "Paused" for c in session.calls)
    await dp.feed_update(bot, cb_update(f"del:{sub.id}", 101))
    assert await db.list_subscriptions(42) == [] and "no feeds" in texts(session)[-1]
