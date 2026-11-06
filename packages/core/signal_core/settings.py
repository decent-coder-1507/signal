"""Process-level settings from environment (.env). Product config lives in config/*.yaml."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIGNAL_", env_file=str(REPO_ROOT / ".env"), extra="ignore")

    mode: Literal["mock", "live"] = "mock"
    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "postgresql+asyncpg://signal:signal@localhost:5442/signal"
    redis_url: str = "redis://localhost:6390/0"
    use_redis_queue: bool = False  # False → in-process inline queue (tests, single-process dev)
    config_dir: Path = REPO_ROOT / "config"
    prompts_dir: Path = REPO_ROOT / "prompts"
    fixtures_dir: Path = REPO_ROOT / "fixtures"
    data_dir: Path = REPO_ROOT / "data"
    secret_key: str = "dev-insecure-change-me"
    timezone: str = "Asia/Kolkata"
    # Claude Runner (ADR-001): local Claude Code CLI, subscription login, no API key.
    claude_bin: str = "claude"
    runner_concurrency: int = 2
    runner_timeout_s: int = 180
    # Embeddings: "mock" (hash) or "fastembed" (local bge-small, 384-d)
    embedding_provider: Literal["mock", "fastembed"] = "mock"
    embedding_dim: int = 384
    # Bootstrap single user (created by `seed` if absent)
    admin_email: str = "srijoy@localhost"
    admin_password: str = Field(default="change-me-now", repr=False)
    cookie_secure: bool = False
    web_origin: str = "http://localhost:3710"
    # Optional adapters (all off unless set)
    telegram_bot_token: str | None = Field(default=None, repr=False)
    telegram_chat_id: str | None = None
    telegram_api_base: str = "https://api.telegram.org"
    smtp_url: str | None = Field(default=None, repr=False)
    email_from: str = "signal@localhost"
    github_token: str | None = Field(default=None, repr=False)
    hashnode_token: str | None = Field(default=None, repr=False)
    reddit_client_id: str | None = Field(default=None, repr=False)
    reddit_client_secret: str | None = Field(default=None, repr=False)
    producthunt_token: str | None = Field(default=None, repr=False)
    x_bearer_token: str | None = Field(default=None, repr=False)
    youtube_api_key: str | None = Field(default=None, repr=False)
    imap_url: str | None = Field(default=None, repr=False)
    backup_s3_url: str | None = Field(default=None, repr=False)
    http_concurrency: int = 6
    http_timeout_s: float = 45.0

    @property
    def is_mock(self) -> bool:
        return self.mode == "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
