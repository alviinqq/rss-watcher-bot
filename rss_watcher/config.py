"""Configuration loaded from environment variables (.env supported)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    check_interval: int = 120
    max_subs_per_user: int = 5
    db_path: str = "data/rss_watcher.db"


def load_config() -> Config:
    """Read settings from the environment. Raises if BOT_TOKEN is missing."""
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")
    interval = max(60, int(os.getenv("CHECK_INTERVAL", "120")))
    return Config(
        bot_token=token,
        check_interval=interval,
        max_subs_per_user=int(os.getenv("MAX_SUBS_PER_USER", "5")),
        db_path=os.getenv("DB_PATH", "data/rss_watcher.db"),
    )
