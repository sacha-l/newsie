"""Even-handedness check — the same template, with party names swapped.

The digest does not get a different prompt per party. This compares two renders
that differ only by the name that was in the source text.
"""

from __future__ import annotations


def render_attributed(speaker: str, statement: str) -> str:
    return f"{speaker} stated: {statement}"


def _only(text: str, party: str, other: str) -> bool:
    if party not in text:
        return False
    if other in party or party in other:
        return True
    return other not in text


def label_swap_ok(
    left: str,
    right: str,
    *,
    party_a: str,
    party_b: str,
    length_ratio_max: float = 1.15,
) -> bool:
    """True when each render names only its party and the two are about the same length."""
    if not _only(left, party_a, party_b) or not _only(right, party_b, party_a):
        return False
    shorter = max(1, min(len(left), len(right)))
    longer = max(len(left), len(right))
    return longer / shorter <= length_ratio_max
