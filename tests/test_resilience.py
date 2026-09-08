"""Tests for protocol resilience, FloodWait handling, and FileReferenceExpired."""

from unittest.mock import AsyncMock

import pytest
from telethon import errors

from tg_downloader.core.errors import DownloadError
from tg_downloader.engine.resilience import ResilienceManager


@pytest.mark.asyncio
async def test_resilience_success_first_try() -> None:
    resilience = ResilienceManager()
    mock_func = AsyncMock(return_value=b"data")

    res = await resilience.execute_with_resilience(mock_func)
    assert res == b"data"
    assert mock_func.call_count == 1


@pytest.mark.asyncio
async def test_resilience_transient_retry() -> None:
    resilience = ResilienceManager(max_retries=3)
    mock_func = AsyncMock(side_effect=[ConnectionError("Temporary drop"), b"recovered"])

    res = await resilience.execute_with_resilience(mock_func)
    assert res == b"recovered"
    assert mock_func.call_count == 2


@pytest.mark.asyncio
async def test_resilience_file_reference_expired() -> None:
    resilience = ResilienceManager()
    mock_func = AsyncMock(
        side_effect=[errors.FileReferenceExpiredError(request=None), b"success_data"]
    )
    mock_refresh = AsyncMock()

    res = await resilience.execute_with_resilience(mock_func, refresh_callback=mock_refresh)
    assert res == b"success_data"
    assert mock_func.call_count == 2
    assert mock_refresh.call_count == 1


@pytest.mark.asyncio
async def test_resilience_max_retries_exceeded() -> None:
    resilience = ResilienceManager(max_retries=2)
    mock_func = AsyncMock(side_effect=ConnectionError("Persistent connection failure"))

    with pytest.raises(DownloadError):
        await resilience.execute_with_resilience(mock_func)


@pytest.mark.asyncio
async def test_resilience_concurrent_file_reference_expired_deduplicated() -> None:
    """Concurrent chunk tasks hitting FileReferenceExpired should trigger only one refresh."""
    import asyncio

    resilience = ResilienceManager()
    mock_refresh = AsyncMock()

    # 3 concurrent worker calls
    async def worker_call() -> bytes:
        # First attempt fails with expired reference, second succeeds
        state = {"attempts": 0}

        async def func() -> bytes:
            await asyncio.sleep(0.01)
            state["attempts"] += 1
            if state["attempts"] == 1:
                raise errors.FileReferenceExpiredError(request=None)
            return b"chunk_data"

        return await resilience.execute_with_resilience(func, refresh_callback=mock_refresh)

    results = await asyncio.gather(worker_call(), worker_call(), worker_call())
    assert results == [b"chunk_data", b"chunk_data", b"chunk_data"]
    # Refresh should be called exactly once instead of 3 times
    assert mock_refresh.call_count == 1
