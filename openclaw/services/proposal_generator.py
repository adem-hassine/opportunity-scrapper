from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import openai

from openclaw.core.config import Settings, resolve_repo_path
from openclaw.models.domain import Opportunity
from openclaw.services.proposal_memory import ProposalMemoryQuery
from openclaw.services.resume_selector import ResumeMatch

SYSTEM_PROMPT = (
    "Tu es un expert en adaptation de propositions commerciales freelance.\n"
    "Tu reçois une proposition existante réussie et une offre de mission.\n"
    "Adapte la proposition à la nouvelle offre en conservant le ton et la structure, "
    "mais en personnalisant le contenu.\n"
    "Réponds uniquement avec le texte de la proposition, sans commentaires ni balises."
)


@dataclass(frozen=True)
class ProposalExample:
    title: str
    stack_keywords: list[str]
    industry: str | None
    tone: str
    proposal_text: str


def generate_proposal(
    opportunity: Opportunity,
    resume_match: ResumeMatch | None,
    memory_query: ProposalMemoryQuery | None,
    settings: Settings,
) -> str:
    examples = _load_examples(resolve_repo_path(settings.proposal_examples_dir))
    best = _find_best_example(examples, memory_query) if memory_query else None
    user_message = _build_user_message(opportunity, resume_match, memory_query, best)

    client = openai.OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )
    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        max_tokens=1024,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


def _load_examples(examples_dir: Path) -> list[ProposalExample]:
    examples: list[ProposalExample] = []
    for path in sorted(examples_dir.glob("*.md")):
        try:
            example = _parse_example_file(path)
            if example:
                examples.append(example)
        except Exception:
            pass
    return examples


def _parse_example_file(path: Path) -> ProposalExample | None:
    content = path.read_text(encoding="utf-8")
    parts = re.split(r"^---\s*$", content, maxsplit=2, flags=re.MULTILINE)
    if len(parts) < 3:
        return None

    frontmatter_text = parts[1].strip()
    proposal_text = parts[2].strip()

    meta: dict[str, str] = {}
    for line in frontmatter_text.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()

    title = meta.get("title", path.stem)
    tone = meta.get("tone", "consultative")
    industry = meta.get("industry") or None

    raw_keywords = meta.get("stack_keywords", "")
    if raw_keywords.startswith("["):
        try:
            stack_keywords = json.loads(raw_keywords)
        except json.JSONDecodeError:
            stack_keywords = [k.strip().strip('"') for k in raw_keywords.strip("[]").split(",") if k.strip()]
    else:
        stack_keywords = [k.strip() for k in raw_keywords.split(",") if k.strip()]

    return ProposalExample(
        title=title,
        stack_keywords=stack_keywords,
        industry=industry,
        tone=tone,
        proposal_text=proposal_text,
    )


def _find_best_example(
    examples: list[ProposalExample],
    memory_query: ProposalMemoryQuery,
) -> ProposalExample | None:
    best: ProposalExample | None = None
    best_score = 0

    query_keywords = {kw.lower() for kw in memory_query.stack_keywords}
    query_industry = (memory_query.industry or "").lower()

    for example in examples:
        score = sum(2 for kw in example.stack_keywords if kw.lower() in query_keywords)
        if query_industry and example.industry and example.industry.lower() == query_industry:
            score += 3
        if score > best_score:
            best_score = score
            best = example

    return best if best_score > 0 else None


def _build_user_message(
    opportunity: Opportunity,
    resume_match: ResumeMatch | None,
    memory_query: ProposalMemoryQuery | None,
    example: ProposalExample | None,
) -> str:
    sections: list[str] = []

    tjm_line = f"TJM : {opportunity.daily_rate_eur} €/jour" if opportunity.daily_rate_eur else "TJM : non précisé"
    client_line = f"Client : {opportunity.client}" if opportunity.client else "Client : non précisé"
    keywords_line = f"Stack / mots-clés : {', '.join(opportunity.keywords)}" if opportunity.keywords else ""
    summary_line = f"Résumé : {opportunity.summary}" if opportunity.summary else ""

    offer_parts = [
        f"Titre : {opportunity.title}",
        client_line,
        tjm_line,
        f"Mode : {opportunity.remote_mode.value}",
    ]
    if keywords_line:
        offer_parts.append(keywords_line)
    if summary_line:
        offer_parts.append(summary_line)

    sections.append("## Offre de mission\n" + "\n".join(offer_parts))

    if example:
        sections.append("## Proposition de référence\n" + example.proposal_text)
    else:
        sections.append("## Proposition de référence\nAucune proposition similaire disponible.")

    if resume_match:
        sections.append(
            f"## Profil CV sélectionné\n"
            f"Profil : {resume_match.label}\n"
            f"Justification : {resume_match.rationale}"
        )

    tone = memory_query.preferred_tone if memory_query else "consultative"
    sections.append(f"## Ton souhaité\n{tone}")

    return "\n\n".join(sections)
