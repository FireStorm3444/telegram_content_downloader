"""Tests for filename sanitization and collision safety."""

import json
from pathlib import Path

from tg_downloader.utils.filename import (
    resolve_target_path,
    resolve_unique_path,
    sanitize_filename,
)


def test_sanitize_illegal_characters() -> None:
    raw = 'My:Video?*<Cool>|"File"/Name.mp4'
    sanitized = sanitize_filename(raw)
    assert ":" not in sanitized
    assert "?" not in sanitized
    assert "*" not in sanitized
    assert "<" not in sanitized
    assert ">" not in sanitized
    assert "|" not in sanitized
    assert '"' not in sanitized
    assert "/" not in sanitized
    assert sanitized.endswith(".mp4")


def test_sanitize_windows_reserved() -> None:
    assert sanitize_filename("CON.txt") == "_CON.txt"
    assert sanitize_filename("aux.mp4") == "_aux.mp4"
    assert sanitize_filename("NUL") == "_NUL"


def test_sanitize_length_truncation() -> None:
    long_name = "a" * 250 + ".mkv"
    sanitized = sanitize_filename(long_name, max_length=50)
    assert len(sanitized) <= 50
    assert sanitized.endswith(".mkv")


def test_resolve_unique_path(tmp_path: Path) -> None:
    test_file = tmp_path / "movie.mp4"
    test_file.write_text("dummy")

    resolved_1 = resolve_unique_path(test_file, overwrite=False)
    assert resolved_1 == tmp_path / "movie (1).mp4"

    resolved_1.write_text("dummy 2")
    resolved_2 = resolve_unique_path(test_file, overwrite=False)
    assert resolved_2 == tmp_path / "movie (2).mp4"

    # Overwrite mode returns exact path
    assert resolve_unique_path(test_file, overwrite=True) == test_file


def test_resolve_target_path_matching_variants(tmp_path: Path) -> None:
    """Test that resolve_target_path correctly identifies base and numbered variants."""
    # Scenario: 3 videos all named 'lecture.mp4'
    v1 = tmp_path / "lecture.mp4"
    v1.write_bytes(b"A" * 1000)

    v2 = tmp_path / "lecture (1).mp4"
    v2.write_bytes(b"B" * 2000)

    # v3 is partially downloaded as lecture (2).mp4.part
    v3_part = tmp_path / "lecture (2).mp4.part"
    v3_part.write_bytes(b"C" * 500)
    v3_meta = tmp_path / "lecture (2).mp4.part.meta"
    v3_meta.write_text(json.dumps({"file_id": "doc_999", "total_size": 3000}), encoding="utf-8")

    # 1. Checking v1: matches base path
    path1, completed1 = resolve_target_path(
        tmp_path, "lecture.mp4", expected_size=1000, file_id="doc_111"
    )
    assert path1 == v1
    assert completed1 is True

    # 2. Checking v2: base path size mismatch (1000 != 2000), matches variant (1)
    path2, completed2 = resolve_target_path(
        tmp_path, "lecture.mp4", expected_size=2000, file_id="doc_222"
    )
    assert path2 == v2
    assert completed2 is True

    # 3. Checking v3: matches in-progress variant (2).part via file_id/size
    path3, completed3 = resolve_target_path(
        tmp_path, "lecture.mp4", expected_size=3000, file_id="doc_999"
    )
    assert path3 == tmp_path / "lecture (2).mp4"
    assert completed3 is False

    # 4. Checking a brand new v4 with size 4000: allocates variant (3)
    path4, completed4 = resolve_target_path(
        tmp_path, "lecture.mp4", expected_size=4000, file_id="doc_444"
    )
    assert path4 == tmp_path / "lecture (3).mp4"
    assert completed4 is False
