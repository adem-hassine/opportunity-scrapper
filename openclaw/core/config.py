from functools import cached_property, lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class JobCriteria(BaseModel):
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


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return (REPO_ROOT / candidate).resolve()


def load_job_criteria(path: str | Path) -> JobCriteria:
    resolved_path = resolve_repo_path(path)
    if not resolved_path.exists():
        raise FileNotFoundError(
            f"Job criteria file does not exist: {resolved_path}. "
            "Set JOB_CRITERIA_FILE in .env to a valid YAML file."
        )

    raw_data = _load_yaml_mapping(resolved_path)
    if not isinstance(raw_data, dict):
        raise ValueError(f"Job criteria file must contain a top-level mapping: {resolved_path}")

    return JobCriteria.model_validate(raw_data)


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")

    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        parsed = _load_simple_yaml_mapping(text)
    else:
        parsed = yaml.safe_load(text) or {}

    if not isinstance(parsed, dict):
        raise ValueError(f"Expected a YAML mapping in {path}, got {type(parsed).__name__}.")
    return parsed


def _load_simple_yaml_mapping(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_list_key: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        if raw_line[:1].isspace():
            stripped = line.strip()
            if stripped.startswith("- ") and current_list_key is not None:
                list_value = data.setdefault(current_list_key, [])
                if not isinstance(list_value, list):
                    raise ValueError(f"YAML key {current_list_key!r} cannot contain both a scalar and a list.")
                list_value.append(_parse_yaml_scalar(stripped[2:].strip()))
                continue
            raise ValueError("Only top-level mappings and simple lists are supported without PyYAML.")

        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(f"Invalid YAML line: {raw_line}")

        key = key.strip()
        value = value.strip()

        if not value:
            data[key] = []
            current_list_key = key
            continue

        current_list_key = None
        data[key] = _parse_yaml_scalar(value)

    return data


def _parse_yaml_scalar(value: str) -> Any:
    if not value:
        return ""
    if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
        return value[1:-1]

    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    if value.isdigit():
        return int(value)
    return value


class Settings(BaseSettings):
    app_name: str = "OpenClaw"
    environment: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://openclaw:openclaw@localhost:5432/openclaw"

    openai_api_key: str = ""
    openai_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    openai_model: str = "gemini-2.0-flash"
    openai_embeddings_model: str = "text-embedding-004"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_allowed_user_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    monitor_interval_seconds: int = 900
    job_criteria_file: str = "config/job_criteria.yml"

    resume_dir: str = "data/resumes"
    proposal_examples_dir: str = "data/proposal_examples"
    playwright_storage_dir: str = "data/playwright"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("telegram_allowed_user_ids", mode="before")
    @classmethod
    def split_int_csv(cls, value: Any) -> Any:
        if value is None or isinstance(value, list):
            return value
        if isinstance(value, str):
            if not value.strip():
                return []
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        return value

    @cached_property
    def job_criteria(self) -> JobCriteria:
        return load_job_criteria(self.job_criteria_file)

    @property
    def platform_targets(self) -> list[str]:
        return list(self.job_criteria.platform_targets)

    @property
    def minimum_tjm(self) -> int:
        return self.job_criteria.minimum_tjm

    @property
    def remote_required(self) -> bool:
        return self.job_criteria.remote_required

    @property
    def excluded_keywords(self) -> list[str]:
        return list(self.job_criteria.excluded_keywords)

    @property
    def required_keywords(self) -> list[str]:
        return list(self.job_criteria.required_keywords)

    @property
    def auto_reject_score_below(self) -> int:
        return self.job_criteria.auto_reject_score_below

    @property
    def alert_score_from(self) -> int:
        return self.job_criteria.alert_score_from

    def public_summary(self) -> dict[str, object]:
        return {
            "app_name": self.app_name,
            "environment": self.environment,
            "platform_targets": self.platform_targets,
            "monitor_interval_seconds": self.monitor_interval_seconds,
            "job_criteria_file": str(resolve_repo_path(self.job_criteria_file)),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
