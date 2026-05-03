"""Portal settings — env-driven, _REPO_ROOT pattern."""

from __future__ import annotations

from pathlib import Path

from bss_models import BSS_RELEASE
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "portal-self-serve"
    version: str = BSS_RELEASE
    log_level: str = "INFO"

    # Upstream BSS service endpoints. v0.4–v0.9: reads only (signup
    # writes routed through the orchestrator). v0.10+: post-login
    # self-serve routes write directly via these clients (see CLAUDE.md
    # doctrine carve-out); signup + chat continue going through the
    # orchestrator.
    catalog_url: str = "http://catalog:8000"
    com_url: str = "http://com:8000"
    subscription_url: str = "http://subscription:8000"
    crm_url: str = "http://crm:8000"
    payment_url: str = "http://payment:8000"
    provisioning_url: str = "http://provisioning:8000"

    # Portal-specific
    bss_portal_self_serve_port: int = 9001
    bss_portal_self_serve_session_ttl: int = 600  # seconds; refresh-during-signup = lost

    # v0.8 — DB connection used for portal_auth identity / session storage.
    # Same `BSS_DB_URL` env every BSS service reads. The portal does not
    # write to BSS-core schemas (CRM, catalog, etc.) — only to portal_auth.
    bss_db_url: str = ""

    # v0.15 — KYC adapter selection.
    bss_portal_kyc_provider: str = "prebaked"
    bss_portal_kyc_didit_api_key: str = ""
    bss_portal_kyc_didit_workflow_id: str = ""
    bss_portal_kyc_didit_webhook_secret: str = ""
    # Public URL for the portal — used as the base for the Didit return_url
    # passed to KycVerificationAdapter.initiate(). Falls back to a localhost
    # default for dev / tests; production deployments set this via env.
    bss_portal_public_url: str = "http://localhost:9001"

    # v0.16 — payment provider mode (read by signup templates to decide
    # mock card-number form vs Stripe.js + Elements). The publishable
    # key is the only Stripe value the browser needs; the secret key
    # stays in the payment service. Defaults to mock so a portal that
    # boots without these env vars set keeps the v0.1-v0.15 behavior.
    bss_payment_provider: str = "mock"
    bss_payment_stripe_publishable_key: str = ""
    bss_env: str = "development"


settings = Settings()
