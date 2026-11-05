"""Entry point: `python -m rss_watcher`."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import load_config
from .db import Database, Subscription
from .feeds import FeedClient, Item
from .handlers import build_router
from .watcher import format_item, run_forever


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is noise
    config = load_config()

    db = Database(config.db_path)
    await db.connect()
    feeds = FeedClient()
    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    async def notify(sub: Subscription, item: Item) -> None:
        await bot.send_message(sub.chat_id, format_item(sub, item), disable_web_page_preview=True)

    dp = Dispatcher()
    dp.include_router(build_router())
    # Injected into handlers as keyword arguments.
    dp["db"] = db
    dp["feeds"] = feeds
    dp["max_subs"] = config.max_subs_per_user

    watcher = asyncio.create_task(run_forever(feeds, db, notify, config.check_interval))
    try:
        await dp.start_polling(bot)
    finally:
        watcher.cancel()
        await feeds.close()
        await db.close()
        await bot.session.close()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
