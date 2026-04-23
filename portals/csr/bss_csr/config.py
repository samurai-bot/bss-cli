"""CSR portal settings — env-driven, _REPO_ROOT pattern."""

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

    service_name: str = "portal-csr"
    version: str = "0.5.0"
    log_level: str = "INFO"

    # Upstream BSS service endpoints (read-path; writes go through the
    # orchestrator via agent_bridge).
    catalog_url: str = "http://catalog:8000"
    com_url: str = "http://com:8000"
    crm_url: str = "http://crm:8000"
    payment_url: str = "http://payment:8000"
    subscription_url: str = "http://subscription:8000"

    # Stub login session lifetime — operator stays logged in across
    # idle gaps within a single demo run, but session is lost on
    # process restart (in-memory).
    bss_portal_csr_port: int = 9002
    bss_portal_csr_session_ttl: int = 3600  # one hour
