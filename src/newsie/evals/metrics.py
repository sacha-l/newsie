"""Scores for the phase exit checks.

Wire-copy rate and BCubed run on whatever corpus you pass in. The label file
in data/gold is a handful of constructed cases, not the 100-sentence audit.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from newsie.domain import Article, Story


def wire_copy_rate(stories: list[Story], articles_by_id: dict[UUID, Article]) -> float | None:
    """Share of multi-article stories whose articles share one origin."""
    multi = 0
    copied = 0
    for story in stories:
        members = [
            articles_by_id[article_id]
            for article_id in story.article_ids
            if article_id in articles_by_id
        ]
        if len(members) < 2:
            continue
        multi += 1
        origins = {article.origin_id or f"source:{article.source_id}" for article in members}
        if len(origins) == 1:
            copied += 1
    if multi == 0:
        return None
    return copied / multi


def bcubed(predicted: dict[str, str], gold: dict[str, str]) -> tuple[float, float]:
    """Precision and recall over items present in both maps. Cluster ids are labels."""
    items = [item for item in gold if item in predicted]
    if not items:
        return 0.0, 0.0
    precision_sum = 0.0
    recall_sum = 0.0
    for item in items:
        pred_set = {other for other, label in predicted.items() if label == predicted[item]}
        gold_set = {other for other, label in gold.items() if label == gold[item]}
        overlap = pred_set & gold_set
        precision_sum += len(overlap) / len(pred_set)
        recall_sum += len(overlap) / len(gold_set)
    count = len(items)
    return precision_sum / count, recall_sum / count


def outlet_count_label(outlet_count: int) -> str:
    """The old rule: two outlet names counted as corroboration."""
    if outlet_count >= 2:
        return "corroborated"
    return "single_origin"


def score_label_rows(rows: list[dict[str, object]]) -> dict[str, float]:
    if not rows:
        return {"evidence": 0.0, "outlet_count": 0.0}
    evidence_hits = 0
    outlet_hits = 0
    for row in rows:
        human = str(row["human"])
        if str(row["evidence_label"]) == human:
            evidence_hits += 1
        outlets = int(str(row["outlet_count"]))
        if outlet_count_label(outlets) == human:
            outlet_hits += 1
    count = len(rows)
    return {"evidence": evidence_hits / count, "outlet_count": outlet_hits / count}


def beats_baseline(rows: list[dict[str, object]]) -> bool:
    scored = score_label_rows(rows)
    return scored["evidence"] > scored["outlet_count"]


def pair_scores(
    predicted_same: set[tuple[str, str]],
    gold_same: set[tuple[str, str]],
) -> tuple[float, float]:
    """Precision and recall for unordered same-origin pairs."""

    def _norm(pairs: set[tuple[str, str]]) -> set[tuple[str, str]]:
        normalised: set[tuple[str, str]] = set()
        for left, right in pairs:
            normalised.add((left, right) if left <= right else (right, left))
        return normalised

    predicted = _norm(predicted_same)
    gold = _norm(gold_same)
    if not predicted and not gold:
        return 1.0, 1.0
    overlap = predicted & gold
    precision = len(overlap) / len(predicted) if predicted else 0.0
    recall = len(overlap) / len(gold) if gold else 0.0
    return precision, recall


def extraction_scores(found: list[str], gold: list[str]) -> tuple[float, float]:
    """Share of gold facts captured, and share of extracted claims that stand alone in gold."""
    if not gold and not found:
        return 1.0, 1.0
    captured = 0
    for fact in gold:
        if any(fact in claim or claim in fact for claim in found):
            captured += 1
    stood = 0
    for claim in found:
        if any(fact in claim or claim in fact for fact in gold):
            stood += 1
    coverage = captured / len(gold) if gold else 0.0
    standalone = stood / len(found) if found else 0.0
    return coverage, standalone


def macro_f1(predicted: list[str], gold: list[str], labels: tuple[str, ...]) -> float:
    if len(predicted) != len(gold):
        raise ValueError("prediction and gold length mismatch")
    scores: list[float] = []
    for label in labels:
        pairs = list(zip(predicted, gold, strict=True))
        tp = sum(1 for pred, truth in pairs if pred == truth == label)
        fp = sum(1 for pred, truth in pairs if pred == label and truth != label)
        fn = sum(1 for pred, truth in pairs if truth == label and pred != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        if precision + recall == 0:
            scores.append(0.0)
        else:
            scores.append(2 * precision * recall / (precision + recall))
    return sum(scores) / len(scores) if scores else 0.0


def citation_support_rate(supported: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return supported / total


def load_label_rows(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("label file must be a list")
    rows: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("label row must be an object")
        rows.append(item)
    return rows
