"""Tests for download resumption state tracking and serialization."""

from pathlib import Path

from tg_downloader.engine.state import DownloadState


def test_download_state_initialization(tmp_path: Path) -> None:
    part_path = tmp_path / "video.mp4.part"
    total_size = 1024 * 1024 * 5  # 5 MB
    chunk_size = 512 * 1024  # 512 KB

    state = DownloadState.load_or_create(
        part_path=part_path,
        total_size=total_size,
        chunk_size=chunk_size,
        file_id="12345",
    )

    assert state.total_chunks == 10
    assert len(state.get_pending_chunk_indices()) == 10
    assert not state.is_complete


def test_download_state_persistence_and_resumption(tmp_path: Path) -> None:
    part_path = tmp_path / "video.mp4.part"
    part_path.write_bytes(b"\x00" * 1024)
    total_size = 1024 * 1024 * 2  # 2 MB
    chunk_size = 512 * 1024  # 512 KB (4 chunks total)

    state = DownloadState.load_or_create(
        part_path=part_path,
        total_size=total_size,
        chunk_size=chunk_size,
        file_id="media_99",
    )

    state.mark_chunk_complete(0)
    state.mark_chunk_complete(2)
    state.save()

    # Load from disk
    resumed = DownloadState.load_or_create(
        part_path=part_path,
        total_size=total_size,
        chunk_size=chunk_size,
        file_id="media_99",
    )

    assert resumed.completed_chunks == {0, 2}
    assert resumed.get_pending_chunk_indices() == [1, 3]

    resumed.mark_chunk_complete(1)
    resumed.mark_chunk_complete(3)
    assert resumed.is_complete

    resumed.cleanup()
    meta_path = part_path.with_suffix(part_path.suffix + ".meta")
    assert not meta_path.exists()
