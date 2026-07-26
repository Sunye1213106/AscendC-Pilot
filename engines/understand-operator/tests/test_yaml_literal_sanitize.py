"""Product: YAML literal-block sanitize for extract_plan evidence_snippet."""

from __future__ import annotations

import yaml

from uo.scripts.yaml_literal_sanitize import (
    safe_load_yaml_text,
    sanitize_literal_block_indents,
)


def test_sanitize_pads_dedented_else_brace() -> None:
    raw = """version: 1
receivers:
  - name: emptyTensorTilingDataRegbase
    evidence_snippet: |
                  emptyTensorTilingDataRegbase->set_formerDqNum(aivNum);
                  emptyTensorTilingDataRegbase->set_singleCoreDqNum(dqNum / aivNum);
              } else {
                  emptyTensorTilingDataRegbase->set_formerDqNum(dqNum % aivNum);
    decision_reason: sink confirmed
aliases: []
"""
    # Raw must fail (the bug we hit in production).
    try:
        yaml.safe_load(raw)
        raw_ok = True
    except yaml.YAMLError:
        raw_ok = False
    assert raw_ok is False

    fixed = sanitize_literal_block_indents(raw)
    doc = yaml.safe_load(fixed)
    assert isinstance(doc, dict)
    snip = doc["receivers"][0]["evidence_snippet"]
    assert "} else {" in snip
    assert "set_formerDqNum" in snip
    assert doc.get("aliases") == []


def test_safe_load_yaml_text_roundtrip() -> None:
    raw = """version: 1
writers:
  - name: Foo
    evidence_snippet: |
          foo();
      } else {
          bar();
    role: ignore
"""
    doc = safe_load_yaml_text(raw)
    assert doc["writers"][0]["name"] == "Foo"
    assert "} else {" in doc["writers"][0]["evidence_snippet"]
