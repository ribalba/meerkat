from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application configuration, overridable via environment variables or a .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Where the app is reachable from a browser. Used to build login + share links in emails.
    base_url: str = "http://localhost:8000"

    # Secret used to sign session/login tokens. CHANGE THIS in production.
    secret_key: str = "dev-insecure-secret-change-me"

    # Database (PostgreSQL). Override with DATABASE_URL; docker-compose points this
    # at the bundled "db" service.
    database_url: str = "postgresql+psycopg2://meerato:meerato@localhost:5432/meerato"

    # File uploads.
    upload_dir: Path = BASE_DIR / "uploads"
    max_upload_bytes: int = 25 * 1024 * 1024  # 25 MB per file

    # Auth token lifetimes (minutes).
    login_token_ttl_minutes: int = 30
    session_ttl_minutes: int = 60 * 24 * 30  # 30 days

    # SMTP. If smtp_host is empty, emails are printed to the console instead of sent.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    email_from: str = "todo@localhost"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings
