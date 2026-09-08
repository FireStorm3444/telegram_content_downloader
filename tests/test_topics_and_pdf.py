"""Tests for forum topic link resolution, PDF media detection, and topic folder organization."""

from unittest.mock import MagicMock

from telethon.tl import types

from tg_downloader.core.resolver import TargetResolver
from tg_downloader.core.scraper import ChannelScraper
from tg_downloader.utils.media import get_media_type, is_media_match


def test_private_base_channel_link() -> None:
    # Test link to the group itself without message ID
    target = "https://t.me/c/3419616253"
    parsed = TargetResolver.parse_target_string(target)
    assert parsed.is_post_link is False
    assert parsed.is_private_c is True
    assert parsed.peer_reference == -1003419616253
    assert parsed.message_ids == []


def test_pdf_media_type_detection() -> None:
    doc = MagicMock(spec=types.Document)
    doc.mime_type = "application/pdf"
    doc.attributes = []

    media = MagicMock(spec=types.MessageMediaDocument)
    media.document = doc

    msg = MagicMock(spec=types.Message)
    msg.id = 123
    msg.media = media

    assert get_media_type(msg) == "pdf"
    assert is_media_match(msg, media_types={"pdf"}) is True
    assert is_media_match(msg, media_types={"video", "pdf"}) is True
    assert is_media_match(msg, media_types={"video"}) is False
    assert is_media_match(msg, extensions={"pdf"}) is True
    assert is_media_match(msg, extensions={"mp4"}) is False


def test_extract_message_topic_id() -> None:
    header_forum = types.MessageReplyHeader(
        forum_topic=True,
        reply_to_msg_id=3,
        reply_to_top_id=None,
    )
    msg1 = MagicMock(spec=types.Message)
    msg1.reply_to = header_forum
    assert ChannelScraper.extract_message_topic_id(msg1) == 3

    header_reply = types.MessageReplyHeader(
        forum_topic=False,
        reply_to_msg_id=45,
        reply_to_top_id=3,
    )
    msg2 = MagicMock(spec=types.Message)
    msg2.reply_to = header_reply
    assert ChannelScraper.extract_message_topic_id(msg2) == 3

    msg3 = MagicMock(spec=types.Message)
    msg3.reply_to = None
    assert ChannelScraper.extract_message_topic_id(msg3) is None
