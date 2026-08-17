from code_engineering.evidence_tier import classify_entity, classify_relation, path_tier


def test_path_tier_weakest_wins() -> None:
    assert path_tier(["A", "A"]) == "A"
    assert path_tier(["A", "B", "A"]) == "B"
    assert path_tier(["B", "C", "A"]) == "C"
    assert path_tier([]) == "C"


def test_classify_uses_trust_not_confirmed_status() -> None:
    advisory = {
        "id": "r1",
        "src": "a",
        "dst": "b",
        "kind": "CALLS",
        "status": "confirmed",
        "attrs": {
            "trust": "advisory",
            "provenance": "source_kernel_call_bound",
            "evidence_source": "lexical",
        },
    }
    authoritative = {
        "id": "r2",
        "src": "a",
        "dst": "b",
        "kind": "CALLS",
        "status": "confirmed",
        "attrs": {
            "trust": "authoritative",
            "provenance": "clang_ast",
            "evidence_source": "clang_ast",
        },
    }
    legacy = {
        "id": "r3",
        "src": "a",
        "dst": "b",
        "kind": "CALLS",
        "status": "confirmed",
        "attrs": {
            "trust": "legacy_unknown",
            "provenance": "clang_ast",
            "evidence_source": "unspecified",
        },
    }
    derived = {
        "id": "r4",
        "src": "a",
        "dst": "b",
        "kind": "BINDS",
        "status": "confirmed",
        "attrs": {
            "trust": "derived",
            "provenance": "source_tpl_args",
            "evidence_source": "deterministic_dsl",
        },
    }
    assert classify_relation(advisory) == "C"
    assert classify_relation(authoritative) == "A"
    assert classify_relation(legacy) == "B"
    assert classify_relation(derived) == "B"
    assert classify_entity(
        {
            "id": "e1",
            "kind": "FUNCTION",
            "name": "K",
            "status": "confirmed",
            "attrs": {
                "trust": "advisory",
                "provenance": "lexical_regex",
                "evidence_source": "lexical",
            },
        }
    ) == "C"
    assert classify_entity(
        {
            "id": "e2",
            "kind": "FUNCTION",
            "name": "K",
            "status": "confirmed",
            "attrs": {
                "trust": "authoritative",
                "provenance": "clang_ast",
                "evidence_source": "clang_ast",
            },
        }
    ) == "A"
