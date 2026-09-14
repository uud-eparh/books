from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "flibusta"
    postgres_password: str = "flibusta_secret"
    postgres_db: str = "flibusta"

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = True

    # Telegram
    telegram_bot_token: str = ""
    telegram_allowed_users: str = ""

    # Paths
    inpx_path: Path
    torrent_data_path: Path
    temp_download_path: Path = Path("./tmp_downloads")
    temp_download_max_gb: int = 20
    temp_file_ttl_minutes: int = 10

    # Torrent
    torrent_hash: str = ""
    torrent_magnet: str = ""

    # Temp files
    temp_file_ttl_minutes: int = 10

    @field_validator("temp_download_path", mode="after")
    @classmethod
    def ensure_temp_dir(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        return v

    @property
    def database_url_async(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def allowed_users_list(self) -> list[int]:
        if not self.telegram_allowed_users.strip():
            return []
        return [
            int(uid.strip())
            for uid in self.telegram_allowed_users.split(",")
            if uid.strip().isdigit()
        ]


settings = Settings()