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
    remote_required: bool = True
    excluded_keywords: tuple[str, ...] = ("wordpress", "php", "onsite only")
    required_keywords: tuple[str, ...] = ("java", "spring", "sso", "keycloak")
    auto_reject_score_below: int = 45
    alert_score_from: int = 75
    paris_aliases: tuple[str, ...] = ("paris", "ile-de-france", "idf")

    @classmethod
    def from_settings(cls, settings: FilteringSettings) -> FilteringRules:
        return cls(
            minimum_tjm=settings.minimum_tjm,
            remote_required=settings.remote_required,
            excluded_keywords=tuple(settings.excluded_keywords),
            required_keywords=tuple(settings.required_keywords),
            auto_reject_score_below=settings.auto_reject_score_below,
            alert_score_from=settings.alert_score_from,
        )


class FilteringSettings(Protocol):
    minimum_tjm: int
    remote_required: bool
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
    reasons: list[str] = []
    excluded = tuple(keyword for keyword in rules.excluded_keywords if keyword.lower() in text)
    matched_required = tuple(
        keyword for keyword in rules.required_keywords if keyword.lower() in text
    )

    if excluded:
        reasons.append(f"Excluded keyword match: {', '.join(excluded)}.")
    if rules.remote_required and opportunity.remote_mode == RemoteMode.ONSITE:
        reasons.append("Onsite-only mission is not allowed.")
    if opportunity.daily_rate_eur is not None and opportunity.daily_rate_eur < rules.minimum_tjm:
        reasons.append(
            f"TJM {opportunity.daily_rate_eur} is below the minimum {rules.minimum_tjm}."
        )
    if rules.required_keywords and not matched_required:
        reasons.append("No required keywords matched the target stack.")
    if reasons:
        return FilteringResult(
            score=0,
            route=QualificationRoute.REJECT,
            rejected=True,
            reasons=reasons,
            matched_keywords=matched_required,
        )

    signals: dict[str, int] = {}
    if opportunity.remote_mode == RemoteMode.REMOTE:
        signals["remote"] = 30
    elif opportunity.remote_mode == RemoteMode.HYBRID:
        if _contains_any(text, rules.paris_aliases):
            signals["hybrid_paris"] = 10
        else:
            signals["hybrid"] = 5

    if opportunity.daily_rate_eur is not None:
        if opportunity.daily_rate_eur >= 700:
            signals["tjm_700_plus"] = 25
        elif opportunity.daily_rate_eur >= rules.minimum_tjm:
            signals["tjm_floor"] = 10

    if _contains_all(text, ("java", "spring")) or "spring boot" in text:
        signals["java_spring"] = 20
    if _contains_any(text, ("keycloak", "oauth2", "sso", "saml", "auth0", "okta")):
        signals["iam_security"] = 20
    if _contains_any(text, ("banking", "finance", "banque", "bank")):
        signals["banking"] = 15
    if _contains_any(text, ("java 8", "legacy java", "maintenance", "run support", "tma")):
        signals["legacy_stack"] = -10

    score = max(0, min(100, sum(signals.values())))
    if score < rules.auto_reject_score_below:
        reasons.append(
            f"Score {score} is below the auto-reject threshold "
            f"{rules.auto_reject_score_below}."
        )
        return FilteringResult(
            score=score,
            route=QualificationRoute.REJECT,
            rejected=True,
            reasons=reasons,
            matched_keywords=matched_required,
            matched_signals=signals,
        )

    route = (
        QualificationRoute.ALERT
        if score >= rules.alert_score_from
        else QualificationRoute.REVIEW
    )
    reasons.append(
        "Qualified for Telegram alert."
        if route == QualificationRoute.ALERT
        else "Borderline opportunity: keep for manual review."
    )
    return FilteringResult(
        score=score,
        route=route,
        rejected=False,
        reasons=reasons,
        matched_keywords=matched_required,
        matched_signals=signals,
    )


def _contains_all(text: str, keywords: tuple[str, ...]) -> bool:
    return all(keyword in text for keyword in keywords)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)
