"""Configuration settings for tg-downloader."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables, .env, or CLI flags."""

    model_config = SettingsConfigDict(
        env_prefix="TG_",
        env_file=(".env", str(Path.home() / ".tg_downloader" / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram API Credentials
    api_id: int | None = Field(default=None, description="Telegram API ID from my.telegram.org")
    api_hash: str | None = Field(default=None, description="Telegram API Hash from my.telegram.org")
    phone: str | None = Field(
        default=None, description="Telegram phone number in international format (+1...)"
    )

    # Session & Storage
    session_name: str = Field(default="tg_downloader", description="Session name")
    session_dir: Path = Field(
        default_factory=lambda: Path.home() / ".tg_downloader",
        description="Directory to store session files and credentials",
    )
    download_dir: Path = Field(
        default_factory=lambda: Path("./downloads"),
        description="Target directory for downloaded media files",
    )

    # Performance & Concurrency
    max_connections: int = Field(
        default=4, ge=1, le=16, description="Parallel MTProto sender connections per file download"
    )
    chunk_size: int = Field(
        default=512 * 1024,
        description="Chunk size in bytes (max MTProto chunk is 524288 / 512KB)",
    )
    max_concurrent_files: int = Field(
        default=1, ge=1, le=8, description="Number of files to download concurrently in batch mode"
    )
    flood_sleep_threshold: int = Field(
        default=120, description="Max seconds to automatically sleep on FloodWait before raising"
    )

    @property
    def session_dir_expanded(self) -> Path:
        """Resolved session directory with user home expansion."""
        return self.session_dir.expanduser()

    @property
    def download_dir_expanded(self) -> Path:
        """Resolved download directory with user home expansion."""
        return self.download_dir.expanduser()

    @property
    def session_path(self) -> Path:
        """Full path to SQLite session file with automatic fallback for existing sessions."""
        primary = self.session_dir_expanded / f"{self.session_name}.session"
        if primary.exists():
            return primary

        # Check for literal "~/.tg_downloader" in cwd
        literal = Path(str(self.session_dir)) / f"{self.session_name}.session"
        if literal.exists():
            return literal

        return primary

    def ensure_directories(self) -> None:
        """Ensure necessary storage directories exist."""
        self.session_dir_expanded.mkdir(parents=True, exist_ok=True)
        self.download_dir_expanded.mkdir(parents=True, exist_ok=True)


def get_default_settings() -> Settings:
    """Retrieve settings instance with auto-discovered environment configuration."""
    settings = Settings()
    return settings
