"""Tests for formatting utilities."""

import pytest

from tg_downloader.utils.formatting import (
    format_bytes,
    format_duration,
    format_speed,
    parse_size_str,
)


def test_format_bytes() -> None:
    assert format_bytes(0) == "0 B"
    assert format_bytes(512) == "512 B"
    assert format_bytes(1024) == "1.00 KB"
    assert format_bytes(1024 * 1024) == "1.00 MB"
    assert format_bytes(1024 * 1024 * 1024 * 2.5) == "2.50 GB"


def test_format_speed() -> None:
    assert format_speed(1024 * 1024 * 15.5) == "15.50 MB/s"


def test_format_duration() -> None:
    assert format_duration(30) == "00:30"
    assert format_duration(95) == "01:35"
    assert format_duration(3665) == "01:01:05"
    assert format_duration(-1) == "--:--"


def test_parse_size_str() -> None:
    assert parse_size_str(None) is None
    assert parse_size_str("") is None
    assert parse_size_str("500B") == 500
    assert parse_size_str("1KB") == 1024
    assert parse_size_str("10MB") == 10 * 1024 * 1024
    assert parse_size_str("1.5GB") == int(1.5 * 1024 * 1024 * 1024)

    with pytest.raises(ValueError):
        parse_size_str("invalid_size")
