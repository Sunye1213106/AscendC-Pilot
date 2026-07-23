from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_FILENAME = ".understand.toml"


def default_config() -> dict[str, Any]:
    return {
        "project": {
            "name": "project",
        },
        "scanner": {
            "cbm_mode": "fast",
            "cbm_required": False,
        },
    }


def load_config(repo_root: Path) -> dict[str, Any]:
    cfg_path = repo_root / DEFAULT_CONFIG_FILENAME
    merged = default_config()
    if cfg_path.exists():
        with cfg_path.open("rb") as f:
            user_data = tomllib.loads(f.read().decode("utf-8"))
        for section, values in user_data.items():
            if isinstance(values, dict) and section in merged:
                merged[section] = {**merged[section], **values}
            else:
                merged[section] = values
    merged.setdefault("project", {})["name"] = repo_root.name
    return merged
