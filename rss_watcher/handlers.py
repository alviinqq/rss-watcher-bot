"""Telegram commands and buttons."""

from __future__ import annotations

import html
from dataclasses import dataclass
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .db import Database, Subscription
from .feeds import FeedError, matches, split_words
from .watcher import FeedSource, format_item, remember_current

HELP = (
    "👋 I watch <b>RSS/Atom feeds</b> (news, job boards, blogs, GitHub releases…) "
    "and send you only new posts that match your keywords.\n\n"
    "<b>Add a feed:</b>\n"
    "<code>/add https://hnrss.org/newest</code>\n"
    "<code>/add https://hnrss.org/newest | python, ai</code>  — only with these words\n"
    "<code>/add &lt;url&gt; | python | senior, crypto</code>  — and without these\n\n"
    "<b>Manage:</b>\n"
    "/list — your feeds (pause / delete)\n"
    "/last — 3 newest matching posts right now\n"
    "/help — this message"
)
LAST_COUNT = 3


@dataclass(frozen=True)
class AddRequest:
    url: str
    keywords: list[str]
    exclude: list[str]


class ParseError(ValueError):
    pass


def parse_add_args(args: str | None) -> AddRequest:
    """Parse `url | keyword1, keyword2 | exclude1, exclude2`."""
    if not args or not args.strip():
        raise ParseError("Send a feed link, e.g. /add https://hnrss.org/newest")
    # Only the first line counts: "/add url\n/last" in one message must not leak into keywords.
    first_line = args.strip().splitlines()[0]
    parts = [p.strip() for p in first_line.split("|")]
    if len(parts) > 3:
        raise ParseError("Too many parts. Format: url | keywords | excluded words")
    url = parts[0]
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ParseError("The first part must be a link starting with http:// or https://")
    keywords = split_words(parts[1]) if len(parts) > 1 else []
    exclude = split_words(parts[2]) if len(parts) > 2 else []
    if any(len(w) > 50 for w in keywords + exclude) or len(keywords + exclude) > 20:
        raise ParseError("Too many or too long keywords (max 20 words, 50 characters each).")
    return AddRequest(url, keywords, exclude)


def subs_keyboard(subs: list[Subscription]) -> InlineKeyboardMarkup:
    rows = []
    for s in subs:
        toggle = ("▶️ Resume", f"resume:{s.id}") if not s.active else ("⏸ Pause", f"pause:{s.id}")
        rows.append(
            [
                InlineKeyboardButton(text=f"#{s.id} {toggle[0]}", callback_data=toggle[1]),
                InlineKeyboardButton(text="🗑 Delete", callback_data=f"del:{s.id}"),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subs_text(subs: list[Subscription]) -> str:
    if not subs:
        return "You have no feeds yet. Add one: <code>/add https://hnrss.org/newest</code>"
    lines = ["<b>Your feeds:</b>"]
    lines += [f"#{s.id} — {html.escape(s.describe())}" for s in subs]
    return "\n".join(lines)


async def cmd_help(message: Message) -> None:
    await message.answer(HELP, disable_web_page_preview=True)


async def cmd_add(
    message: Message, command: CommandObject, db: Database, feeds: FeedSource, max_subs: int
) -> None:
    try:
        req = parse_add_args(command.args)
    except ParseError as exc:
        await message.answer(f"⚠️ {html.escape(str(exc))}")
        return
    if await db.count_active(message.chat.id) >= max_subs:
        await message.answer(f"⚠️ Limit reached: max {max_subs} active feeds. Delete one in /list.")
        return
    try:
        title, items = await feeds.fetch(req.url)
    except FeedError as exc:
        await message.answer(f"⚠️ {html.escape(str(exc))}")
        return
    sub = await db.add_subscription(message.chat.id, req.url, title, req.keywords, req.exclude)
    await remember_current(sub, items, db)  # only posts published from now on are sent
    await message.answer(
        f"✅ Watching {html.escape(sub.describe())}\n"
        f"Feed has {len(items)} posts now — I'll send only new ones. /last shows the latest."
    )


async def cmd_list(message: Message, db: Database) -> None:
    subs = await db.list_subscriptions(message.chat.id)
    await message.answer(subs_text(subs), reply_markup=subs_keyboard(subs) if subs else None)


async def cmd_last(message: Message, db: Database, feeds: FeedSource) -> None:
    """Show the newest matching posts for every feed, without waiting for new ones."""
    subs = [s for s in await db.list_subscriptions(message.chat.id) if s.active]
    if not subs:
        await message.answer("You have no active feeds. Add one: <code>/add https://hnrss.org/newest</code>")
        return
    for sub in subs:
        try:
            _, items = await feeds.fetch(sub.url)
        except FeedError as exc:
            await message.answer(f"⚠️ #{sub.id}: {html.escape(str(exc))}")
            continue
        found = [i for i in items if matches(i, sub.keywords, sub.exclude)]
        if not found:
            await message.answer(
                f"#{sub.id} {html.escape(sub.describe())}: {len(items)} posts in the feed, "
                "none match your keywords."
            )
            continue
        await message.answer(f"<b>#{sub.id}</b> {html.escape(sub.describe())} — newest:")
        for item in found[:LAST_COUNT]:
            await message.answer(format_item(sub, item), disable_web_page_preview=True)


async def on_sub_button(callback: CallbackQuery, db: Database) -> None:
    action, raw_id = callback.data.split(":")
    chat_id = callback.message.chat.id
    sub_id = int(raw_id)
    if action == "del":
        ok = await db.delete_subscription(sub_id, chat_id)
        note = "Deleted" if ok else "Not found"
    else:
        ok = await db.set_active(sub_id, chat_id, action == "resume")
        note = ("Resumed" if action == "resume" else "Paused") if ok else "Not found"
    subs = await db.list_subscriptions(chat_id)
    await callback.message.edit_text(
        subs_text(subs), reply_markup=subs_keyboard(subs) if subs else None
    )
    await callback.answer(note)


def build_router() -> Router:
    """Create a fresh router with all handlers (a router can be attached only once)."""
    router = Router()
    router.message.register(cmd_help, CommandStart())
    router.message.register(cmd_help, Command("help"))
    router.message.register(cmd_add, Command("add"))
    router.message.register(cmd_list, Command("list"))
    router.message.register(cmd_last, Command("last"))
    router.callback_query.register(on_sub_button, F.data.regexp(r"^(pause|resume|del):\d+$"))
    return router
