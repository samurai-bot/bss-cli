"""Portal settings — env-driven, _REPO_ROOT pattern."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "portal-self-serve"
    version: str = "0.4.0"
    log_level: str = "INFO"

    # Upstream BSS service endpoints (reads only — writes go through the
    # orchestrator, which has its own URL config).
    catalog_url: str = "http://catalog:8000"
    com_url: str = "http://com:8000"
    subscription_url: str = "http://subscription:8000"
    crm_url: str = "http://crm:8000"

    # Portal-specific
    bss_portal_self_serve_port: int = 9001
    bss_portal_self_serve_session_ttl: int = 600  # seconds; refresh-during-signup = lost


settings = Settings()
