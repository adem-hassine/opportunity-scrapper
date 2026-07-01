from __future__ import annotations

from datetime import date, datetime
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from openclaw.models.domain import RemoteMode

REPO_ROOT = Path(__file__).resolve().parents[2]


class FreelanceCriteria(BaseModel):
    minimum_tjm: int
    unspecified_tjm: bool
    minimum_duration_months: int


class CddCdiCriteria(BaseModel):
    minimum_year_salary: int


class JobCriteria(BaseModel):
    platform_targets: list[str] = Field(default_factory=lambda: ["free-work", "malt", "lehibou"])
    employment_type: list[str] = Field(default_factory=lambda: ["freelance"])
    freelance_criteria: FreelanceCriteria | None = None
    cdd_cdi_criteria: CddCdiCriteria | None = None
    allowed_remote_modes: list[RemoteMode] = Field(
        default_factory=lambda: [RemoteMode.REMOTE, RemoteMode.HYBRID]
    )
    excluded_keywords: list[str] = Field(
        default_factory=lambda: ["wordpress", "php", "onsite only"]
    )
    required_keywords: list[str] = Field(
        default_factory=lambda: ["java", "spring", "sso", "keycloak"]
    )
    publication_date: str | None = None

    @field_validator(
        "platform_targets",
        "employment_type",
        "excluded_keywords",
        "required_keywords",
        mode="before",
    )
    @classmethod
    def split_csv(cls, value: Any) -> Any:
        if value is None:
            return value
        if isinstance(value, list):
            items: list[Any] = []
            for item in value:
                if isinstance(item, str):
                    items.extend(part.strip() for part in item.split(",") if part.strip())
                else:
                    items.append(item)
            return items
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("allowed_remote_modes", mode="before")
    @classmethod
    def normalize_remote_modes(cls, value: Any) -> Any:
        if value is None:
            return value
        raw_values = value if isinstance(value, list) else [value]
        values: list[Any] = []
        for item in raw_values:
            if isinstance(item, str):
                values.extend(part.strip() for part in item.split(",") if part.strip())
            else:
                values.append(item)
        return [_normalize_remote_mode(item) for item in values]

    @model_validator(mode="after")
    def validate_employment_criteria(self) -> JobCriteria:
        employment_types = {_normalize_employment_type(value) for value in self.employment_type}
        employment_types.discard(None)

        if "freelance" in employment_types and self.freelance_criteria is None:
            raise ValueError("freelance_criteria is required when employment_type includes freelance.")
        if employment_types.intersection({"cdi", "cdd"}) and self.cdd_cdi_criteria is None:
            raise ValueError("cdd_cdi_criteria is required when employment_type includes cdi or cdd.")

        return self


def _normalize_employment_type(value: str) -> str | None:
    item = value.strip().lower().replace("-", " ")
    if item in {"freelance", "contractor", "mission"}:
        return "freelance"
    if item in {"cdi", "permanent"}:
        return "cdi"
    if item in {"cdd", "fixed term", "fixed term contract"}:
        return "cdd"
    return item or None


def _normalize_remote_mode(value: Any) -> str:
    item = str(value).strip().lower().replace("_", " ").replace("-", " ")
    if item in {"remote", "full remote", "fully remote", "100% remote"}:
        return RemoteMode.REMOTE.value
    if item in {"hybrid", "hybride", "partial remote", "teletravail partiel"}:
        return RemoteMode.HYBRID.value
    if item in {"onsite", "on site", "sur site", "presentiel", "présentiel"}:
        return RemoteMode.ONSITE.value
    return item


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
        if self.job_criteria.freelance_criteria is None:
            return 0
        return self.job_criteria.freelance_criteria.minimum_tjm

    @property
    def unspecified_tjm(self) -> bool:
        if self.job_criteria.freelance_criteria is None:
            return False
        return self.job_criteria.freelance_criteria.unspecified_tjm

    @property
    def minimum_duration_months(self) -> int:
        if self.job_criteria.freelance_criteria is None:
            return 0
        return self.job_criteria.freelance_criteria.minimum_duration_months

    @property
    def minimum_year_salary(self) -> int:
        if self.job_criteria.cdd_cdi_criteria is None:
            return 0
        return self.job_criteria.cdd_cdi_criteria.minimum_year_salary

    @property
    def employment_type(self) -> list[str]:
        return list(self.job_criteria.employment_type)

    @property
    def allowed_remote_modes(self) -> list[RemoteMode]:
        return list(self.job_criteria.allowed_remote_modes)

    @property
    def excluded_keywords(self) -> list[str]:
        return list(self.job_criteria.excluded_keywords)

    @property
    def required_keywords(self) -> list[str]:
        return list(self.job_criteria.required_keywords)

    @property
    def publication_date(self) -> date | None:
        raw = self.job_criteria.publication_date
        if raw is None:
            return None
        try:
            return datetime.strptime(raw, "%d/%m/%Y").date()
        except ValueError:
            return None

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
