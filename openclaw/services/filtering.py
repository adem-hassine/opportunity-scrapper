from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from openclaw.models.domain import Opportunity, RemoteMode


class QualificationRoute(StrEnum):
    REJECT = "reject"
    REVIEW = "review"
    ALERT = "alert"


@dataclass(slots=True)
class FilteringRules:
    minimum_tjm: int = 650
    unspecified_tjm: bool = True
    allowed_remote_modes: tuple[RemoteMode, ...] = (RemoteMode.REMOTE, RemoteMode.HYBRID)
    excluded_keywords: tuple[str, ...] = ("wordpress", "php", "onsite only")
    required_keywords: tuple[str, ...] = ("java", "spring", "sso", "keycloak")
    auto_reject_score_below: int = 45
    alert_score_from: int = 75
    paris_aliases: tuple[str, ...] = ("paris", "ile-de-france", "idf")

    @classmethod
    def from_settings(cls, settings: FilteringSettings) -> FilteringRules:
        return cls(
            minimum_tjm=settings.minimum_tjm,
            unspecified_tjm=settings.unspecified_tjm,
            allowed_remote_modes=tuple(settings.allowed_remote_modes),
            excluded_keywords=tuple(settings.excluded_keywords),
            required_keywords=tuple(settings.required_keywords),
            auto_reject_score_below=settings.auto_reject_score_below,
            alert_score_from=settings.alert_score_from,
        )


class FilteringSettings(Protocol):
    minimum_tjm: int
    unspecified_tjm: bool
    allowed_remote_modes: list[RemoteMode]
    excluded_keywords: list[str]
    required_keywords: list[str]
    auto_reject_score_below: int
    alert_score_from: int


@dataclass(slots=True)
class FilteringResult:
    score: int
    route: QualificationRoute
    rejected: bool
    reasons: list[str] = field(default_factory=list)
    matched_keywords: tuple[str, ...] = field(default_factory=tuple)
    matched_signals: dict[str, int] = field(default_factory=dict)


def score_opportunity(opportunity: Opportunity, rules: FilteringRules) -> FilteringResult:
    text = opportunity.search_blob()
    matched_required = tuple(
        keyword for keyword in rules.required_keywords if keyword.lower() in text
    )

    return FilteringResult(
        score=100,
        route=QualificationRoute.ALERT,
        rejected=False,
        reasons=["Temporary pass-through: send every scraped opportunity to Telegram."],
        matched_keywords=matched_required,
        matched_signals={"temporary_always_alert": 100},
    )


def _contains_all(text: str, keywords: tuple[str, ...]) -> bool:
    return all(keyword in text for keyword in keywords)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)
