from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from openclaw.models.domain import Opportunity, ResumeVariant


@dataclass(frozen=True, slots=True)
class ResumeMatch:
    key: str
    label: str
    score: int
    matched_keywords: tuple[str, ...]
    rationale: str


_RESUME_LANG_DIRS = ("en", "fr")

_ROLE_KEYWORD_MAP: dict[str, tuple[str, ...]] = {
    "java": ("java", "spring", "spring boot", "j2ee", "jakarta"),
    "technical lead": ("java", "spring", "spring boot", "lead", "architecture", "rest", "microservices"),
    "sso": ("sso", "keycloak", "oauth2", "saml", "auth0", "okta", "iam"),
    "iam": ("sso", "keycloak", "oauth2", "saml", "auth0", "okta", "iam"),
    "full stack": ("java", "spring", "react", "angular", "typescript", "rest"),
}


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _parse_resume_filename(stem: str) -> tuple[str, str, str] | None:
    """Parse a resume filename stem into (name, lang, role).

    Expected pattern: <name> - <EN|FR> - <role>
    """
    m = re.match(r"^(.+?)\s*-\s*(EN|FR)\s*-\s*(.+)$", stem, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).strip(), m.group(2).upper(), m.group(3).strip()


def load_resume_variants(resume_dir: str | Path) -> tuple[ResumeVariant, ...]:
    resume_path = Path(resume_dir)
    variants: list[ResumeVariant] = []

    for lang_dir in _RESUME_LANG_DIRS:
        lang_path = resume_path / lang_dir
        if not lang_path.is_dir():
            continue
        for pdf_path in sorted(lang_path.glob("*.pdf")):
            parsed = _parse_resume_filename(pdf_path.stem)
            if parsed is None:
                continue
            _name, lang, role = parsed
            label = f"{role} ({lang})"
            key = _slugify(f"{role}-{lang}")

            keywords: set[str] = set()
            for word in re.split(r"[\s&/]+", role.lower()):
                mapped = _ROLE_KEYWORD_MAP.get(word)
                if mapped:
                    keywords.update(mapped)
            if not keywords:
                keywords.add(role.lower())

            variants.append(ResumeVariant(
                key=key,
                label=label,
                summary=f"{role} resume ({lang}).",
                primary_keywords=tuple(sorted(keywords)),
                file_path=str(pdf_path),
            ))

    return tuple(variants)


def select_best_resume(
    opportunity: Opportunity,
    resumes: tuple[ResumeVariant, ...],
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

