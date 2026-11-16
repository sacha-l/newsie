"""Guardrails: kill switch, budgets, idempotent loops, iteration caps.

Inspired by pstack principles: make-operations-idempotent, laziness-protocol,
guard-the-context-window — keep pipeline loops bounded and re-runnable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class BudgetDimension(StrEnum):
    LLM_TOKENS = "llm_tokens"
    FETCHES = "fetches"
    PLAYWRIGHT_MINUTES = "playwright_minutes"
    PIPELINE_STEPS = "pipeline_steps"


class KillSwitchEngagedError(RuntimeError):
    pass


class BudgetExceededError(RuntimeError):
    pass


class LoopLimitExceededError(RuntimeError):
    pass


@dataclass
class KillSwitch:
    engaged: bool = False
    reason: str = ""

    def check(self) -> None:
        if self.engaged:
            raise KillSwitchEngagedError(self.reason or "kill switch engaged")

    def engage(self, reason: str) -> None:
        self.engaged = True
        self.reason = reason

    def clear(self) -> None:
        self.engaged = False
        self.reason = ""


@dataclass
class BudgetLedger:
    caps: dict[BudgetDimension, int]
    used: dict[BudgetDimension, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for dim in BudgetDimension:
            self.used.setdefault(dim, 0)

    def remaining(self, dim: BudgetDimension) -> int:
        return max(0, self.caps.get(dim, 0) - self.used.get(dim, 0))

    def charge(self, dim: BudgetDimension, amount: int = 1) -> None:
        if amount < 0:
            raise ValueError("amount must be non-negative")
        next_used = self.used.get(dim, 0) + amount
        cap = self.caps.get(dim, 0)
        if next_used > cap:
            raise BudgetExceededError(f"{dim} budget exceeded: {next_used}/{cap}")
        self.used[dim] = next_used

    def snapshot(self) -> dict[str, int]:
        return {dim.value: self.used.get(dim, 0) for dim in BudgetDimension}


@dataclass
class LoopGuard:
    """Hard cap on iterations so ingest/cluster loops cannot spin forever."""

    max_iterations: int
    name: str = "loop"
    _count: int = 0

    def tick(self) -> None:
        self._count += 1
        if self._count > self.max_iterations:
            raise LoopLimitExceededError(
                f"{self.name} exceeded max_iterations={self.max_iterations}"
            )

    @property
    def count(self) -> int:
        return self._count


def content_hash(text: str) -> str:
    """Stable content identity for idempotent ingest."""
    import hashlib

    normalized = " ".join(text.split()).strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
