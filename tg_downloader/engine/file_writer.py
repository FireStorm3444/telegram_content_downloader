"""Asynchronous direct-to-disk chunk writer supporting out-of-order writes with byte offsets."""

import asyncio
import logging
import os
from pathlib import Path

from tg_downloader.core.errors import DownloadError

logger = logging.getLogger(__name__)


class AsyncFileWriter:
    """Streams downloaded chunks directly to disk using byte offsets (os.pwrite) with zero RAM buffering."""

    def __init__(self, final_path: Path, total_size: int) -> None:
        self.final_path = final_path
        self.part_path = final_path.with_suffix(final_path.suffix + ".part")
        self.total_size = total_size
        self._fd: int | None = None
        self._closed = False

    async def open(self) -> None:
        """Open the .part file descriptor and pre-allocate target size."""
        self.part_path.parent.mkdir(parents=True, exist_ok=True)

        def _sync_open() -> int:
            fd = os.open(self.part_path, os.O_RDWR | os.O_CREAT, 0o644)
            if self.total_size > 0:
                try:
                    os.ftruncate(fd, self.total_size)
                except OSError as e:
                    logger.debug("ftruncate pre-allocation non-fatal notice: %s", e)
            return fd

        self._fd = await asyncio.to_thread(_sync_open)
        self._closed = False

    async def write_chunk(self, offset: int, data: bytes) -> int:
        """Write chunk data to disk at the specified byte offset asynchronously using os.pwrite."""
        if self._fd is None or self._closed:
            raise DownloadError(f"Cannot write to closed file writer: {self.part_path}")

        fd = self._fd

        def _sync_pwrite() -> int:
            return os.pwrite(fd, data, offset)

        written = await asyncio.to_thread(_sync_pwrite)
        return written

    async def finalize(self) -> Path:
        """Flush buffers to disk, close descriptor, validate size, and atomically rename .part to target."""
        if self._fd is None or self._closed:
            raise DownloadError(f"File writer already closed or not opened: {self.part_path}")

        fd = self._fd
        self._closed = True
        self._fd = None

        def _sync_finalize() -> None:
            os.fsync(fd)
            os.close(fd)

        await asyncio.to_thread(_sync_finalize)

        # Validate total file size
        actual_size = self.part_path.stat().st_size
        if self.total_size > 0 and actual_size != self.total_size:
            raise DownloadError(
                f"File size mismatch for {self.final_path.name}: "
                f"expected {self.total_size} bytes, got {actual_size} bytes"
            )

        # Atomic replacement
        def _sync_rename() -> None:
            os.replace(self.part_path, self.final_path)

        await asyncio.to_thread(_sync_rename)
        logger.info("Successfully finalized file atomically: %s", self.final_path)
        return self.final_path

    async def close(self) -> None:
        """Close file descriptor without atomic renaming (e.g. on error or cancellation)."""
        if self._fd is not None and not self._closed:
            fd = self._fd
            self._closed = True
            self._fd = None
            await asyncio.to_thread(os.close, fd)

    async def __aenter__(self) -> "AsyncFileWriter":
        await self.open()
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.close()
