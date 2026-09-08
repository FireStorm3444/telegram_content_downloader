"""Cryptographic hardware acceleration diagnostics and verification."""

import logging
import os
import platform
import time
from typing import Any

logger = logging.getLogger(__name__)


def is_cryptg_available() -> bool:
    """Check if native cryptg acceleration is installed and importable."""
    try:
        import cryptg  # noqa: F401

        return True
    except ImportError:
        return False


def get_active_aes_backend() -> str:
    """Detect which AES backend Telethon is using for MTProto."""
    try:
        import telethon.crypto.aes as aes_mod

        if hasattr(aes_mod, "cryptg") and aes_mod.cryptg is not None:
            return "cryptg (Native C Acceleration)"
        elif hasattr(aes_mod, "libssl") and getattr(aes_mod.libssl, "encrypt_ige", None):
            return "libssl (OpenSSL C Acceleration)"
        else:
            return "pyaes (Pure Python - Slow)"
    except Exception as e:
        logger.debug("Failed to inspect telethon.crypto.aes: %s", e)
        return "Unknown"


def benchmark_aes_ige(size_mb: int = 1) -> float:
    """Benchmark AES-IGE throughput in MB/s using Telethon's active AES backend."""
    from telethon.crypto.aes import AES

    data_len = size_mb * 1024 * 1024
    key = os.urandom(32)
    iv = os.urandom(32)
    data = os.urandom(data_len)

    t0 = time.perf_counter()
    encrypted = AES.encrypt_ige(data, key, iv)
    decrypted = AES.decrypt_ige(encrypted, key, iv)
    t1 = time.perf_counter()

    if decrypted != data:
        raise RuntimeError("AES-IGE integrity validation failed during benchmark")

    elapsed = t1 - t0
    if elapsed <= 0:
        return float("inf")
    # Total processed bytes = encrypt + decrypt = 2 * size_mb
    throughput_mb_s = (2.0 * size_mb) / elapsed
    return throughput_mb_s


def get_crypto_diagnostics() -> dict[str, Any]:
    """Gather complete hardware and cryptographic acceleration diagnostics."""
    cryptg_ok = is_cryptg_available()
    active_backend = get_active_aes_backend()

    benchmark_speed = 0.0
    try:
        benchmark_speed = benchmark_aes_ige(size_mb=1)
    except Exception as e:
        logger.debug("AES benchmark failed: %s", e)

    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "cryptg_installed": cryptg_ok,
        "active_backend": active_backend,
        "hardware_accelerated": "Native" in active_backend or "OpenSSL" in active_backend,
        "benchmark_speed_mb_s": benchmark_speed,
    }
