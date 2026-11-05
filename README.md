# 📰 RSS Watcher Bot

A Telegram bot that watches **RSS/Atom feeds** — job boards, news sites, blogs,
GitHub releases, forums — and sends you **only new posts that match your keywords**.

> Stop checking ten sites a day. Subscribe once, filter by keywords, get pinged instantly.

<!-- Demo: add a GIF/screenshot here, e.g. docs/demo.gif -->
![demo](docs/demo.gif)

## Features

- 🔗 **Any RSS or Atom feed** — validated when you add it
- 🔑 **Keyword filter** and 🚫 **exclude words** (whole words, case- and diacritics-insensitive: `poznan` = `Poznań`)
- 🆕 **Only new posts** — everything already in the feed is remembered on subscribe; each post is sent once
- ⚡ `/last` — see the latest matching posts right now
- ⏸ **Manage with buttons** — pause, resume, delete
- 🛡 **Robust** — retries with backoff, no retries on 4xx, a failing feed never stops the others
- 💾 **SQLite**, zero external services
- ✅ **26 tests** — parser (RSS + Atom), filters, database, watcher logic and Telegram handlers, all offline

## Quick start

```bash
git clone https://github.com/<your-username>/rss-watcher-bot.git
cd rss-watcher-bot
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env — then put your @BotFather token in .env
python -m rss_watcher       # Windows: py -m rss_watcher
```

Check a feed without Telegram: `python check_feed.py https://hnrss.org/newest`

## Usage

| Command | What it does |
|---|---|
| `/add https://hnrss.org/newest` | Watch a feed (all new posts) |
| `/add <url> \| python, telegram` | …only posts containing any of these words |
| `/add <url> \| python \| senior, crypto` | …and none of these |
| `/list` | Your feeds with ⏸ / 🗑 buttons |
| `/last` | 3 newest matching posts now |
| `/help` | Help |

Example notification:

```
🆕 Junior Python Developer (Remote, Poland)
We are looking for a junior Python dev. Telegram bots a plus.
📰 Remote Jobs Board
Open →
```

**Where to find feeds:** most blogs and news sites have one (look for the RSS icon or add `/feed`, `/rss`),
GitHub releases (`https://github.com/<owner>/<repo>/releases.atom`), Hacker News (`https://hnrss.org/newest?q=python`),
many job boards.

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | — | Token from [@BotFather](https://t.me/BotFather) (required) |
| `CHECK_INTERVAL` | `120` | Seconds between checks (min 60) |
| `MAX_SUBS_PER_USER` | `5` | Active feeds per user |
| `DB_PATH` | `data/rss_watcher.db` | SQLite file |

## How it works

1. On `/add` the bot downloads the feed, checks it really is RSS/Atom and remembers every post already there.
2. Every `CHECK_INTERVAL` seconds each active feed is downloaded again.
3. Posts never seen before that pass the keyword filters are sent (oldest first, max 10 per check).

## Project structure

```
rss_watcher/
├── main.py       # entry point: bot + background watcher
├── config.py     # .env settings
├── feeds.py      # download + parse RSS/Atom, keyword matching
├── watcher.py    # check loop, dedup, message formatting
├── handlers.py   # Telegram commands and buttons
└── db.py         # SQLite: subscriptions + sent posts
tests/            # pytest, offline (fixtures + fake Telegram session)
check_feed.py     # quick connectivity check
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Deploy

**Docker**

```bash
docker build -t rss-watcher .
docker run -d --env-file .env -v $(pwd)/data:/app/data --restart unless-stopped rss-watcher
```

**systemd** (VPS) — see [`rss-watcher.service`](rss-watcher.service).

## License

MIT © Kyrylo Dubovenko
