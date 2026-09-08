"""Tests verifying MTProto chunk offset and limit alignment rules."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tg_downloader.engine.parallel import MAX_MTPROTO_CHUNK, MIN_MTPROTO_CHUNK, ParallelDownloader


def test_chunk_size_alignment() -> None:
    # Any custom chunk size must be clamped and aligned to a multiple of 4KB
    mock_client = MagicMock()
    downloader = ParallelDownloader(client=mock_client, chunk_size=500000)
    assert downloader.chunk_size % MIN_MTPROTO_CHUNK == 0
    assert downloader.chunk_size <= MAX_MTPROTO_CHUNK
    assert downloader.chunk_size >= MIN_MTPROTO_CHUNK


def test_chunk_offsets_are_aligned() -> None:
    mock_client = MagicMock()
    downloader = ParallelDownloader(client=mock_client, chunk_size=MAX_MTPROTO_CHUNK)
    # For any chunk index, offset must be divisible by 4096
    for idx in range(100):
        offset = idx * downloader.chunk_size
        assert offset % 4096 == 0
        assert offset % 1024 == 0


@pytest.mark.asyncio
async def test_download_media_already_exists_skips(tmp_path: Path) -> None:
    """Test that download_media returns skipped=True without downloading if file exists with matching size."""
    mock_client = MagicMock()
    downloader = ParallelDownloader(client=mock_client)

    # Pre-create the file on disk
    dest_file = tmp_path / "existing.mp4"
    dest_file.write_bytes(b"x" * 1024)

    mock_msg = MagicMock()
    mock_msg.id = 42
    mock_msg.media = MagicMock()

    with patch("tg_downloader.engine.parallel.utils._get_file_info") as mock_get_info:
        mock_info = MagicMock()
        mock_info.size = 1024  # Matching size
        mock_info.location = MagicMock()
        mock_info.dc_id = 2
        mock_get_info.return_value = mock_info

        res = await downloader.download_media(
            message=mock_msg,
            dest_dir=tmp_path,
            filename_override="existing.mp4",
            overwrite=False,
        )

        assert res.skipped is True
        assert res.path == dest_file
        # Verify no network connections were attempted
        mock_client._borrow_exported_sender.assert_not_called()
        mock_client._create_exported_sender.assert_not_called()


@pytest.mark.asyncio
async def test_download_media_worker_failure_aborts_immediately(tmp_path: Path) -> None:
    """Test that worker failure aborts download_media immediately without deadlocking."""
    from unittest.mock import AsyncMock

    mock_client = MagicMock()
    mock_client.session.dc_id = 2
    downloader = ParallelDownloader(client=mock_client, max_connections=2)

    mock_msg = MagicMock()
    mock_msg.id = 535
    mock_msg.media = MagicMock()

    chunk_size = downloader.chunk_size
    total_size = chunk_size * 4  # 4 chunks

    with (
        patch("tg_downloader.engine.parallel.utils._get_file_info") as mock_get_info,
        patch.object(downloader, "get_pool") as mock_get_pool,
    ):
        mock_info = MagicMock()
        mock_info.size = total_size
        mock_info.location = MagicMock()
        mock_info.location.id = 535
        mock_info.dc_id = 2
        mock_get_info.return_value = mock_info

        mock_pool = MagicMock()
        mock_pool.initialize = AsyncMock()
        mock_sender = MagicMock()

        class MockAcquireContext:
            async def __aenter__(self) -> MagicMock:
                return mock_sender

            async def __aexit__(self, *args: object) -> None:
                pass

        mock_pool.acquire.return_value = MockAcquireContext()
        mock_get_pool.return_value = mock_pool

        # Calling client._call fails with ServerError
        mock_client._call = AsyncMock(side_effect=RuntimeError("RPCError -500: No workers running"))

        with pytest.raises(RuntimeError) as exc_info:
            await downloader.download_media(
                message=mock_msg,
                dest_dir=tmp_path,
                filename_override="failed_video.mp4",
                overwrite=False,
            )

        assert "No workers running" in str(exc_info.value)
