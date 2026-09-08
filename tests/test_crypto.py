"""Tests for cryptographic acceleration and diagnostics."""

from tg_downloader.utils.crypto import (
    benchmark_aes_ige,
    get_active_aes_backend,
    get_crypto_diagnostics,
    is_cryptg_available,
)


def test_cryptg_detection() -> None:
    # cryptg was installed in environment
    assert is_cryptg_available() is True


def test_active_aes_backend() -> None:
    backend = get_active_aes_backend()
    assert "cryptg" in backend or "Native" in backend


def test_aes_ige_benchmark() -> None:
    speed_mb_s = benchmark_aes_ige(size_mb=1)
    assert speed_mb_s > 10.0  # Hardware acceleration should yield > 100 MB/s


def test_crypto_diagnostics() -> None:
    diag = get_crypto_diagnostics()
    assert diag["cryptg_installed"] is True
    assert diag["hardware_accelerated"] is True
    assert diag["benchmark_speed_mb_s"] > 0
