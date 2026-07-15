from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from understand_operator._operator.source_reader import SourceReader


LEGACY_IDENTITY_FIELDS = {"fact_key", "relation_key", "source_fact_key", "target_fact_key"}
FORBIDDEN_MODEL_FIELDS = {
    "status",
    "id",
    "stable_id",
    "canonical_key",
    "source_id",
    "target_id",
    "sources",
    "source_text",
    "code_hash",
    "file_hash",
    "encoding",
    "newline",
    "bom",
}
FORBIDDEN_ITEM_FIELDS = FORBIDDEN_MODEL_FIELDS | LEGACY_IDENTITY_FIELDS
FORBIDDEN_RELATION_FIELDS = FORBIDDEN_MODEL_FIELDS | LEGACY_IDENTITY_FIELDS


@dataclass(frozen=True)
class CandidateError:
    code: str
    message: str
    target: str = ""
    fact_key: str = ""
    relation_key: str = ""
    local_id: str = ""
    field: str = ""
    repair_scope: str = "candidate_batch"
    actual_type: str = ""
    expected_type: str = ""
    expected_shape: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if value}


def stable_id(prefix: str, semantic_key: str) -> str:
    normalized = "".join(char if char.isalnum() else "_" for char in semantic_key.upper()).strip("_")
    readable = normalized[:48] or "FACT"
    return f"{prefix}_{readable}_{hashlib.sha256(semantic_key.encode('utf-8')).hexdigest()[:8].upper()}"


def source_anchor(reader: SourceReader, location: dict[str, Any]) -> dict[str, Any]:
    material = "\0".join((str(location["file"]), str(location["symbol"]), str(location["start_line"]), str(location["end_line"]), str(location["anchor_kind"])))
    return {
        "id": stable_id("SRC", material), "file": str(location["file"]), "symbol": str(location["symbol"]),
        "span": {"start_line": location["start_line"], "end_line": location["end_line"]},
        "anchor_kind": location["anchor_kind"],
    }


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CandidateError("CANDIDATE_JSON_INVALID", str(exc), field="$") from exc
