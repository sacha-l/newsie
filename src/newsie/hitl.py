"""HITL approve / reject / rate — no silent publish."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from newsie.balance import balance_report
from newsie.domain import DigestDraft, DigestSentence, Publication
from newsie.guardrails import KillSwitch


class HitlError(RuntimeError):
    pass


def approve_draft(
    store: Any,
    draft_id: UUID,
    *,
    kill_switch: KillSwitch,
    telegram_message_ids: list[str] | None = None,
) -> Publication:
    kill_switch.check()
    draft = store.get_draft(draft_id)
    if draft is None:
        raise HitlError(f"draft not found: {draft_id}")
    if draft.validation_status != "ok":
        raise HitlError(f"draft not validated: {draft.validation_status}")
    for pub in store.publications.values():
        if pub.draft_id == draft_id:
            return Publication.model_validate(pub)  # idempotent re-approve
    snapshot = draft.model_dump(mode="json")
    articles = {article.id: article for article in store.list_articles(skip_quarantined=False)}
    stories = [story for story in store.list_stories() if story.id in set(draft.story_ids)]
    evidence = store.list_evidence() if hasattr(store, "list_evidence") else []
    snapshot["balance_text"] = balance_report(stories, articles, store.sources, evidence)
    publication = Publication(
        draft_id=draft_id,
        approved_at=datetime.now(UTC),
        telegram_message_ids=telegram_message_ids or ["demo-msg-1"],
        immutable_snapshot=snapshot,
    )
    store.save_publication(publication)
    return publication


def reject_draft(store: Any, draft_id: UUID, reason: str) -> DigestDraft:
    draft = store.get_draft(draft_id)
    if draft is None:
        raise HitlError(f"draft not found: {draft_id}")
    updated = draft.model_copy(
        update={"validation_status": f"rejected:{reason}"},
    )
    store.save_draft(updated)
    return DigestDraft.model_validate(updated)


def flag_sentence(
    store: Any,
    draft_id: UUID,
    sentence_id: UUID,
    flag: str = "citation_wrong",
) -> DigestSentence:
    """Record that a citation is wrong and count it against the source."""
    raw = store.mark_sentence_flag(draft_id, sentence_id, flag)
    if raw is None:
        raise HitlError(f"sentence not found: {sentence_id}")
    sentence = DigestSentence.model_validate(raw)
    if flag == "citation_wrong":
        articles = {article.id: article for article in store.list_articles(skip_quarantined=False)}
        for citation in sentence.citations:
            article = articles.get(citation.article_id)
            if article is not None:
                store.record_citation_failure(article.source_id)
    return sentence
