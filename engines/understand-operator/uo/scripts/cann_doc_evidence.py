"""CANN official-document evidence cache (offline-first).

Authority order: operator source → target CANN version docs → latest → other.
Documents supply interface/macro contracts only — never project call edges.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml, write_yaml

DEFAULT_DOC_INDEX = "https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/latest/index/index.html"

# Built-in offline contract fixtures (tests / air-gapped). Not project provenance.
BUILTIN_CONTRACTS: dict[str, dict[str, Any]] = {
    "GET_TPL_TILING_KEY": {
        "symbol_kind": "macro",
        "qualified_names": ['GET_TPL_TILING_KEY'],
        "symbol_or_macro": "GET_TPL_TILING_KEY",
        "document_title": "AscendC TilingKey template helpers",
        "document_url": DEFAULT_DOC_INDEX,
        "cann_version": "offline_fixture",
        "semantic_summary": "Packs Host-side TilingKey arguments in declaration order.",
        "parameter_order": ["dim0", "dim1", "..."],
        "return_semantics": "uint64 tiling key",
        "nullability": "n/a",
        "constraints": ["argument order must match ASCENDC_TPL_ARGS_DECL"],
        "applicable_architecture": "all",
        "evidence_excerpt": "GET_TPL_TILING_KEY(args...) binds by position to ARGS_DECL",
        "confidence": 0.7,
    },
    "ASCENDC_TPL_ARGS_DECL": {
        "symbol_kind": "macro",
        "qualified_names": ['ASCENDC_TPL_ARGS_DECL'],
        "symbol_or_macro": "ASCENDC_TPL_ARGS_DECL",
        "document_title": "AscendC TilingKey ARGS_DECL",
        "document_url": DEFAULT_DOC_INDEX,
        "cann_version": "offline_fixture",
        "semantic_summary": "Declares TilingKey dimensions (declaration_space).",
        "parameter_order": ["op_name", "BOOL/UINT_DECL..."],
        "return_semantics": "declaration only",
        "nullability": "n/a",
        "constraints": ["order defines Host/Kernel positional binding"],
        "applicable_architecture": "all",
        "evidence_excerpt": "ASCENDC_TPL_ARGS_DECL defines declaration_space",
        "confidence": 0.7,
    },
    "ASCENDC_TPL_ARGS_SEL": {
        "symbol_kind": "macro",
        "qualified_names": ['ASCENDC_TPL_ARGS_SEL'],
        "symbol_or_macro": "ASCENDC_TPL_ARGS_SEL",
        "document_title": "AscendC TilingKey ARGS_SEL",
        "document_url": DEFAULT_DOC_INDEX,
        "cann_version": "offline_fixture",
        "semantic_summary": "Compile-time selection space (subset of declaration_space).",
        "parameter_order": ["SEL entries"],
        "return_semantics": "compile selection",
        "nullability": "n/a",
        "constraints": ["must not be merged with declaration_space"],
        "applicable_architecture": "all",
        "evidence_excerpt": "ARGS_SEL defines compile_selection_space",
        "confidence": 0.7,
    },
    "GET_TILING_DATA": {
        "symbol_kind": "macro",
        "qualified_names": ['GET_TILING_DATA'],
        "symbol_or_macro": "GET_TILING_DATA",
        "document_title": "Kernel GetTilingData",
        "document_url": DEFAULT_DOC_INDEX,
        "cann_version": "offline_fixture",
        "semantic_summary": "Loads default TilingData type for current kernel.",
        "parameter_order": ["tiling_data_var"],
        "return_semantics": "fills tiling data struct",
        "nullability": "n/a",
        "constraints": ["type must match REGISTER_TILING_DEFAULT / FOR_TILINGKEY"],
        "applicable_architecture": "all",
        "evidence_excerpt": "GET_TILING_DATA binds kernel reader to registered type",
        "confidence": 0.7,
    },
    "GetOptionalInputShape": {
        "symbol_kind": "method",
        "qualified_names": ['gert::TilingContext::GetOptionalInputShape'],
        "symbol_or_macro": "GetOptionalInputShape",
        "document_title": "TilingContext optional input",
        "document_url": DEFAULT_DOC_INDEX,
        "cann_version": "offline_fixture",
        "semantic_summary": "Returns nullptr when optional input absent; empty tensor is present-but-empty.",
        "parameter_order": ["index"],
        "return_semantics": "gert::Shape* or null",
        "nullability": "nullable",
        "constraints": ["null => absent; non-null empty dims => present_but_empty"],
        "applicable_architecture": "all",
        "evidence_excerpt": "Optional input nullability contract",
        "confidence": 0.7,
    },
    "REGISTER_TILING_TEMPLATE": {
        "symbol_kind": "macro",
        "qualified_names": ['REGISTER_TILING_TEMPLATE'],
        "symbol_or_macro": "REGISTER_TILING_TEMPLATE",
        "document_title": "Host tiling template registration",
        "document_url": DEFAULT_DOC_INDEX,
        "cann_version": "offline_fixture",
        "semantic_summary": "Registers a tiling template class into the op registry.",
        "parameter_order": ["op_type", "template_class"],
        "return_semantics": "registration side-effect",
        "nullability": "n/a",
        "constraints": ["creates registry→class edge"],
        "applicable_architecture": "all",
        "evidence_excerpt": "REGISTER_TILING_TEMPLATE(op, Class)",
        "confidence": 0.7,
    },
}


def docs_cache_dir(uo_root: Path) -> Path:
    path = uo_root / "docs_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_doc_contract(
    uo_root: Path,
    symbol_or_macro: str,
    *,
    cann_version: str = "offline_fixture",
    allow_network: bool = False,
) -> dict[str, Any]:
    """Return structured doc evidence or unresolved payload."""
    cache = docs_cache_dir(uo_root)
    key = re.sub(r"[^A-Za-z0-9_]+", "_", symbol_or_macro)
    cache_path = cache / f"{key}.json"
    if cache_path.exists():
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        data["retrieved_at"] = data.get("retrieved_at") or _now()
        return _version_gate(data, cann_version)

    # Prefer offline builtin fixtures
    if symbol_or_macro in BUILTIN_CONTRACTS:
        data = dict(BUILTIN_CONTRACTS[symbol_or_macro])
        data["retrieved_at"] = _now()
        cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return _version_gate(data, cann_version)

    # Optional packaged fixtures under engines/understand-operator/tests/fixtures/cann_docs
    fixture_root = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "cann_docs"
    fixture = fixture_root / f"{key}.json"
    if fixture.exists():
        data = json.loads(fixture.read_text(encoding="utf-8"))
        data["retrieved_at"] = _now()
        cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return _version_gate(data, cann_version)

    if allow_network:
        fetched = _try_fetch(symbol_or_macro, cann_version)
        if fetched:
            cache_path.write_text(json.dumps(fetched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return _version_gate(fetched, cann_version)

    return {
        "unresolved": True,
        "severity": "degraded",
        "code": "documentation_unavailable",
        "symbol_or_macro": symbol_or_macro,
        "related_symbols": [symbol_or_macro],
        "candidate_files": [],
        "evidence_present": [],
        "evidence_missing": ["cann_doc_page", "offline_cache"],
        "reason": f"no offline cache/fixture for {symbol_or_macro}; network {'disabled' if not allow_network else 'failed'}",
        "cann_version_requested": cann_version,
    }


def collect_doc_evidence_bundle(
    repo_root: Path,
    op_name: str,
    symbols: list[str] | None = None,
    *,
    cann_version: str = "offline_fixture",
    allow_network: bool = False,
) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    symbols = symbols or list(BUILTIN_CONTRACTS)
    items = []
    unresolved = []
    for sym in symbols:
        item = load_doc_contract(uo_root, sym, cann_version=cann_version, allow_network=allow_network)
        if item.get("unresolved"):
            unresolved.append(item)
        else:
            items.append(item)
    payload = {
        "version": 1,
        "op_name": op_name,
        "cann_version": cann_version,
        "authority_order": ["operator_source", "target_cann_docs", "latest_docs", "other"],
        "items": items,
        "unresolved": unresolved,
    }
    write_yaml(uo_root / "ir" / "doc_evidence.yaml", payload)
    return payload


def _version_gate(data: dict[str, Any], requested: str) -> dict[str, Any]:
    have = str(data.get("cann_version") or "")
    if requested and requested not in {"offline_fixture", "latest", ""} and have not in {requested, "offline_fixture"}:
        return {
            "unresolved": True,
            "severity": "degraded",
            "code": "documentation_version_mismatch",
            "symbol_or_macro": data.get("symbol_or_macro"),
            "related_symbols": [data.get("symbol_or_macro")],
            "candidate_files": [],
            "evidence_present": [f"doc_version={have}"],
            "evidence_missing": [f"doc_version={requested}"],
            "reason": f"doc cann_version={have} does not match requested {requested}",
            "document": data,
        }
    return data


def _try_fetch(symbol: str, cann_version: str) -> dict[str, Any] | None:
    # Network fetch is optional; failures must not invent contracts from model memory.
    try:
        import urllib.request

        url = DEFAULT_DOC_INDEX
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
            body = resp.read(2000).decode("utf-8", errors="ignore")
        if not body:
            return None
        # Dynamic pages often lack usable static contracts — record unresolved-ish low confidence.
        return {
            "symbol_or_macro": symbol,
            "document_title": "CANNCommunityEdition index",
            "document_url": url,
            "cann_version": cann_version or "latest",
            "retrieved_at": _now(),
            "semantic_summary": "index page retrieved; symbol-specific contract not parsed",
            "parameter_order": [],
            "return_semantics": "",
            "nullability": "",
            "constraints": [],
            "applicable_architecture": "unknown",
            "evidence_excerpt": body[:240],
            "confidence": 0.2,
        }
    except Exception:
        return None


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect CANN official doc evidence (offline-first)")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--cann-version", default="offline_fixture")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--symbol", action="append", default=[])
    args = parser.parse_args(argv)
    payload = collect_doc_evidence_bundle(
        Path(args.repo).resolve(),
        args.op_name,
        symbols=args.symbol or None,
        cann_version=args.cann_version,
        allow_network=args.allow_network,
    )
    print(f"doc_items={len(payload['items'])} unresolved={len(payload['unresolved'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
