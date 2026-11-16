from __future__ import annotations

from datetime import UTC, datetime

import pytest

from newsie.domain import IngestArticlePayload, Provenance, SourceTier, TrustState
from newsie.guardrails import BudgetDimension, BudgetLedger
from newsie.ingest_api import (
    IngestAuthError,
    hash_token,
    ingest_agent_articles,
    register_demo_agent,
)
from newsie.store import MemoryStore


def test_agent_ingest_quarantines_and_cannot_be_reporting() -> None:
    store = MemoryStore()
    agents: dict = {}
    register_demo_agent(agents, agent_id="fixture-agent", token="secret")
    budget = BudgetLedger(caps={BudgetDimension.FETCHES: 10})
    payloads = [
        IngestArticlePayload(
            url="https://example.test/agent/1",
            title="Agent item",
            content_text="Signal from social",
            provenance=Provenance(
                collector="agent:fixture-agent",
                retrieved_at=datetime.now(UTC),
                content_hash="sha256:abc",
            ),
        )
    ]
    arts = ingest_agent_articles(
        store, agents, bearer_token="secret", payloads=payloads, budget=budget
    )
    assert len(arts) == 1
    assert arts[0].tier_at_ingest == SourceTier.AGENT_DERIVED
    assert arts[0].quarantine_reason == "agent_quarantine"
    assert agents["fixture-agent"].trust_state == TrustState.QUARANTINE


def test_agent_bad_token() -> None:
    store = MemoryStore()
    agents: dict = {}
    register_demo_agent(agents, agent_id="a", token="good")
    budget = BudgetLedger(caps={BudgetDimension.FETCHES: 10})
    with pytest.raises(IngestAuthError):
        ingest_agent_articles(
            store,
            agents,
            bearer_token="bad",
            payloads=[],
            budget=budget,
        )


def test_token_hash_stable() -> None:
    assert hash_token("x") == hash_token("x")
