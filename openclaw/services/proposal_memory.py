from __future__ import annotations

from dataclasses import dataclass

from openclaw.models.domain import Opportunity
from openclaw.services.resume_selector import ResumeMatch

IMPORTANT_MEMORY_KEYWORDS = (
    "java",
    "spring",
    "spring boot",
    "keycloak",
    "oauth2",
    "saml",
    "kubernetes",
    "aws",
    "security",
    "banking",
)


@dataclass(frozen=True, slots=True)
class ProposalMemoryQuery:
    client_type: str | None
    industry: str | None
    stack_keywords: tuple[str, ...]
    resume_key: str | None
    preferred_tone: str


def build_memory_query(
    opportunity: Opportunity,
    resume_match: ResumeMatch | None,
) -> ProposalMemoryQuery:
    text = opportunity.search_blob()
    stack_keywords = tuple(keyword for keyword in IMPORTANT_MEMORY_KEYWORDS if keyword in text)
    preferred_tone = (
        "enterprise"
        if any(keyword in text for keyword in ("banking", "security", "architecture"))
        else "consultative"
    )
    return ProposalMemoryQuery(
        client_type=opportunity.client,
        industry=opportunity.industry,
        stack_keywords=stack_keywords,
        resume_key=resume_match.key if resume_match is not None else None,
        preferred_tone=preferred_tone,
    )

