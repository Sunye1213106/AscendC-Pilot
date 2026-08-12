from code_engineering.evidence_tier import path_tier


def test_path_tier_weakest_wins() -> None:
    assert path_tier(["A", "A"]) == "A"
    assert path_tier(["A", "B", "A"]) == "B"
    assert path_tier(["B", "C", "A"]) == "C"
    assert path_tier([]) == "C"
