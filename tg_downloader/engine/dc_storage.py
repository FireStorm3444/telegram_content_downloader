"""Persistent on-disk storage for exported MTProto Data Center authorization keys."""

import base64
import contextlib
import json
import logging
import os
from pathlib import Path

from telethon.crypto import AuthKey

logger = logging.getLogger(__name__)


class DCKeyStorage:
    """Manages secure serialization and loading of foreign DC auth keys to avoid re-exporting."""

    @staticmethod
    def get_storage_path(session_path: Path) -> Path:
        """Derive the key storage path alongside the session file."""
        return session_path.parent / f"{session_path.stem}.dc_keys.json"

    @classmethod
    def load_keys(cls, session_path: Path | None, dc_id: int) -> list[AuthKey]:
        """Load all saved AuthKeys for the specified DC from disk."""
        if session_path is None:
            return []

        path = cls.get_storage_path(session_path)
        if not path.exists():
            return []

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            dc_str = str(dc_id)
            if dc_str not in data or not isinstance(data[dc_str], list):
                return []

            keys: list[AuthKey] = []
            for b64_key in data[dc_str]:
                try:
                    raw = base64.b64decode(b64_key)
                    if len(raw) == 256:
                        keys.append(AuthKey(raw))
                except Exception as e:
                    logger.debug("Failed to decode DC key: %s", e)

            if keys:
                logger.info(
                    "Loaded %d persistent auth key(s) for DC %d from %s",
                    len(keys),
                    dc_id,
                    path.name,
                )
            return keys
        except Exception as e:
            logger.warning("Error reading DC key storage %s: %s", path, e)
            return []

    @classmethod
    def save_key(cls, session_path: Path | None, dc_id: int, auth_key: AuthKey) -> None:
        """Save an AuthKey for the specified DC to disk."""
        if session_path is None or not auth_key or not getattr(auth_key, "key", None):
            return
        if len(auth_key.key) != 256:
            return

        path = cls.get_storage_path(session_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, list[str]] = {}
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        data = loaded
            except Exception:
                data = {}

        dc_str = str(dc_id)
        existing = data.get(dc_str, [])
        b64 = base64.b64encode(auth_key.key).decode("ascii")
        if b64 not in existing:
            existing.append(b64)
            data[dc_str] = existing

            temp_path = path.with_suffix(".tmp")
            try:
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                # Secure file permissions (rw-------)
                os.chmod(temp_path, 0o600)
                os.replace(temp_path, path)
                logger.info("Persisted auth key for DC %d to %s", dc_id, path.name)
            except Exception as e:
                logger.warning("Failed to persist DC key to %s: %s", path, e)
                if temp_path.exists():
                    with contextlib.suppress(OSError):
                        temp_path.unlink()

    @classmethod
    def remove_key(cls, session_path: Path | None, dc_id: int, auth_key: AuthKey) -> None:
        """Remove an invalidated AuthKey for the specified DC from disk."""
        if session_path is None or not auth_key or not getattr(auth_key, "key", None):
            return

        path = cls.get_storage_path(session_path)
        if not path.exists():
            return

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            dc_str = str(dc_id)
            if dc_str in data and isinstance(data[dc_str], list):
                b64 = base64.b64encode(auth_key.key).decode("ascii")
                data[dc_str] = [k for k in data[dc_str] if k != b64]
                temp_path = path.with_suffix(".tmp")
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                os.chmod(temp_path, 0o600)
                os.replace(temp_path, path)
                logger.info("Removed invalidated auth key for DC %d from %s", dc_id, path.name)
        except Exception as e:
            logger.debug("Error removing key from %s: %s", path, e)
