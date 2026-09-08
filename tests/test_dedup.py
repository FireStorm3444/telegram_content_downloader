"""Tests for file deduplication and redundant partial file cleanup."""

from pathlib import Path

from tg_downloader.utils.dedup import (
    find_duplicate_files,
    find_redundant_part_files,
    purge_duplicates,
)


def test_find_and_purge_duplicate_files(tmp_path: Path) -> None:
    """Detect and purge exact duplicate files while preserving originals."""
    # Create original files
    orig1 = tmp_path / "notes (1).pdf"
    orig1.write_bytes(b"HELLO WORLD TEST CONTENT" * 100)

    orig2 = tmp_path / "notes (2).pdf"
    orig2.write_bytes(b"DIFFERENT CONTENT" * 100)

    # Create exact duplicate with higher counter
    dup1 = tmp_path / "notes (9).pdf"
    dup1.write_bytes(b"HELLO WORLD TEST CONTENT" * 100)

    dups = find_duplicate_files(tmp_path)
    assert len(dups) == 1
    assert dups[0][0] == dup1
    assert dups[0][1] == orig1

    # Dry run should not delete
    removed_dry = purge_duplicates(tmp_path, dry_run=True)
    assert dup1 in removed_dry
    assert dup1.exists()

    # Actual purge
    removed = purge_duplicates(tmp_path, dry_run=False)
    assert dup1 in removed
    assert not dup1.exists()
    assert orig1.exists()
    assert orig2.exists()


def test_find_redundant_part_files(tmp_path: Path) -> None:
    """Detect redundant .part and .part.meta when completed file already exists."""
    import json

    # Completed file (1000 bytes)
    comp = tmp_path / "video (1).mp4"
    comp.write_bytes(b"V" * 1000)

    # Redundant .part of the same total_size
    part_file = tmp_path / "video (9).mp4.part"
    part_file.write_bytes(b"V" * 500)
    meta_file = tmp_path / "video (9).mp4.part.meta"
    meta_file.write_text(json.dumps({"total_size": 1000, "file_id": "999"}), encoding="utf-8")

    redundant = find_redundant_part_files(tmp_path)
    assert part_file in redundant
    assert meta_file in redundant

    purge_duplicates(tmp_path, dry_run=False)
    assert not part_file.exists()
    assert not meta_file.exists()
    assert comp.exists()
