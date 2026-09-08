"""TelegramClient factory and lifecycle management."""

import logging
from pathlib import Path

from telethon import TelegramClient

from tg_downloader.config import Settings
from tg_downloader.core.errors import AuthenticationError

logger = logging.getLogger(__name__)


def create_telegram_client(
    settings: Settings,
    session_override: Path | None = None,
) -> TelegramClient:
    """Create and configure a Telethon TelegramClient instance."""
    if not settings.api_id or not settings.api_hash:
        raise AuthenticationError(
            "Telegram API credentials missing. Please provide TG_API_ID and TG_API_HASH "
            "via environment variables, .env, or CLI flags. "
            "Get credentials from https://my.telegram.org/apps"
        )

    settings.ensure_directories()
    session_target = session_override or settings.session_path

    # Telethon takes session path without the .session suffix if passing string path
    session_str = str(session_target)
    if session_str.endswith(".session"):
        session_str = session_str[:-8]

    client = TelegramClient(
        session=session_str,
        api_id=settings.api_id,
        api_hash=settings.api_hash,
        flood_sleep_threshold=settings.flood_sleep_threshold,
        request_retries=5,
        connection_retries=5,
    )

    return client
