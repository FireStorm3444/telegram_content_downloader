"""Tests for DCKeyStorage and cooldown countdown timer."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console
from telethon import errors
from telethon.crypto import AuthKey

from tg_downloader.engine.dc_storage import DCKeyStorage
from tg_downloader.engine.pool import MTProtoSenderPool, wait_for_dc_cooldown


def test_dc_storage_none_or_missing_path(tmp_path: Path) -> None:
    """Loading or saving with None path or non-existent path returns safely."""
    assert DCKeyStorage.load_keys(None, 4) == []
    non_existent = tmp_path / "non_existent.session"
    assert DCKeyStorage.load_keys(non_existent, 4) == []

    # Saving with None path does nothing
    dummy_key = AuthKey(os.urandom(256))
    DCKeyStorage.save_key(None, 4, dummy_key)
    DCKeyStorage.remove_key(None, 4, dummy_key)


def test_dc_storage_save_load_and_deduplicate(tmp_path: Path) -> None:
    """Keys are saved to .dc_keys.json with 256 bytes and deduplicated."""
    session = tmp_path / "test.session"
    session.touch()

    key1 = AuthKey(os.urandom(256))
    key2 = AuthKey(os.urandom(256))

    # Save key1 for DC 4
    DCKeyStorage.save_key(session, 4, key1)
    keys_dc4 = DCKeyStorage.load_keys(session, 4)
    assert len(keys_dc4) == 1
    assert keys_dc4[0].key == key1.key

    # Other DCs have no keys
    assert DCKeyStorage.load_keys(session, 2) == []

    # Saving duplicate key1 does not create duplicate
    DCKeyStorage.save_key(session, 4, key1)
    assert len(DCKeyStorage.load_keys(session, 4)) == 1

    # Save key2 for DC 4
    DCKeyStorage.save_key(session, 4, key2)
    keys_dc4 = DCKeyStorage.load_keys(session, 4)
    assert len(keys_dc4) == 2
    assert {k.key for k in keys_dc4} == {key1.key, key2.key}


def test_dc_storage_remove_key(tmp_path: Path) -> None:
    """Removing a key updates the stored list."""
    session = tmp_path / "test.session"
    session.touch()

    key1 = AuthKey(os.urandom(256))
    key2 = AuthKey(os.urandom(256))
    DCKeyStorage.save_key(session, 4, key1)
    DCKeyStorage.save_key(session, 4, key2)

    assert len(DCKeyStorage.load_keys(session, 4)) == 2

    # Remove key1
    DCKeyStorage.remove_key(session, 4, key1)
    remaining = DCKeyStorage.load_keys(session, 4)
    assert len(remaining) == 1
    assert remaining[0].key == key2.key

    # Remove key2
    DCKeyStorage.remove_key(session, 4, key2)
    assert len(DCKeyStorage.load_keys(session, 4)) == 0


def test_dc_storage_corrupt_data(tmp_path: Path) -> None:
    """Corrupted or invalid length keys are ignored gracefully."""
    session = tmp_path / "test.session"
    storage_path = DCKeyStorage.get_storage_path(session)
    storage_path.write_text('{"4": ["not-valid-base64!@#$", "YWJj"]}', encoding="utf-8")

    loaded = DCKeyStorage.load_keys(session, 4)
    assert loaded == []


@pytest.mark.asyncio
async def test_wait_for_dc_cooldown() -> None:
    """Cooldown countdown finishes accurately with mock time."""
    console = Console(record=True)
    current_time = 1000.0

    def mock_time() -> float:
        return current_time

    async def mock_sleep(seconds: float) -> None:
        nonlocal current_time
        current_time += seconds

    with patch("time.time", side_effect=mock_time), patch("asyncio.sleep", side_effect=mock_sleep):
        await wait_for_dc_cooldown(wait_seconds=3, dc_id=4, console=console)

    output = console.export_text()
    assert "Telegram rate limit active on DC 4" in output
    assert "Cooldown for DC 4 completed!" in output


@pytest.mark.asyncio
async def test_pool_connect_with_saved_key(tmp_path: Path) -> None:
    """Pool successfully utilizes saved key without calling client._borrow_exported_sender."""
    session = tmp_path / "test.session"
    session.touch()
    saved_key = AuthKey(os.urandom(256))
    DCKeyStorage.save_key(session, 4, saved_key)

    mock_client = MagicMock()
    mock_client.session.dc_id = 2
    mock_client._log = MagicMock()
    mock_client._proxy = None
    mock_client._local_addr = None
    mock_dc = MagicMock()
    mock_dc.ip_address = "149.154.167.91"
    mock_dc.port = 443
    mock_dc.id = 4
    mock_client._get_dc = AsyncMock(return_value=mock_dc)
    mock_client._borrow_exported_sender = AsyncMock()

    pool = MTProtoSenderPool(
        client=mock_client,
        dc_id=4,
        max_connections=1,
        session_path=session,
    )

    with patch("tg_downloader.engine.pool.MTProtoSender") as mock_sender_cls:
        mock_sender_instance = MagicMock()
        mock_sender_instance.connect = AsyncMock()
        mock_sender_instance.send = AsyncMock()
        mock_sender_cls.return_value = mock_sender_instance

        await pool.initialize()

        assert len(pool._senders) == 1
        # Primary export was skipped because saved key connected successfully
        mock_client._borrow_exported_sender.assert_not_called()
        mock_sender_instance.connect.assert_awaited_once()

    await pool.close()


@pytest.mark.asyncio
async def test_pool_invalidated_saved_key_removed(tmp_path: Path) -> None:
    """Invalidated saved key is pruned from storage, falling back to export."""
    session = tmp_path / "test.session"
    session.touch()
    invalid_key = AuthKey(os.urandom(256))
    DCKeyStorage.save_key(session, 4, invalid_key)

    mock_client = MagicMock()
    mock_client.session.dc_id = 2
    mock_client._log = MagicMock()
    mock_client._proxy = None
    mock_client._local_addr = None
    mock_dc = MagicMock()
    mock_dc.ip_address = "149.154.167.91"
    mock_dc.port = 443
    mock_dc.id = 4
    mock_client._get_dc = AsyncMock(return_value=mock_dc)

    mock_exported = MagicMock()
    mock_exported.auth_key = AuthKey(os.urandom(256))
    mock_exported.is_connected.return_value = True
    mock_exported.disconnect = AsyncMock()
    mock_client._borrow_exported_sender = AsyncMock(return_value=mock_exported)

    pool = MTProtoSenderPool(
        client=mock_client,
        dc_id=4,
        max_connections=1,
        session_path=session,
    )

    with patch("tg_downloader.engine.pool.MTProtoSender") as mock_sender_cls:
        mock_sender_instance = MagicMock()
        mock_sender_instance.connect = AsyncMock()
        # Sender raises AuthKeyUnregisteredError when testing connection
        mock_sender_instance.send = AsyncMock(
            side_effect=errors.AuthKeyUnregisteredError(request=None)
        )
        mock_sender_cls.return_value = mock_sender_instance

        await pool.initialize()

        # Invalid key should be removed from disk
        saved = DCKeyStorage.load_keys(session, 4)
        # And the new exported key should be saved
        assert len(saved) == 1
        assert saved[0].key == mock_exported.auth_key.key
        mock_client._borrow_exported_sender.assert_awaited_once()

    await pool.close()
