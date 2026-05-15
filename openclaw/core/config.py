from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "OpenClaw"
    environment: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://openclaw:openclaw@localhost:5432/openclaw"

    openai_api_key: str = ""
    openai_model: str = "replace-me"
    openai_embeddings_model: str = "replace-me"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_allowed_user_ids: list[int] = Field(default_factory=list)

    monitor_interval_seconds: int = 900
    platform_targets: list[str] = Field(default_factory=lambda: ["free-work", "malt", "lehibou"])

    minimum_tjm: int = 650
    remote_required: bool = True
    excluded_keywords: list[str] = Field(
        default_factory=lambda: ["wordpress", "php", "onsite only"]
    )
    required_keywords: list[str] = Field(
        default_factory=lambda: ["java", "spring", "sso", "keycloak"]
    )
    auto_reject_score_below: int = 45
    alert_score_from: int = 75

    resume_dir: str = "data/resumes"
    proposal_examples_dir: str = "data/proposal_examples"
    playwright_storage_dir: str = "data/playwright"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator(
        "platform_targets",
        "excluded_keywords",
        "required_keywords",
        mode="before",
    )
    @classmethod
    def split_csv(cls, value: Any) -> Any:
        if value is None or isinstance(value, list):
            return value
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("telegram_allowed_user_ids", mode="before")
    @classmethod
    def split_int_csv(cls, value: Any) -> Any:
        if value is None or isinstance(value, list):
            return value
        if isinstance(value, str):
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        return value

    def public_summary(self) -> dict[str, object]:
        return {
            "app_name": self.app_name,
            "environment": self.environment,
            "platform_targets": self.platform_targets,
            "monitor_interval_seconds": self.monitor_interval_seconds,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()

