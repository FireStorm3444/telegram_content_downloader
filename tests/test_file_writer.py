"""Tests for AsyncFileWriter and out-of-order zero-copy disk streaming."""

from pathlib import Path

import pytest

from tg_downloader.core.errors import DownloadError
from tg_downloader.engine.file_writer import AsyncFileWriter


@pytest.mark.asyncio
async def test_async_file_writer_out_of_order(tmp_path: Path) -> None:
    target_file = tmp_path / "stream_test.bin"
    chunk_1 = b"AAAA" * 1024  # 4 KB at offset 4096
    chunk_0 = b"BBBB" * 1024  # 4 KB at offset 0
    total_size = len(chunk_0) + len(chunk_1)

    async with AsyncFileWriter(final_path=target_file, total_size=total_size) as writer:
        # Write chunk 1 before chunk 0 (out of order)
        await writer.write_chunk(offset=4096, data=chunk_1)
        await writer.write_chunk(offset=0, data=chunk_0)
        final_path = await writer.finalize()

    assert final_path.exists()
    assert not target_file.with_suffix(target_file.suffix + ".part").exists()
    assert final_path.stat().st_size == total_size

    # Verify content
    content = final_path.read_bytes()
    assert content[:4096] == chunk_0
    assert content[4096:] == chunk_1


@pytest.mark.asyncio
async def test_async_file_writer_size_mismatch(tmp_path: Path) -> None:
    target_file = tmp_path / "mismatch.bin"
    chunk_0 = b"1234"

    async with AsyncFileWriter(final_path=target_file, total_size=100) as writer:
        await writer.write_chunk(offset=0, data=chunk_0)
        # Expected 100 bytes, but only 4 bytes written without pre-allocation filling
        with pytest.raises(DownloadError):
            # If ftruncate pre-allocated 100 bytes on Linux, actual size is 100.
            # But let's verify error handling if file descriptor is truncated differently.
            part_path = target_file.with_suffix(target_file.suffix + ".part")
            # Force size mismatch by truncating .part to 50 bytes
            import os

            os.truncate(part_path, 50)
            await writer.finalize()
