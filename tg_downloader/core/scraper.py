"""Channel and chat scraping engine with customizable filters and forum topic resolution."""

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from telethon import TelegramClient
from telethon.tl import functions, types

from tg_downloader.utils.media import (
    get_media_filename,
    get_media_size,
    get_media_type,
    is_media_match,
)

logger = logging.getLogger(__name__)


@dataclass
class ScrapedMedia:
    """Represents a media item discovered during channel scraping."""

    message: types.Message
    message_id: int
    media_type: str
    file_size: int
    file_name: str
    chat_peer: Any
    date: datetime
    topic_id: int | None = None
    topic_title: str | None = None
    scraped_at: float = field(default_factory=time.time)


@dataclass
class ScrapeFilter:
    """Filter specifications for scraping media from a Telegram channel or chat."""

    limit: int | None = None
    media_types: set[str] | None = None  # None or empty implies all
    extensions: set[str] | None = None  # File extensions without leading dot (e.g. {'pdf', 'mp4'})
    min_id: int | None = None
    max_id: int | None = None
    start_date: datetime | None = None  # Messages on or after this date
    end_date: datetime | None = None  # Messages on or before this date
    min_size: int | None = None  # Bytes
    max_size: int | None = None  # Bytes
    search_query: str | None = None
    reverse: bool = False
    topic_id: int | None = None
    topic_query: str | None = None  # Substring match on topic title


class ChannelScraper:
    """Scrapes messages from channels and chats, filtering for downloadable media."""

    def __init__(self, client: TelegramClient) -> None:
        self.client = client

    async def get_forum_topics(self, entity: Any) -> dict[int, str]:
        """Retrieve forum topics mapping (topic_id -> title) if entity has forum enabled."""
        topics_map: dict[int, str] = {1: "General"}
        if not getattr(entity, "forum", False):
            return topics_map

        try:
            input_peer = await self.client.get_input_entity(entity)
            offset_date = None
            offset_id = 0
            offset_topic = 0

            while True:
                res = await self.client(
                    functions.messages.GetForumTopicsRequest(
                        peer=input_peer,
                        offset_date=offset_date,
                        offset_id=offset_id,
                        offset_topic=offset_topic,
                        limit=100,
                    )
                )
                if not isinstance(res, types.messages.ForumTopics) or not res.topics:
                    break

                for t in res.topics:
                    if isinstance(t, types.ForumTopic):
                        topics_map[t.id] = t.title

                if len(res.topics) < 100:
                    break

                last_t = res.topics[-1]
                if isinstance(last_t, types.ForumTopic):
                    offset_topic = last_t.id
                    offset_date = last_t.date
                    offset_id = last_t.top_message
                else:
                    break

        except Exception as e:
            logger.debug("Failed to retrieve forum topics: %s", e)

        return topics_map

    @staticmethod
    def extract_message_topic_id(message: types.Message) -> int | None:
        """Extract the forum topic ID from a Telegram message."""
        if not message.reply_to:
            return None
        header = message.reply_to
        if isinstance(header, types.MessageReplyHeader):
            if header.forum_topic:
                return header.reply_to_top_id or header.reply_to_msg_id
            elif header.reply_to_top_id:
                return header.reply_to_top_id
        return None

    async def scrape(
        self,
        entity: Any,
        scrape_filter: ScrapeFilter | None = None,
        chat_prefix: str = "",
    ) -> AsyncIterator[ScrapedMedia]:
        """Iterate through messages from an entity and yield filtered media items."""
        flt = scrape_filter or ScrapeFilter()
        count = 0

        # Retrieve topics if this is a forum supergroup
        is_forum = bool(getattr(entity, "forum", False))
        topics_map = await self.get_forum_topics(entity) if is_forum else {}

        # Setup Telethon iter_messages kwargs
        kwargs: dict[str, Any] = {}
        if flt.min_id is not None:
            kwargs["min_id"] = flt.min_id
        if flt.max_id is not None:
            kwargs["max_id"] = flt.max_id
        if flt.search_query:
            kwargs["search"] = flt.search_query
        if flt.reverse:
            kwargs["reverse"] = True
        # If filtering specifically by a known topic ID on Telegram level
        if flt.topic_id is not None:
            kwargs["reply_to"] = flt.topic_id

        async for message in self.client.iter_messages(entity, **kwargs):
            if not isinstance(message, types.Message):
                continue

            # Check if message has media and satisfies media type / extension filters
            if not is_media_match(message, media_types=flt.media_types, extensions=flt.extensions):
                continue

            # Classify media
            m_type = get_media_type(message)
            if not m_type:
                continue

            # Check topic resolution
            msg_topic_id = self.extract_message_topic_id(message)
            if is_forum and msg_topic_id is None:
                msg_topic_id = 1  # Default to General topic for forum supergroups

            topic_title: str | None = None
            if msg_topic_id is not None and is_forum:
                topic_title = topics_map.get(msg_topic_id, f"Topic_{msg_topic_id}")

            # Topic ID filter
            if flt.topic_id is not None and msg_topic_id != flt.topic_id:
                continue

            # Topic name query filter
            if flt.topic_query:
                clean_query = flt.topic_query.lower().strip()
                if not topic_title or clean_query not in topic_title.lower():
                    continue

            # Check date range
            msg_date = message.date
            if flt.start_date and msg_date < flt.start_date:
                if flt.reverse:
                    continue
                else:
                    break

            if flt.end_date and msg_date > flt.end_date:
                if flt.reverse:
                    break
                else:
                    continue

            # Check size
            size = get_media_size(message)
            if flt.min_size is not None and size < flt.min_size:
                continue
            if flt.max_size is not None and size > flt.max_size:
                continue

            filename = get_media_filename(message, chat_prefix=chat_prefix)

            yield ScrapedMedia(
                message=message,
                message_id=message.id,
                media_type=m_type,
                file_size=size,
                file_name=filename,
                chat_peer=entity,
                date=msg_date,
                topic_id=msg_topic_id,
                topic_title=topic_title,
            )

            count += 1
            if flt.limit is not None and count >= flt.limit:
                break
