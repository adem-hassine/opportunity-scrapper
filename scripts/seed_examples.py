"""Seed proposal_examples DB table from data/proposal_examples/*.md files.

Usage:
    .venv/bin/python scripts/seed_examples.py
"""
from openclaw.core.config import get_settings, resolve_repo_path
from openclaw.db.session import get_session
from openclaw.models.storage import ProposalExampleRecord
from openclaw.services.proposal_generator import _load_examples
from sqlalchemy import select


def main() -> None:
    settings = get_settings()
    examples_dir = resolve_repo_path(settings.proposal_examples_dir)
    examples = _load_examples(examples_dir)

    if not examples:
        print(f"No examples found in {examples_dir}")
        return

    seeded = 0
    with get_session() as session:
        for ex in examples:
            existing = session.scalars(
                select(ProposalExampleRecord).where(ProposalExampleRecord.title == ex.title)
            ).first()
            if existing:
                existing.stack_keywords = ex.stack_keywords
                existing.industry = ex.industry
                existing.tone = ex.tone
                existing.proposal_text = ex.proposal_text
            else:
                session.add(ProposalExampleRecord(
                    title=ex.title,
                    client_type=None,
                    industry=ex.industry,
                    tone=ex.tone,
                    stack_keywords=ex.stack_keywords,
                    proposal_text=ex.proposal_text,
                    outcome_status=None,
                    metadata_json={},
                ))
            seeded += 1

    print(f"Seeded {seeded} examples.")


if __name__ == "__main__":
    main()
