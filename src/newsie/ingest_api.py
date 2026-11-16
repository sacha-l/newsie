"""Authenticated ingest for future news-source agents — quarantine by default."""

from __future__ import annotations

from hashlib import sha256

from newsie.domain import (
    AgentRegistration,
    Article,
    IngestArticlePayload,
    SourceTier,
    TrustState,
)
from newsie.guardrails import BudgetDimension, BudgetLedger, content_hash
from newsie.store import MemoryStore
from newsie.urls import canonicalise_url


class IngestAuthError(RuntimeError):
    pass


class IngestValidationError(RuntimeError):
    pass


def hash_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def ingest_agent_articles(
    store: MemoryStore,
    agents: dict[str, AgentRegistration],
    *,
    bearer_token: str,
    payloads: list[IngestArticlePayload],
    budget: BudgetLedger,
) -> list[Article]:
    token_h = hash_token(bearer_token)
    agent = next((a for a in agents.values() if a.token_hash == token_h), None)
    if agent is None:
        raise IngestAuthError("invalid agent token")
    if agent.trust_state == TrustState.DISABLED:
        raise IngestAuthError("agent disabled")

    saved: list[Article] = []
    for payload in payloads:
        budget.charge(BudgetDimension.FETCHES, 1)
        if not payload.provenance.content_hash:
            raise IngestValidationError("provenance.content_hash required")
        text_hash = content_hash(payload.content_text)
        if payload.provenance.content_hash != text_hash:
            raise IngestValidationError("provenance.content_hash does not match the submitted text")
        article = Article(
            source_id=f"agent:{agent.id}",
            url=str(payload.url),
            canonical_url=canonicalise_url(str(payload.url)),
            title=payload.title,
            published_at=payload.published_at,
            retrieved_at=payload.provenance.retrieved_at,
            content_text=payload.content_text,
            content_hash=text_hash,
            lang=payload.language,
            tier_at_ingest=SourceTier.AGENT_DERIVED,
            raw_metadata={
                "collector": payload.provenance.collector,
                "agent_id": agent.id,
            },
            quarantine_reason=(
                None if agent.trust_state == TrustState.TRUSTED else "agent_quarantine"
            ),
        )
        # Agents cannot self-raise trust or set reporting tier (enforced above)
        saved.append(store.save_article(article))
    return saved


def register_demo_agent(agents: dict[str, AgentRegistration], *, agent_id: str, token: str) -> None:
    agents[agent_id] = AgentRegistration(
        id=agent_id,
        name=agent_id,
        token_hash=hash_token(token),
        trust_state=TrustState.QUARANTINE,
        budget_caps={"fetches": 50},
    )
