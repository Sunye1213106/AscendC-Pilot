from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def semantic_snapshot_hash(snapshot: dict[str, Any]) -> str:
    semantic = {
        "op_name": snapshot.get("op_name"),
        "view": snapshot.get("view"),
        "files": snapshot.get("files"),
        "source_artifact_hashes": snapshot.get("source_artifact_hashes"),
    }
    return stable_hash(semantic)
