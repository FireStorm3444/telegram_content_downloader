"""High-performance parallel MTProto chunk fetching engine."""

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

from rich.console import Console
from telethon import TelegramClient, utils
from telethon.tl import functions, types

from tg_downloader.core.errors import DownloadError, FileReferenceRefreshError
from tg_downloader.engine.file_writer import AsyncFileWriter
from tg_downloader.engine.pool import MTProtoSenderPool
from tg_downloader.engine.resilience import ResilienceManager
from tg_downloader.engine.state import DownloadState
from tg_downloader.utils.filename import resolve_target_path

logger = logging.getLogger(__name__)

# Standard MTProto chunk constants
MAX_MTPROTO_CHUNK = 512 * 1024  # 512 KB
MIN_MTPROTO_CHUNK = 4 * 1024  # 4 KB


class DownloadResult(NamedTuple):
    """Result of a media download containing destination path and skip status."""

    path: Path
    skipped: bool = False


class ParallelDownloader:
    """High-throughput parallel MTProto downloader streaming directly to disk with zero-copy discipline."""

    def __init__(
        self,
        client: TelegramClient,
        max_connections: int = 4,
        chunk_size: int = MAX_MTPROTO_CHUNK,
        resilience: ResilienceManager | None = None,
        session_path: Path | None = None,
        auto_wait: bool = True,
        console: Console | None = None,
    ) -> None:
        self.client = client
        self.max_connections = max(1, min(max_connections, 16))
        # Ensure chunk_size is valid multiple of 4KB and not exceeding 512KB
        self.chunk_size = min(MAX_MTPROTO_CHUNK, max(MIN_MTPROTO_CHUNK, chunk_size))
        self.chunk_size -= self.chunk_size % MIN_MTPROTO_CHUNK
        self.resilience = resilience or ResilienceManager()
        self.session_path = session_path
        self.auto_wait = auto_wait
        self.console = console
        self._pools: dict[int, MTProtoSenderPool] = {}
        self._pools_lock = asyncio.Lock()

    async def get_pool(self, dc_id: int | None) -> MTProtoSenderPool:
        """Obtain or create a cached persistent MTProtoSenderPool for the target DC."""
        client_dc = getattr(self.client.session, "dc_id", 1) if self.client.session else 1
        target_dc = dc_id or client_dc
        async with self._pools_lock:
            if target_dc not in self._pools:
                self._pools[target_dc] = MTProtoSenderPool(
                    client=self.client,
                    dc_id=target_dc,
                    max_connections=self.max_connections,
                    max_flood_sleep=self.resilience.max_flood_sleep,
                    session_path=self.session_path,
                    auto_wait=self.auto_wait,
                    console=self.console,
                )
            return self._pools[target_dc]

    async def close(self) -> None:
        """Cleanly close and disconnect all pooled MTProto connections across all DCs."""
        async with self._pools_lock:
            for pool in self._pools.values():
                await pool.close()
            self._pools.clear()

    async def download_media(
        self,
        message: types.Message,
        dest_dir: Path,
        filename_override: str | None = None,
        overwrite: bool = False,
        entity: Any = None,
        progress_callback: Callable[[int, int], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
    ) -> DownloadResult:
        """Download media from a Telegram message using parallel chunk fetching."""
        if not message.media:
            raise DownloadError(f"Message {message.id} does not contain any media.")

        file_info = utils._get_file_info(message)
        location = file_info.location
        dc_id = file_info.dc_id
        total_size = file_info.size or 0

        # Obtain unique file identifier for resumption state validation
        file_id = getattr(location, "id", f"msg_{message.id}")

        # Determine target file name and path
        from tg_downloader.utils.media import get_media_filename

        filename = filename_override or get_media_filename(message)
        target_path, is_completed = resolve_target_path(
            dest_dir=dest_dir,
            filename=filename,
            expected_size=total_size,
            file_id=str(file_id),
            overwrite=overwrite,
        )

        # Check if already completed with identical size
        if is_completed:
            logger.info("File %s already exists with matching size. Skipping.", target_path.name)
            if progress_callback:
                progress_callback(total_size, total_size)
            return DownloadResult(path=target_path, skipped=True)

        part_path = target_path.with_suffix(target_path.suffix + ".part")

        # Load or initialize resumption state
        state = DownloadState.load_or_create(
            part_path=part_path,
            total_size=total_size,
            chunk_size=self.chunk_size,
            file_id=file_id,
        )

        # Handle empty files directly
        if total_size <= 0:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.touch()
            if progress_callback:
                progress_callback(0, 0)
            return DownloadResult(path=target_path, skipped=False)

        # Handle small files without multi-chunk parallelization
        if total_size <= self.chunk_size:
            return await self._download_single_chunk(
                message=message,
                location=location,
                dc_id=dc_id,
                total_size=total_size,
                target_path=target_path,
                entity=entity,
                progress_callback=progress_callback,
            )

        # Calculate pending chunks
        pending_chunks = state.get_pending_chunk_indices()
        completed_bytes = len(state.completed_chunks) * self.chunk_size
        if progress_callback:
            progress_callback(min(completed_bytes, total_size), total_size)

        if not pending_chunks:
            logger.info("All chunks already verified on disk; finalizing: %s", target_path.name)
            if part_path.exists():
                part_path.replace(target_path)
            state.cleanup()
            return DownloadResult(path=target_path, skipped=False)

        # Setup persistent connection pool
        pool = await self.get_pool(dc_id)
        await pool.initialize()

        # Shared location reference for dynamic FileReferenceExpired refresh
        current_location = location
        target_peer = entity or message.peer_id

        async def refresh_reference() -> types.TypeInputFileLocation:
            nonlocal current_location
            try:
                result_msg = await self.client.get_messages(target_peer, ids=message.id)
                fresh_msg = result_msg[0] if isinstance(result_msg, list) else result_msg
                if not isinstance(fresh_msg, types.Message) or not fresh_msg.media:
                    raise FileReferenceRefreshError(
                        f"Unable to refresh message {message.id} from peer"
                    )
                fresh_info = utils._get_file_info(fresh_msg)
                current_location = fresh_info.location
                logger.info("File reference refreshed successfully for %s", target_path.name)
                return current_location
            except Exception as e:
                raise FileReferenceRefreshError(
                    f"Failed to refresh file reference for message {message.id}: {e}"
                ) from e

        # Setup AsyncFileWriter for zero-copy out-of-order writes
        file_writer = AsyncFileWriter(final_path=target_path, total_size=total_size)
        await file_writer.open()

        # Queue pending chunks
        chunk_queue: asyncio.Queue[int | None] = asyncio.Queue()
        for idx in pending_chunks:
            await chunk_queue.put(idx)

        # Progress tracking
        downloaded_bytes_lock = asyncio.Lock()
        current_downloaded_bytes = completed_bytes

        async def worker() -> None:
            nonlocal current_downloaded_bytes
            while True:
                chunk_idx = await chunk_queue.get()
                if chunk_idx is None:
                    chunk_queue.task_done()
                    break

                offset = chunk_idx * self.chunk_size
                req_limit = self.chunk_size

                async def fetch_chunk(
                    cur_offset: int = offset, cur_limit: int = req_limit
                ) -> bytes:
                    req = functions.upload.GetFileRequest(
                        location=current_location,
                        offset=cur_offset,
                        limit=cur_limit,
                    )
                    async with pool.acquire() as sender:
                        res = await self.client._call(sender, req)

                    if isinstance(res, types.upload.File):
                        return res.bytes
                    elif isinstance(res, types.upload.FileCdnRedirect):
                        raise DownloadError("CDN redirects are currently unsupported.")
                    else:
                        raise DownloadError(f"Unexpected MTProto upload response: {type(res)}")

                try:
                    chunk_data = await self.resilience.execute_with_resilience(
                        func=fetch_chunk,
                        refresh_callback=refresh_reference,
                        operation_name=f"chunk {chunk_idx} of {target_path.name}",
                    )

                    # Write immediately to disk at byte offset with zero memory accumulation
                    await file_writer.write_chunk(offset, chunk_data)
                    data_len = len(chunk_data)

                    # Release reference to raw data immediately for zero-copy discipline
                    del chunk_data

                    # Update state
                    state.mark_chunk_complete(chunk_idx)

                    # Update progress
                    async with downloaded_bytes_lock:
                        current_downloaded_bytes += data_len
                        prog = min(current_downloaded_bytes, total_size)

                    if progress_callback:
                        progress_callback(prog, total_size)

                    # Periodically flush state
                    if chunk_idx % 10 == 0:
                        state.save()

                except Exception as err:
                    logger.error(
                        "Chunk %d download failed for %s: %s",
                        chunk_idx,
                        target_path.name,
                        err,
                    )
                    raise
                finally:
                    chunk_queue.task_done()

        # Launch parallel worker tasks
        num_workers = min(self.max_connections, len(pending_chunks))
        workers = [asyncio.create_task(worker()) for _ in range(num_workers)]

        async def wait_for_queue() -> None:
            await chunk_queue.join()

        queue_task = asyncio.create_task(wait_for_queue())

        try:
            # Monitor workers and queue completion; abort immediately if any worker crashes
            while not queue_task.done():
                done, _ = await asyncio.wait(
                    [queue_task, *workers],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for w in workers:
                    if w.done() and not w.cancelled():
                        exc = w.exception()
                        if exc:
                            raise exc

            # Signal workers to stop
            for _ in range(num_workers):
                await chunk_queue.put(None)
            await asyncio.gather(*workers)

            # Finalize file atomically
            await file_writer.finalize()
            state.cleanup()
            return DownloadResult(path=target_path, skipped=False)

        except BaseException:
            # Cancel queue task and all workers, and close writer descriptor on failure
            queue_task.cancel()
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            state.save()
            await file_writer.close()
            raise

    async def _download_single_chunk(
        self,
        message: types.Message,
        location: types.TypeInputFileLocation,
        dc_id: int | None,
        total_size: int,
        target_path: Path,
        entity: Any = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> DownloadResult:
        """Download small file (<512KB) in a single direct MTProto request."""
        pool = await self.get_pool(dc_id)
        await pool.initialize()

        current_location = location
        target_peer = entity or message.peer_id

        async def refresh_single_ref() -> types.TypeInputFileLocation:
            nonlocal current_location
            try:
                result_msg = await self.client.get_messages(target_peer, ids=message.id)
                fresh_msg = result_msg[0] if isinstance(result_msg, list) else result_msg
                if not isinstance(fresh_msg, types.Message) or not fresh_msg.media:
                    raise FileReferenceRefreshError(
                        f"Unable to refresh message {message.id} from peer"
                    )
                fresh_info = utils._get_file_info(fresh_msg)
                current_location = fresh_info.location
                return current_location
            except Exception as e:
                raise FileReferenceRefreshError(
                    f"Failed to refresh file reference for message {message.id}: {e}"
                ) from e

        async def fetch() -> bytes:
            req = functions.upload.GetFileRequest(
                location=current_location,
                offset=0,
                limit=MAX_MTPROTO_CHUNK,
            )
            async with pool.acquire() as sender:
                res = await self.client._call(sender, req)
            if isinstance(res, types.upload.File):
                return res.bytes
            raise DownloadError(f"Unexpected upload response for single chunk: {type(res)}")

        data = await self.resilience.execute_with_resilience(
            func=fetch,
            refresh_callback=refresh_single_ref,
            operation_name=f"single-chunk {target_path.name}",
        )

        part_path = target_path.with_suffix(target_path.suffix + ".part")
        part_path.parent.mkdir(parents=True, exist_ok=True)

        def _sync_write() -> None:
            with open(part_path, "wb") as f:
                f.write(data)
            part_path.replace(target_path)

        await asyncio.to_thread(_sync_write)

        if progress_callback:
            progress_callback(len(data), len(data))

        return DownloadResult(path=target_path, skipped=False)
