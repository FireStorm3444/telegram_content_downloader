"""Universal Telegram target and link resolution.

Supports:
- Public post links: https://t.me/channel/123
- Private channel links: https://t.me/c/1234567890/456 (with -100 supergroup mapping)
- Topic / thread links: https://t.me/channel/10/456 or https://t.me/c/1234567890/10/456
- Message ranges: https://t.me/channel/100-110
- Channel usernames, IDs, and invite links
"""

import logging
import re
from dataclasses import dataclass
from typing import Any

from telethon import TelegramClient, errors, utils
from telethon.tl import types

from tg_downloader.core.errors import EntityResolutionError, TargetNotFoundError

logger = logging.getLogger(__name__)

# Regular expressions for link parsing
PUBLIC_LINK_PATTERN = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?P<peer>[a-zA-Z0-9_]+)/(?P<msg_id>\d+)(?:-(?P<end_msg_id>\d+))?(?:\?.*)?$"
)
TOPIC_PUBLIC_LINK_PATTERN = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?P<peer>[a-zA-Z0-9_]+)/(?P<topic_id>\d+)/(?P<msg_id>\d+)(?:-(?P<end_msg_id>\d+))?(?:\?.*)?$"
)
PRIVATE_C_BASE_PATTERN = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/c/(?P<channel_id>\d+)/?$"
)
PRIVATE_C_LINK_PATTERN = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/c/(?P<channel_id>\d+)/(?P<msg_id>\d+)(?:-(?P<end_msg_id>\d+))?(?:\?.*)?$"
)
TOPIC_PRIVATE_C_LINK_PATTERN = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/c/(?P<channel_id>\d+)/(?P<topic_id>\d+)/(?P<msg_id>\d+)(?:-(?P<end_msg_id>\d+))?(?:\?.*)?$"
)
CHANNEL_URL_PATTERN = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?P<peer>[a-zA-Z0-9_]+)/?$"
)
INVITE_LINK_PATTERN = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?:\+|joinchat/)(?P<hash>[a-zA-Z0-9_\-]+)/?$"
)


@dataclass
class ParsedTarget:
    """Represents a parsed Telegram target specification."""

    raw_input: str
    peer_reference: Any  # str (username), int (-100... or user ID), or invite hash
    is_post_link: bool
    is_private_c: bool
    message_ids: list[int]
    topic_id: int | None = None
    candidate_topic_id: int | None = None
    is_invite_link: bool = False


@dataclass
class ResolvedTarget:
    """Represents a fully resolved Telegram entity ready for downloading or scraping."""

    entity: Any
    peer_id: int
    title: str
    username: str | None
    is_post_link: bool
    message_ids: list[int]
    topic_id: int | None = None
    is_forum: bool = False


class TargetResolver:
    """Parses and resolves Telegram URLs, peer IDs, and usernames via MTProto."""

    @staticmethod
    def parse_target_string(target: str) -> ParsedTarget:
        """Parse raw user input into a ParsedTarget structure."""
        cleaned = target.strip()

        # 1. Private /c/ link with topic: t.me/c/<channel_id>/<topic_id>/<msg_id>
        topic_priv_match = TOPIC_PRIVATE_C_LINK_PATTERN.match(cleaned)
        if topic_priv_match:
            raw_cid = topic_priv_match.group("channel_id")
            supergroup_id = int(f"-100{raw_cid}")
            topic_id = int(topic_priv_match.group("topic_id"))
            start_id = int(topic_priv_match.group("msg_id"))
            end_id_str = topic_priv_match.group("end_msg_id")
            end_id = int(end_id_str) if end_id_str else start_id
            msg_ids = list(range(min(start_id, end_id), max(start_id, end_id) + 1))
            return ParsedTarget(
                raw_input=cleaned,
                peer_reference=supergroup_id,
                is_post_link=True,
                is_private_c=True,
                message_ids=msg_ids,
                topic_id=topic_id,
            )

        # 2. Private /c/ base channel/group: t.me/c/<channel_id>
        base_priv_match = PRIVATE_C_BASE_PATTERN.match(cleaned)
        if base_priv_match:
            raw_cid = base_priv_match.group("channel_id")
            supergroup_id = int(f"-100{raw_cid}")
            return ParsedTarget(
                raw_input=cleaned,
                peer_reference=supergroup_id,
                is_post_link=False,
                is_private_c=True,
                message_ids=[],
            )

        # 3. Standard Private /c/ link: t.me/c/<channel_id>/<msg_id>
        priv_match = PRIVATE_C_LINK_PATTERN.match(cleaned)
        if priv_match:
            raw_cid = priv_match.group("channel_id")
            # Apply Telegram's internal -100 supergroup ID mapping
            supergroup_id = int(f"-100{raw_cid}")
            start_id = int(priv_match.group("msg_id"))
            end_id_str = priv_match.group("end_msg_id")
            end_id = int(end_id_str) if end_id_str else start_id
            msg_ids = list(range(min(start_id, end_id), max(start_id, end_id) + 1))
            return ParsedTarget(
                raw_input=cleaned,
                peer_reference=supergroup_id,
                is_post_link=True,
                is_private_c=True,
                message_ids=msg_ids,
                candidate_topic_id=start_id if not end_id_str else None,
            )

        # 3. Public link with topic: t.me/<peer>/<topic_id>/<msg_id>
        topic_pub_match = TOPIC_PUBLIC_LINK_PATTERN.match(cleaned)
        if topic_pub_match:
            peer = topic_pub_match.group("peer")
            topic_id = int(topic_pub_match.group("topic_id"))
            start_id = int(topic_pub_match.group("msg_id"))
            end_id_str = topic_pub_match.group("end_msg_id")
            end_id = int(end_id_str) if end_id_str else start_id
            msg_ids = list(range(min(start_id, end_id), max(start_id, end_id) + 1))
            return ParsedTarget(
                raw_input=cleaned,
                peer_reference=peer,
                is_post_link=True,
                is_private_c=False,
                message_ids=msg_ids,
                topic_id=topic_id,
            )

        # 4. Standard Public link: t.me/<peer>/<msg_id>
        pub_match = PUBLIC_LINK_PATTERN.match(cleaned)
        if pub_match:
            peer = pub_match.group("peer")
            start_id = int(pub_match.group("msg_id"))
            end_id_str = pub_match.group("end_msg_id")
            end_id = int(end_id_str) if end_id_str else start_id
            msg_ids = list(range(min(start_id, end_id), max(start_id, end_id) + 1))
            return ParsedTarget(
                raw_input=cleaned,
                peer_reference=peer,
                is_post_link=True,
                is_private_c=False,
                message_ids=msg_ids,
            )

        # 5. Invite link: t.me/+hash or t.me/joinchat/hash
        invite_match = INVITE_LINK_PATTERN.match(cleaned)
        if invite_match:
            return ParsedTarget(
                raw_input=cleaned,
                peer_reference=cleaned,
                is_post_link=False,
                is_private_c=False,
                message_ids=[],
                is_invite_link=True,
            )

        # 6. Channel URL: t.me/<peer>
        channel_match = CHANNEL_URL_PATTERN.match(cleaned)
        if channel_match:
            peer = channel_match.group("peer")
            return ParsedTarget(
                raw_input=cleaned,
                peer_reference=peer,
                is_post_link=False,
                is_private_c=False,
                message_ids=[],
            )

        # 7. Numeric ID (-100... or standard integer)
        try:
            numeric_id = int(cleaned)
            return ParsedTarget(
                raw_input=cleaned,
                peer_reference=numeric_id,
                is_post_link=False,
                is_private_c=str(numeric_id).startswith("-100"),
                message_ids=[],
            )
        except ValueError:
            pass

        # 8. Username: @username or plain username
        peer = cleaned.lstrip("@")
        return ParsedTarget(
            raw_input=cleaned,
            peer_reference=peer,
            is_post_link=False,
            is_private_c=False,
            message_ids=[],
        )

    @classmethod
    async def resolve(
        cls,
        client: TelegramClient,
        target_str: str,
        message_id_override: list[int] | None = None,
    ) -> ResolvedTarget:
        """Resolve target string against Telegram MTProto to get the verified entity."""
        parsed = cls.parse_target_string(target_str)
        entity = None

        # Attempt entity resolution with cache hydration fallback
        try:
            entity = await client.get_entity(parsed.peer_reference)
        except (ValueError, errors.ChannelPrivateError, errors.ChannelInvalidError) as initial_err:
            logger.debug(
                "Initial entity resolution failed for %s (%s). Attempting dialog cache hydration...",
                parsed.peer_reference,
                initial_err,
            )
            # If entity is not found in session cache, hydrate cache from dialogs
            try:
                await client.get_dialogs(limit=100)
                entity = await client.get_entity(parsed.peer_reference)
            except Exception as hydrate_err:
                if parsed.is_private_c:
                    raise EntityResolutionError(
                        f"Cannot access private channel {parsed.peer_reference}. "
                        "Ensure your authenticated account has joined this channel or group."
                    ) from hydrate_err
                raise TargetNotFoundError(
                    f"Could not resolve target '{target_str}': {hydrate_err}"
                ) from hydrate_err
        except Exception as e:
            raise TargetNotFoundError(f"Failed to resolve target '{target_str}': {e}") from e

        if not entity:
            raise TargetNotFoundError(f"Entity not found for target '{target_str}'")

        # Extract title and username
        title = "Unknown"
        username = None
        peer_id = utils.get_peer_id(entity)

        if isinstance(entity, types.Channel | types.Chat):
            title = entity.title or f"Chat_{peer_id}"
            username = getattr(entity, "username", None)
        elif isinstance(entity, types.User):
            first = entity.first_name or ""
            last = entity.last_name or ""
            title = f"{first} {last}".strip() or f"User_{peer_id}"
            username = entity.username

        msg_ids = message_id_override or parsed.message_ids
        is_forum = bool(getattr(entity, "forum", False))
        is_post_link = parsed.is_post_link
        topic_id = parsed.topic_id

        # In forum supergroups, 2-segment URLs (/c/<cid>/<topic_id>) represent topic links
        if is_forum and parsed.candidate_topic_id is not None and not parsed.topic_id:
            topic_id = parsed.candidate_topic_id
            is_post_link = False

        return ResolvedTarget(
            entity=entity,
            peer_id=peer_id,
            title=title,
            username=username,
            is_post_link=is_post_link,
            message_ids=msg_ids,
            topic_id=topic_id,
            is_forum=is_forum,
        )
