"""Protocol resilience handling MTProto FloodWait with backoff/jitter and FileReferenceExpired."""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from telethon import errors
from telethon.tl import types

from tg_downloader.core.errors import DownloadError, RateLimitError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ResilienceManager:
    """Provides automated error mitigation, FloodWait backoff, and file reference refreshing."""

    def __init__(
        self,
        max_retries: int = 5,
        max_flood_sleep: int = 300,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.max_retries = max_retries
        self.max_flood_sleep = max_flood_sleep
        self.status_callback = status_callback
        self._refresh_lock = asyncio.Lock()
        self._refresh_generation = 0

    async def execute_with_resilience(
        self,
        func: Callable[[], Awaitable[T]],
        refresh_callback: Callable[[], Awaitable[types.TypeInputFileLocation]] | None = None,
        operation_name: str = "MTProto operation",
    ) -> T:
        """Execute an asynchronous MTProto operation with automated error mitigation."""
        attempt = 0
        backoff = 1.0

        while attempt < self.max_retries:
            start_generation = self._refresh_generation
            try:
                return await func()

            except (errors.FloodWaitError, errors.FloodPremiumWaitError) as flood_err:
                wait_sec = flood_err.seconds
                if wait_sec > self.max_flood_sleep:
                    raise RateLimitError(
                        f"Telegram FloodWait {wait_sec}s exceeds maximum threshold of {self.max_flood_sleep}s."
                    ) from flood_err

                jitter = random.uniform(1.0, 3.0)
                total_sleep = wait_sec + jitter
                msg = f"FloodWait: sleeping {total_sleep:.1f}s (requested {wait_sec}s + jitter) for {operation_name}..."
                logger.warning(msg)
                if self.status_callback:
                    self.status_callback(msg)

                await asyncio.sleep(total_sleep)
                # Flood wait sleep doesn't count against transient retry budget
                continue

            except errors.FileReferenceExpiredError as exp_err:
                logger.info(
                    "FileReferenceExpired detected for %s; refreshing reference from channel...",
                    operation_name,
                )
                if not refresh_callback:
                    raise DownloadError(
                        f"File reference expired for {operation_name}, and no refresh callback is configured."
                    ) from exp_err

                # Synchronize refresh across concurrent chunk tasks
                async with self._refresh_lock:
                    # If another task has already refreshed while waiting for the lock, skip refresh
                    if self._refresh_generation == start_generation:
                        if self.status_callback:
                            self.status_callback(
                                f"Refreshing expired file reference for {operation_name}..."
                            )
                        await refresh_callback()
                        self._refresh_generation += 1
                    else:
                        logger.debug(
                            "Reference for %s was already refreshed by a concurrent chunk task.",
                            operation_name,
                        )

                # Retry immediately with updated reference
                continue

            except (
                errors.TimedOutError,
                errors.RpcCallFailError,
                errors.RpcMcgetFailError,
                errors.ServerError,
                ConnectionError,
                OSError,
            ) as transient_err:
                attempt += 1
                if attempt >= self.max_retries:
                    raise DownloadError(
                        f"{operation_name} failed after {self.max_retries} attempts: {transient_err}"
                    ) from transient_err

                sleep_time = backoff + random.uniform(0.1, 1.0)
                logger.warning(
                    "Transient error during %s (attempt %d/%d): %s. Retrying in %.1fs...",
                    operation_name,
                    attempt,
                    self.max_retries,
                    transient_err,
                    sleep_time,
                )
                await asyncio.sleep(sleep_time)
                backoff = min(backoff * 2.0, 16.0)

            except Exception as e:
                logger.error("Non-transient error during %s: %s", operation_name, e)
                raise

        raise DownloadError(
            f"{operation_name} exceeded maximum retry attempts ({self.max_retries})"
        )
