from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class RemoteMode(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"


@dataclass(slots=True)
class Opportunity:
    platform: str
    external_id: str
    title: str
    published_at: date | None = None
    client: str | None = None
    location: str | None = None
    daily_rate_eur: int | None = None
    remote_mode: RemoteMode = RemoteMode.HYBRID
    remote_days_per_week: int | None = None
    summary: str = ""
    keywords: tuple[str, ...] = field(default_factory=tuple)
    industry: str | None = None
    source_url: str | None = None

    def search_blob(self) -> str:
        parts = [
            self.platform,
            self.external_id,
            self.title,
            self.client or "",
            self.location or "",
            self.summary,
            self.industry or "",
            *self.keywords,
        ]
        return " ".join(part for part in parts if part).lower()

    def normalized_keywords(self) -> set[str]:
        return {keyword.strip().lower() for keyword in self.keywords if keyword.strip()}


@dataclass(frozen=True, slots=True)
class ResumeVariant:
    key: str
    label: str
    summary: str
    primary_keywords: tuple[str, ...]
    industries: tuple[str, ...] = field(default_factory=tuple)
    preferred_tone: str = "consultative"
    file_path: str | None = None


@dataclass(slots=True)
class SubmissionResult:
    success: bool
    platform: str
    mission_url: str
    confirmation_url: str | None = None
    error: str | None = None
    submitted_at: datetime | None = None
