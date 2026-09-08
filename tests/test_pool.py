"""Tests for MTProtoSenderPool and ParallelDownloader persistent pooling."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telethon import errors

from tg_downloader.core.errors import RateLimitError
from tg_downloader.engine.parallel import ParallelDownloader
from tg_downloader.engine.pool import MTProtoSenderPool


@pytest.mark.asyncio
async def test_pool_home_dc() -> None:
    """Test MTProtoSenderPool when target DC is the client's home DC."""
    mock_client = MagicMock()
    mock_client.session.dc_id = 2
    mock_sender = MagicMock()
    mock_client._sender = mock_sender

    pool = MTProtoSenderPool(client=mock_client, dc_id=2, max_connections=4)
    assert pool._is_home_dc is True

    await pool.initialize()
    assert pool._initialized is True

    # Acquiring should yield the primary client sender
    async with pool.acquire() as sender:
        assert sender is mock_sender

    await pool.close()
    assert pool._initialized is False


@pytest.mark.asyncio
async def test_pool_foreign_dc_success() -> None:
    """Test MTProtoSenderPool when target DC is a foreign DC with multiple connections."""
    mock_client = MagicMock()
    mock_client.session.dc_id = 2

    mock_primary = MagicMock()
    mock_primary.is_connected.return_value = True
    mock_primary.disconnect = AsyncMock()

    mock_extra = MagicMock()
    mock_extra.is_connected.return_value = True
    mock_extra.disconnect = AsyncMock()

    mock_client._borrow_exported_sender = AsyncMock(return_value=mock_primary)
    mock_client._create_exported_sender = AsyncMock(return_value=mock_extra)
    mock_client._return_exported_sender = AsyncMock()

    pool = MTProtoSenderPool(client=mock_client, dc_id=4, max_connections=2)
    assert pool._is_home_dc is False

    await pool.initialize()
    assert pool._initialized is True
    assert len(pool._senders) == 2
    assert pool._sender_queue.qsize() == 2

    # Acquire and release
    async with pool.acquire() as s1:
        assert s1 in (mock_primary, mock_extra)

    await pool.close()
    assert pool._initialized is False
    assert len(pool._senders) == 0


@pytest.mark.asyncio
async def test_pool_foreign_dc_flood_wait_on_extra_connection() -> None:
    """Test that FloodWait on an extra connection does not abort if primary is available."""
    mock_client = MagicMock()
    mock_client.session.dc_id = 2

    mock_primary = MagicMock()
    mock_primary.is_connected.return_value = True
    mock_primary.disconnect = AsyncMock()

    mock_client._borrow_exported_sender = AsyncMock(return_value=mock_primary)
    # Extra connection hits FloodWait
    mock_client._create_exported_sender = AsyncMock(
        side_effect=errors.FloodWaitError(request=None, capture=10)
    )

    pool = MTProtoSenderPool(client=mock_client, dc_id=4, max_connections=4)
    await pool.initialize()

    # Should have 1 sender, but queue populated with 4 concurrency slots
    assert len(pool._senders) == 1
    assert pool._sender_queue.qsize() == 4

    async with pool.acquire() as s:
        assert s is mock_primary

    await pool.close()


@pytest.mark.asyncio
async def test_pool_foreign_dc_primary_flood_wait_no_home_dc_fallback() -> None:
    """Test that FloodWait on primary export raises RateLimitError and NEVER falls back to home DC."""
    mock_client = MagicMock()
    mock_client.session.dc_id = 2

    # Primary export hits FloodWait of 2713 seconds
    mock_client._borrow_exported_sender = AsyncMock(
        side_effect=errors.FloodWaitError(request=None, capture=2713)
    )

    pool = MTProtoSenderPool(client=mock_client, dc_id=4, max_connections=4, auto_wait=False)
    with pytest.raises(RateLimitError) as exc_info:
        await pool.initialize()

    assert "2713" in str(exc_info.value)
    # Crucial assertion: pool must NEVER pretend to be home DC
    assert pool._is_home_dc is False
    assert pool._flood_until > time.time()

    # Second call while flood wait active should immediately raise RateLimitError without calling client
    mock_client._borrow_exported_sender.reset_mock()
    with pytest.raises(RateLimitError) as exc_info2:
        await pool.initialize()

    assert "remaining" in str(exc_info2.value)
    mock_client._borrow_exported_sender.assert_not_called()


@pytest.mark.asyncio
async def test_pool_foreign_dc_primary_flood_wait_auto_wait() -> None:
    """Test that FloodWait on primary export automatically triggers countdown when auto_wait=True."""
    mock_client = MagicMock()
    mock_client.session.dc_id = 2

    mock_sender = MagicMock()
    mock_sender.is_connected.return_value = True

    # First call raises FloodWait(5), second call succeeds
    mock_client._borrow_exported_sender = AsyncMock(
        side_effect=[errors.FloodWaitError(request=None, capture=5), mock_sender]
    )
    mock_client._create_exported_sender = AsyncMock(
        side_effect=errors.FloodWaitError(request=None, capture=5)
    )

    with patch(
        "tg_downloader.engine.pool.wait_for_dc_cooldown", new_callable=AsyncMock
    ) as mock_wait:
        pool = MTProtoSenderPool(
            client=mock_client, dc_id=4, max_connections=1, auto_wait=True, max_flood_sleep=10
        )
        await pool.initialize()
        mock_wait.assert_awaited_once_with(5, 4, console=pool.console)
        assert len(pool._senders) == 1
        await pool.close()


@pytest.mark.asyncio
async def test_parallel_downloader_persistent_pooling() -> None:
    """Test that ParallelDownloader caches MTProtoSenderPool across calls and cleans up on close."""
    mock_client = MagicMock()
    mock_client.session.dc_id = 2

    downloader = ParallelDownloader(client=mock_client, max_connections=4)

    # Calling get_pool for DC 4 multiple times returns the exact same pool instance
    pool1 = await downloader.get_pool(4)
    pool2 = await downloader.get_pool(4)
    assert pool1 is pool2

    # DC 2 returns a different pool instance
    pool_home = await downloader.get_pool(2)
    assert pool_home is not pool1

    # Closing downloader closes all cached pools
    with (
        patch.object(pool1, "close", new_callable=AsyncMock) as mock_close1,
        patch.object(pool_home, "close", new_callable=AsyncMock) as mock_close2,
    ):
        await downloader.close()
        mock_close1.assert_awaited_once()
        mock_close2.assert_awaited_once()
        assert len(downloader._pools) == 0
