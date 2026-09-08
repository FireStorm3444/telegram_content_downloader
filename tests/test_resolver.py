"""Tests for universal Telegram link and target resolution."""

from tg_downloader.core.resolver import TargetResolver


def test_public_post_link() -> None:
    target = "https://t.me/durov/123"
    parsed = TargetResolver.parse_target_string(target)
    assert parsed.is_post_link is True
    assert parsed.is_private_c is False
    assert parsed.peer_reference == "durov"
    assert parsed.message_ids == [123]


def test_public_post_range_link() -> None:
    target = "https://t.me/durov/100-105"
    parsed = TargetResolver.parse_target_string(target)
    assert parsed.is_post_link is True
    assert parsed.peer_reference == "durov"
    assert parsed.message_ids == [100, 101, 102, 103, 104, 105]


def test_private_c_link_with_supergroup_mapping() -> None:
    target = "https://t.me/c/1234567890/456"
    parsed = TargetResolver.parse_target_string(target)
    assert parsed.is_post_link is True
    assert parsed.is_private_c is True
    # Verifies internal -100 supergroup ID mapping
    assert parsed.peer_reference == -1001234567890
    assert parsed.message_ids == [456]


def test_private_c_link_with_topic() -> None:
    target = "https://t.me/c/1234567890/10/456"
    parsed = TargetResolver.parse_target_string(target)
    assert parsed.is_post_link is True
    assert parsed.is_private_c is True
    assert parsed.peer_reference == -1001234567890
    assert parsed.topic_id == 10
    assert parsed.message_ids == [456]


def test_channel_username_and_numeric_id() -> None:
    parsed_username = TargetResolver.parse_target_string("@telegram")
    assert parsed_username.is_post_link is False
    assert parsed_username.peer_reference == "telegram"

    parsed_id = TargetResolver.parse_target_string("-1009876543210")
    assert parsed_id.is_post_link is False
    assert parsed_id.peer_reference == -1009876543210
