"""Quick check without Telegram: `py check_feed.py https://hnrss.org/newest`"""

import asyncio
import sys

from rss_watcher.feeds import FeedClient


async def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://hnrss.org/newest"
    client = FeedClient(retries=1)
    try:
        title, items = await client.fetch(url)
        print(f"OK: «{title}» — {len(items)} posts")
        for item in items[:3]:
            print(f" - {item.title}")
    except Exception as exc:
        print(f"FAILED: {exc}")
    finally:
        await client.close()


asyncio.run(main())
