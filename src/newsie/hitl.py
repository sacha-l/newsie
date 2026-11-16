"""HITL approve / reject / rate — no silent publish."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from newsie.domain import DigestDraft, Publication
from newsie.guardrails import KillSwitch
from newsie.store import MemoryStore


class HitlError(RuntimeError):
    pass


def approve_draft(
    store: MemoryStore,
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
            return pub  # idempotent re-approve
    publication = Publication(
        draft_id=draft_id,
        approved_at=datetime.now(UTC),
        telegram_message_ids=telegram_message_ids or ["demo-msg-1"],
        immutable_snapshot=draft.model_dump(mode="json"),
    )
    store.save_publication(publication)
    return publication


def reject_draft(store: MemoryStore, draft_id: UUID, reason: str) -> DigestDraft:
    draft = store.get_draft(draft_id)
    if draft is None:
        raise HitlError(f"draft not found: {draft_id}")
    updated = draft.model_copy(
        update={"validation_status": f"rejected:{reason}"},
    )
    store.save_draft(updated)
    return updated
