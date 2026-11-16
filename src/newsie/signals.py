"""Burst detection and the learned signals that sit beside the label rule.

Learned values are inputs a reader can see. They do not replace `label_claim`.
"""

from __future__ import annotations

import math


def is_burst(current: float, baseline: float, *, factor: float = 2.0) -> bool:
    """True when the current rate is at least `factor` times the trailing baseline."""
    if factor <= 1:
        raise ValueError("factor must be greater than 1")
    if baseline <= 0:
        return current > 0
    return current >= baseline * factor


def outlet_axis(matrix: list[list[float]]) -> list[float]:
    """First axis of an outlet × claim matrix. Show it beside the hand-set spectrum."""
    if not matrix or not matrix[0]:
        return []
    width = len(matrix[0])
    if any(len(row) != width for row in matrix):
        raise ValueError("matrix rows must be the same width")
    height = len(matrix)
    means = [sum(row[column] for row in matrix) / height for column in range(width)]
    centered = [[value - means[column] for column, value in enumerate(row)] for row in matrix]
    vector = [1.0 / width] * width
    for _ in range(24):
        nxt = [0.0] * width
        for row in centered:
            weight = sum(left * right for left, right in zip(row, vector, strict=True))
            for column, value in enumerate(row):
                nxt[column] += weight * value
        norm = math.sqrt(sum(value * value for value in nxt)) or 1.0
        vector = [value / norm for value in nxt]
    return vector


def origin_accuracy(outcomes: dict[str, list[bool]]) -> dict[str, float]:
    """Share of an origin's claims that were later corroborated. Origins, not outlets."""
    scores: dict[str, float] = {}
    for origin, flags in outcomes.items():
        scores[origin] = (sum(1 for flag in flags if flag) / len(flags)) if flags else 0.0
    return scores


def conformal_threshold(scores: list[float], *, alpha: float = 0.1) -> float:
    """Upper quantile of nonconformity scores. Higher means less sure."""
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
    if not scores:
        return 1.0
    ordered = sorted(scores)
    rank = math.ceil((len(ordered) + 1) * (1 - alpha))
    index = min(len(ordered), max(1, rank)) - 1
    return ordered[index]


def least_sure(items: list[tuple[str, float]], k: int) -> list[tuple[str, float]]:
    """Claims with the lowest stance confidence, for the owner to label."""
    if k <= 0:
        return []
    return sorted(items, key=lambda item: (item[1], item[0]))[:k]
