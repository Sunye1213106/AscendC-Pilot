from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from understand_operator._operator.source_reader import SourceReader


LEGACY_IDENTITY_FIELDS = {"fact_key", "relation_key", "source_fact_key", "target_fact_key"}
FORBIDDEN_MODEL_FIELDS = {
    "id",
    "stable_id",
    "canonical_key",
    "source_id",
    "target_id",
    "source_text",
    "code_hash",
    "file_hash",
    "sources",
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

    def to_dict(self) -> dict[str, str]:
        return {key: value for key, value in self.__dict__.items() if value}


def stable_id(prefix: str, semantic_key: str) -> str:
    normalized = "".join(char if char.isalnum() else "_" for char in semantic_key.upper()).strip("_")
    readable = normalized[:48] or "FACT"
    return f"{prefix}_{readable}_{hashlib.sha256(semantic_key.encode('utf-8')).hexdigest()[:8].upper()}"


def source_anchor(reader: SourceReader, location: dict[str, Any]) -> dict[str, Any]:
    source = reader.read(str(location["file"]))
    text = source.span(int(location["start_line"]), int(location["end_line"]))
    material = "\0".join((str(location["file"]), str(location["start_line"]), str(location["end_line"]), str(location["symbol"]), str(location["anchor_kind"]), text))
    return {
        "id": stable_id("SRC", material), "file": str(location["file"]), "symbol": str(location["symbol"]),
        "span": {"start_line": location["start_line"], "end_line": location["end_line"]},
        "source_text": text, "code_hash": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "anchor_kind": location["anchor_kind"], "encoding": source.encoding, "file_hash": source.byte_hash,
    }


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CandidateError("CANDIDATE_JSON_INVALID", str(exc), field="$") from exc
