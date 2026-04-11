from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service_name: str = "bss-service"
    log_level: str = "INFO"
    db_url: str = ""
    mq_url: str = ""
    env: str = "development"
    tenant_default: str = "DEFAULT"

    model_config = {"env_prefix": "BSS_", "extra": "ignore"}


settings = Settings()
