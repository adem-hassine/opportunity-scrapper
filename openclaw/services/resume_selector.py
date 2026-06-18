from __future__ import annotations

from dataclasses import dataclass

from openclaw.models.domain import Opportunity, ResumeVariant


@dataclass(frozen=True, slots=True)
class ResumeMatch:
    key: str
    label: str
    score: int
    matched_keywords: tuple[str, ...]
    rationale: str


DEFAULT_RESUME_VARIANTS: tuple[ResumeVariant, ...] = (
    ResumeVariant(
        key="java-backend",
        label="Java Backend",
        summary="Generic Java/Spring backend consulting profile.",
        primary_keywords=("java", "spring", "spring boot", "rest", "microservices"),
        industries=("banking", "finance", "retail"),
        preferred_tone="consultative",
        file_path="data/resumes/java-backend.pdf",
    ),
    ResumeVariant(
        key="iam-sso",
        label="IAM / SSO Expert",
        summary="Identity, federation, and access management profile.",
        primary_keywords=("keycloak", "oauth2", "sso", "saml", "auth0", "okta"),
        industries=("banking", "insurance", "security"),
        preferred_tone="enterprise",
        file_path="data/resumes/iam-sso.pdf",
    ),
    ResumeVariant(
        key="enterprise-architect",
        label="Enterprise Architect",
        summary="Enterprise modernization and architecture profile.",
        primary_keywords=("architecture", "governance", "transformation", "integration"),
        industries=("banking", "public", "enterprise"),
        preferred_tone="enterprise",
        file_path="data/resumes/enterprise-architect.pdf",
    ),
    ResumeVariant(
        key="api-security",
        label="API Security",
        summary="API and application security consulting profile.",
        primary_keywords=("security", "api", "gateway", "oauth2", "zero trust"),
        industries=("banking", "security", "healthcare"),
        preferred_tone="enterprise",
        file_path="data/resumes/api-security.pdf",
    ),
    ResumeVariant(
        key="cloud-migration",
        label="Cloud Migration",
        summary="Cloud modernization and Kubernetes migration profile.",
        primary_keywords=("aws", "azure", "gcp", "kubernetes", "migration", "modernization"),
        industries=("banking", "saas", "enterprise"),
        preferred_tone="consultative",
        file_path="data/resumes/cloud-migration.pdf",
    ),
)


def select_best_resume(
    opportunity: Opportunity,
    resumes: tuple[ResumeVariant, ...] = DEFAULT_RESUME_VARIANTS,
) -> ResumeMatch:
    text = opportunity.search_blob()
    best_match: ResumeMatch | None = None

    for resume in resumes:
        matched_keywords = tuple(keyword for keyword in resume.primary_keywords if keyword in text)
        score = len(matched_keywords) * 15
        if opportunity.industry and opportunity.industry.lower() in {
            industry.lower() for industry in resume.industries
        }:
            score += 10
        if resume.key == "iam-sso" and any(
            keyword in text for keyword in ("keycloak", "oauth2", "sso", "saml", "auth0", "okta")
        ):
            score += 10
        if resume.key == "cloud-migration" and any(
            keyword in text for keyword in ("aws", "azure", "gcp", "kubernetes", "migration")
        ):
            score += 10
        if score == 0:
            continue

        rationale = (
            f"Matched keywords: {', '.join(matched_keywords)}."
            if matched_keywords
            else "Matched through industry alignment."
        )
        candidate = ResumeMatch(
            key=resume.key,
            label=resume.label,
            score=score,
            matched_keywords=matched_keywords,
            rationale=rationale,
        )
        if best_match is None or candidate.score > best_match.score:
            best_match = candidate

    if best_match is not None:
        return best_match

    fallback = resumes[0]
    return ResumeMatch(
        key=fallback.key,
        label=fallback.label,
        score=5,
        matched_keywords=tuple(),
        rationale="Fallback to the default Java backend resume.",
    )

