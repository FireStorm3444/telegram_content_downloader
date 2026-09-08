"""Custom exceptions for tg-downloader."""


class TGDownloaderError(Exception):
    """Base exception for all tg-downloader errors."""


class AuthenticationError(TGDownloaderError):
    """Raised when Telegram authentication fails or is required."""


class EntityResolutionError(TGDownloaderError):
    """Raised when an entity, channel, or message cannot be resolved."""


class TargetNotFoundError(EntityResolutionError):
    """Raised when the specified target channel, chat, or post is not found."""


class DownloadError(TGDownloaderError):
    """Raised when a file download encounters an unrecoverable failure."""


class ResumptionError(DownloadError):
    """Raised when resuming a download fails due to corrupted state or file mismatch."""


class RateLimitError(TGDownloaderError):
    """Raised when Telegram FloodWait cannot be resolved within threshold."""


class FileReferenceRefreshError(TGDownloaderError):
    """Raised when a file reference cannot be refreshed from the message."""
