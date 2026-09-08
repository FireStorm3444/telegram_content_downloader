"""Resumption and download state management (.part.meta)."""

import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DownloadState:
    """Tracks completed chunks and verification metadata for partial downloads."""

    def __init__(
        self,
        meta_path: Path,
        total_size: int,
        chunk_size: int,
        file_id: Any,
        completed_chunks: set[int] | None = None,
    ) -> None:
        self.meta_path = meta_path
        self.total_size = total_size
        self.chunk_size = chunk_size
        self.file_id = str(file_id)
        self.completed_chunks: set[int] = completed_chunks or set()

    @property
    def total_chunks(self) -> int:
        """Total number of chunks required for this file."""
        if self.total_size <= 0:
            return 1
        return (self.total_size + self.chunk_size - 1) // self.chunk_size

    @property
    def is_complete(self) -> bool:
        """Check if all chunks have been recorded as completed."""
        return len(self.completed_chunks) >= self.total_chunks

    def mark_chunk_complete(self, chunk_index: int) -> None:
        """Mark a chunk index as successfully written to disk."""
        self.completed_chunks.add(chunk_index)

    def get_pending_chunk_indices(self) -> list[int]:
        """Return list of chunk indices that have not yet been completed."""
        all_indices = range(self.total_chunks)
        return [idx for idx in all_indices if idx not in self.completed_chunks]

    def save(self) -> None:
        """Save state metadata to disk atomically."""
        data = {
            "file_id": self.file_id,
            "total_size": self.total_size,
            "chunk_size": self.chunk_size,
            "completed_chunks": sorted(self.completed_chunks),
        }
        temp_path = self.meta_path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(temp_path, self.meta_path)
        except Exception as e:
            logger.debug("Failed to write metadata file %s: %s", self.meta_path, e)
            if temp_path.exists():
                with contextlib.suppress(OSError):
                    temp_path.unlink()

    @classmethod
    def load_or_create(
        cls,
        part_path: Path,
        total_size: int,
        chunk_size: int,
        file_id: Any,
    ) -> "DownloadState":
        """Load existing state if valid; otherwise create fresh state."""
        meta_path = part_path.with_suffix(part_path.suffix + ".meta")

        if meta_path.exists() and part_path.exists():
            try:
                with open(meta_path, encoding="utf-8") as f:
                    data = json.load(f)

                # Validate consistency
                if (
                    data.get("file_id") == str(file_id)
                    and data.get("total_size") == total_size
                    and data.get("chunk_size") == chunk_size
                ):
                    completed = set(data.get("completed_chunks", []))
                    logger.info(
                        "Resuming download from existing .part state (%d/%d chunks)",
                        len(completed),
                        (total_size + chunk_size - 1) // chunk_size,
                    )
                    return cls(
                        meta_path=meta_path,
                        total_size=total_size,
                        chunk_size=chunk_size,
                        file_id=file_id,
                        completed_chunks=completed,
                    )
            except Exception as e:
                logger.warning("Existing metadata file corrupted, restarting transfer: %s", e)

        return cls(
            meta_path=meta_path,
            total_size=total_size,
            chunk_size=chunk_size,
            file_id=file_id,
        )

    def cleanup(self) -> None:
        """Remove state metadata file upon successful completion."""
        if self.meta_path.exists():
            try:
                self.meta_path.unlink()
            except OSError as e:
                logger.debug("Failed to remove metadata file: %s", e)
