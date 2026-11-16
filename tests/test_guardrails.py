from __future__ import annotations

import pytest

from newsie.guardrails import (
    BudgetDimension,
    BudgetExceededError,
    BudgetLedger,
    KillSwitch,
    KillSwitchEngagedError,
    LoopGuard,
    LoopLimitExceededError,
    content_hash,
)


def test_kill_switch_blocks() -> None:
    ks = KillSwitch()
    ks.check()
    ks.engage("test")
    with pytest.raises(KillSwitchEngagedError):
        ks.check()


def test_budget_hard_stop() -> None:
    ledger = BudgetLedger(caps={BudgetDimension.FETCHES: 2})
    ledger.charge(BudgetDimension.FETCHES, 1)
    ledger.charge(BudgetDimension.FETCHES, 1)
    with pytest.raises(BudgetExceededError):
        ledger.charge(BudgetDimension.FETCHES, 1)


def test_loop_guard_caps_iterations() -> None:
    guard = LoopGuard(max_iterations=3, name="t")
    guard.tick()
    guard.tick()
    guard.tick()
    with pytest.raises(LoopLimitExceededError):
        guard.tick()


def test_content_hash_idempotent() -> None:
    a = content_hash("Hello   World")
    b = content_hash("hello world")
    assert a == b
    assert a.startswith("sha256:")
