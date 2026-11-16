"""Citation validator — claims must reference URLs present in the story cluster."""

from __future__ import annotations

from dataclasses import dataclass

from newsie.domain import Article, DigestDraft


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]


def validate_draft(draft: DigestDraft, articles: list[Article]) -> ValidationResult:
    allowed = {a.url for a in articles} | {a.canonical_url for a in articles}
    errors: list[str] = []

    for url in draft.citations:
        if url not in allowed:
            errors.append(f"citation not in cluster: {url}")

    for brief in draft.perspectives:
        for url in brief.citation_urls:
            if url not in allowed:
                errors.append(f"perspective citation not in cluster: {url}")

    for event in draft.events:
        for url in event.citation_urls:
            if url not in allowed:
                errors.append(f"event citation not in cluster: {url}")

    # Fabrication heuristic: empty citations when content exists
    if articles and not draft.citations:
        errors.append("digest has no citations")

    return ValidationResult(ok=not errors, errors=errors)
