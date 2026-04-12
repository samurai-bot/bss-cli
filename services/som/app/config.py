from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    service_name: str = "som"
    version: str = "0.1.0"
    log_level: str = "INFO"
    db_url: str = ""
    mq_url: str = ""
    crm_url: str = "http://crm:8000"
    env: str = "development"
    tenant_default: str = "DEFAULT"

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="BSS_",
        extra="ignore",
    )


settings = Settings()
