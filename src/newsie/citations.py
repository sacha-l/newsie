"""Citation validator.

Every factual sentence needs a citation. The quote has to occur in the stored
article, and the passage has to support the sentence. A URL that is merely
somewhere in the cluster is only the first gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from newsie.domain import Article, DigestDraft, DigestSentence, SupportRelation
from newsie.evidence import support_relation


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]
    sentences: list[DigestSentence] = field(default_factory=list)


def _article_for(url: str, articles: list[Article]) -> Article | None:
    for article in articles:
        if url == article.url or url == article.canonical_url:
            return article
    return None


_UNCITED = {"note", "unclear", "reporting"}


def _check_sentence(
    sentence: DigestSentence, articles: list[Article], errors: list[str]
) -> DigestSentence:
    if sentence.section in _UNCITED:
        return sentence.model_copy(update={"support_verdict": "unchecked"})
    if not sentence.citations:
        errors.append(f"sentence has no citation: {sentence.text[:80]}")
        return sentence.model_copy(update={"support_verdict": "unsupported"})
    verdict = "supported"
    for citation in sentence.citations:
        article = _article_for(citation.url, articles)
        if article is None:
            errors.append(f"citation not in cluster: {citation.url}")
            verdict = "unsupported"
            continue
        if citation.quote not in article.body_text():
            errors.append(f"quote not in article: {citation.url}")
            verdict = "unsupported"
            continue
        relation = support_relation(sentence.text, citation.quote)
        if relation == SupportRelation.PARTIAL and verdict == "supported":
            verdict = "partial"
        elif relation not in {SupportRelation.DIRECT, SupportRelation.PARTIAL}:
            errors.append(f"passage does not support sentence: {sentence.text[:80]}")
            verdict = "unsupported"
    return sentence.model_copy(update={"support_verdict": verdict})


def validate_draft(draft: DigestDraft, articles: list[Article]) -> ValidationResult:
    allowed = {article.url for article in articles} | {
        article.canonical_url for article in articles
    }
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

    checked: list[DigestSentence] = []
    if draft.sentences:
        for sentence in draft.sentences:
            checked.append(_check_sentence(sentence, articles, errors))
    elif articles and not draft.citations:
        errors.append("digest has no citations")

    return ValidationResult(ok=not errors, errors=errors, sentences=checked)
