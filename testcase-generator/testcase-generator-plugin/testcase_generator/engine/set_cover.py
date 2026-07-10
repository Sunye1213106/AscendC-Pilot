from __future__ import annotations

from typing import Any


def greedy_set_cover(
    valid_candidates: list[dict[str, Any]],
    obligations: list[dict[str, Any]],
) -> dict[str, Any]:
    # Positive obligations only; unreachable_proof / L2 negatives are not cover targets.
    uncovered = {
        ob["id"]
        for ob in obligations
        if ob.get("id") and ob.get("type") != "unreachable_proof"
    }
    # L2 / expect_reject candidates are kept separately and always appended.
    positives = [
        c
        for c in valid_candidates
        if c.get("level") != "L2" and not c.get("expect_reject")
    ]
    negatives = [
        c
        for c in valid_candidates
        if c.get("level") == "L2" or c.get("expect_reject")
    ]

    selected: list[dict[str, Any]] = []
    remaining = list(positives)

    while uncovered and remaining:
        best = None
        best_gain = 0
        for cand in remaining:
            covers = set(cand.get("covers", []))
            gain = len(covers & uncovered)
            if gain > best_gain:
                best_gain = gain
                best = cand
        if best is None or best_gain == 0:
            break
        selected.append(best)
        uncovered -= set(best.get("covers", []))
        remaining.remove(best)

    selected.extend(negatives)

    return {
        "version": 1,
        "strategy": "greedy_set_cover",
        "selected": selected,
        "selected_count": len(selected),
        "selected_positive": len(selected) - len(negatives),
        "selected_negative_l2": len(negatives),
        "uncovered_obligations": sorted(uncovered),
    }
