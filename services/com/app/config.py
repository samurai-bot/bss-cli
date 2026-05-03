from pathlib import Path
from bss_models import BSS_RELEASE
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    service_name: str = "com"
    version: str = BSS_RELEASE
    log_level: str = "INFO"
    db_url: str = ""
    mq_url: str = ""
    crm_url: str = "http://crm:8000"
    catalog_url: str = "http://catalog:8000"
    payment_url: str = "http://payment:8000"
    som_url: str = "http://som:8000"
    subscription_url: str = "http://subscription:8000"
    env: str = "development"
    tenant_default: str = "DEFAULT"

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="BSS_",
        extra="ignore",
    )


settings = Settings()
