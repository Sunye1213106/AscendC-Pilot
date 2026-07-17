from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml, snippet, write_yaml
from uo.scripts.cbm_client import CbmClient, read_source_snippet

ROLE_PATTERNS: dict[str, tuple[str, ...]] = {
    # Prefer exact AscendC host tiling entry names; avoid bare "Tiling" (too noisy).
    "host_tiling_entry": ("DoOpTiling", "DoTiling"),
    "get_tiling_key": ("GetTilingKey",),
    "save_tiling_data": ("SaveToTilingData",),
    "init_tiling_data": ("InitTilingData",),
    # Kernel entry: prefer launch/entry symbols over generic Process helpers.
    "kernel_entry": ("KernelEntry", "Invoke", "FlashAttentionScoreGradKernel", "FlashAttentionScoreGrad", "RegbaseFAG"),
}
EXACT_PREFERRED = {
    "host_tiling_entry": ("DoOpTiling",),
    "get_tiling_key": ("GetTilingKey",),
    "save_tiling_data": ("SaveToTilingData",),
    "init_tiling_data": ("InitTilingData",),
    "kernel_entry": ("FlashAttentionScoreGradKernel", "RegbaseFAG", "KernelEntry"),
}

REGISTER_RE = re.compile(
    r"REGISTER_TILING_TEMPLATE(?:_WITH_ARCH)?\s*\(\s*([^,]+)\s*,\s*([^,\)]+)",
    re.MULTILINE,
)


def collect_entrypoint_candidates(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    auto_confirm_high_confidence: bool = True,
) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    client = CbmClient(uo_root)
    confirmed_files = _confirmed_files(uo_root)
    roles: dict[str, Any] = {}
    for role, patterns in ROLE_PATTERNS.items():
        candidates = []
        for pattern in patterns:
            if client.available:
                # exact-ish name search first, then suffix/contains
                for name_pat in (pattern, f"%{pattern}", f"%{pattern}%"):
                    for hit in client.search_symbols(name_pattern=name_pat, file_contains=op_name or architecture, limit=30):
                        if architecture and architecture not in hit.file_path.replace("\\", "/"):
                            if role == "kernel_entry" or role.startswith("host") or role in {
                                "get_tiling_key",
                                "save_tiling_data",
                                "init_tiling_data",
                            }:
                                continue
                        conf = _confidence(role, hit.name, hit.file_path, op_name, architecture)
                        if conf < 0.45:
                            continue
                        candidates.append(
                            {
                                **hit.as_dict(),
                                "pattern": pattern,
                                "confidence": conf,
                                "signature_snippet": snippet(
                                    read_source_snippet(repo_root, hit.file_path, hit.start_line, hit.start_line + 8)
                                ),
                                "needs_llm": conf < 0.85,
                            }
                        )
            # filesystem fallback: exact token match only
            for path in _scan_paths(repo_root, confirmed_files, architecture, role):
                text = path.read_text(encoding="utf-8", errors="ignore")
                for match in re.finditer(rf"\b({re.escape(pattern)})\b", text):
                    name = match.group(1)
                    rel = path.relative_to(repo_root).as_posix()
                    if architecture and architecture not in rel:
                        continue
                    conf = _confidence(role, name, rel, op_name, architecture)
                    if conf < 0.45:
                        continue
                    line = text.count("\n", 0, match.start()) + 1
                    candidates.append(
                        {
                            "node_id": 0,
                            "name": name,
                            "qualified_name": f"{rel}::{name}",
                            "file_path": rel,
                            "start_line": line,
                            "end_line": line,
                            "label": "filesystem",
                            "pattern": pattern,
                            "confidence": conf,
                            "signature_snippet": snippet("\n".join(text.splitlines()[max(0, line - 1) : line + 6])),
                            "needs_llm": conf < 0.85,
                        }
                    )
        # kernel entry special: scan __global__ in arch kernel files
        if role == "kernel_entry":
            candidates.extend(_scan_global_kernels(repo_root, confirmed_files, op_name, architecture))
        candidates = _dedupe_candidates(candidates)
        selected = None
        if auto_confirm_high_confidence:
            preferred = EXACT_PREFERRED.get(role) or ()
            exact = [c for c in candidates if c.get("name") in preferred and c.get("confidence", 0) >= 0.8]
            if len(exact) == 1:
                selected = {**exact[0], "confirmed_by": "deterministic_exact_name"}
            elif len(exact) > 1:
                ranked = sorted(
                    exact,
                    key=lambda c: (
                        -float(c.get("confidence") or 0),
                        0 if architecture in str(c.get("file_path") or "") else 1,
                        0 if op_name in str(c.get("file_path") or "") else 1,
                        0 if "normal" in str(c.get("file_path") or "").lower() else 1,
                        0 if "entry" in str(c.get("file_path") or "").lower() else 1,
                        c.get("file_path") or "",
                    ),
                )
                # Exact preferred names in-scope: pick best-ranked deterministically.
                if architecture in str(ranked[0].get("file_path") or ""):
                    selected = {**ranked[0], "confirmed_by": "deterministic_exact_ranked"}
            if selected is None:
                high = [c for c in candidates if c["confidence"] >= 0.9]
                if role == "kernel_entry":
                    # Prefer real kernel class/entry over macro/field noise.
                    ranked = sorted(
                        candidates,
                        key=lambda c: (
                            0 if str(c.get("name") or "") in (EXACT_PREFERRED.get("kernel_entry") or ()) else 1,
                            0 if str(c.get("label") or "").lower() in {"class", "method", "function", "global_kernel", "entry_symbol"} else 1,
                            0 if str(c.get("name") or "").endswith("Kernel") else 1,
                            0 if "entry" in str(c.get("file_path") or "").lower() else 1,
                            0 if "kernel" in str(c.get("name") or "").lower() else 1,
                            0 if architecture in str(c.get("file_path") or "") else 1,
                            -float(c.get("confidence") or 0),
                            c.get("file_path") or "",
                        ),
                    )
                    top = ranked[0] if ranked else None
                    top_name = str((top or {}).get("name") or "")
                    top_conf = float((top or {}).get("confidence") or 0)
                    # Auto-pick when the best hit is a clear kernel class / preferred name.
                    if top and (
                        top_name in (EXACT_PREFERRED.get("kernel_entry") or ())
                        or (top_name.endswith("Kernel") and top_conf >= 0.65)
                        or top_conf >= 0.75
                    ):
                        selected = {**top, "confirmed_by": "deterministic_kernel_ranked"}
                elif len(high) == 1:
                    selected = {**high[0], "confirmed_by": "deterministic_high_confidence"}
                elif len(high) > 1:
                    ranked = sorted(high, key=lambda c: (-c["confidence"], 0 if op_name in c["file_path"] else 1, c["file_path"]))
                    if ranked[0]["confidence"] > ranked[1]["confidence"] + 0.05:
                        selected = {**ranked[0], "confirmed_by": "deterministic_ranked"}
        roles[role] = {
            "candidates": candidates,
            "selected": selected,
            "status": "confirmed" if selected else ("missing" if not candidates else "needs_llm"),
        }

    registry = _scan_register_macros(repo_root, confirmed_files, architecture)
    payload = {
        "version": 1,
        "op_name": op_name,
        "architecture": architecture,
        "cbm_available": client.available,
        "cbm_project": client.project,
        "roles": roles,
        "tiling_templates": registry,
        "llm_required_roles": [role for role, body in roles.items() if body["status"] == "needs_llm"],
    }
    client.close()
    return payload


def apply_entrypoint_confirmation(candidates_doc: dict[str, Any], confirmation: dict[str, Any]) -> dict[str, Any]:
    """Merge LLM/human confirmation into entrypoints.yaml shape."""
    roles_out: dict[str, Any] = {}
    for role, body in (candidates_doc.get("roles") or {}).items():
        selected = body.get("selected")
        conf_item = (confirmation.get("roles") or {}).get(role) or {}
        if conf_item.get("qualified_name") or conf_item.get("name"):
            chosen = None
            for cand in body.get("candidates") or []:
                if cand.get("qualified_name") == conf_item.get("qualified_name") or cand.get("name") == conf_item.get("name"):
                    chosen = {**cand, "confirmed_by": conf_item.get("confirmed_by") or "llm", "rationale": conf_item.get("rationale")}
                    break
            if chosen is None:
                chosen = {
                    "name": conf_item.get("name"),
                    "qualified_name": conf_item.get("qualified_name"),
                    "file_path": conf_item.get("file_path"),
                    "start_line": conf_item.get("start_line") or 0,
                    "end_line": conf_item.get("end_line") or 0,
                    "confidence": conf_item.get("confidence") or 0.5,
                    "confirmed_by": conf_item.get("confirmed_by") or "llm",
                    "rationale": conf_item.get("rationale"),
                }
            selected = chosen
        roles_out[role] = {
            "selected": selected,
            "status": "confirmed" if selected else body.get("status"),
            "candidate_count": len(body.get("candidates") or []),
        }
    return {
        "version": 1,
        "op_name": candidates_doc.get("op_name"),
        "architecture": candidates_doc.get("architecture"),
        "roles": roles_out,
        "tiling_templates": candidates_doc.get("tiling_templates") or [],
        "source": "entrypoint_confirmation",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect host/kernel entrypoint candidates with confidence scores")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--architecture", default="arch35")
    parser.add_argument("--write", action="store_true", help="Write ir/entrypoint_candidates.yaml")
    parser.add_argument("--confirm-patch", help="Optional LLM confirmation YAML to produce ir/entrypoints.yaml")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    uo_root = existing_operator_root(repo_root, op_name)
    candidates = collect_entrypoint_candidates(repo_root, op_name, architecture=args.architecture)
    if args.write:
        write_yaml(uo_root / "ir" / "entrypoint_candidates.yaml", candidates)
        # if all roles already confirmed, also write entrypoints.yaml
        if not candidates.get("llm_required_roles"):
            confirmed = apply_entrypoint_confirmation(candidates, {"roles": {}})
            # fill from selected already present
            for role, body in candidates["roles"].items():
                confirmed["roles"][role] = {
                    "selected": body.get("selected"),
                    "status": body.get("status"),
                    "candidate_count": len(body.get("candidates") or []),
                }
            write_yaml(uo_root / "ir" / "entrypoints.yaml", confirmed)
    if args.confirm_patch:
        patch = read_yaml(Path(args.confirm_patch))
        entrypoints = apply_entrypoint_confirmation(candidates, patch)
        write_yaml(uo_root / "ir" / "entrypoints.yaml", entrypoints)
    print(f"entrypoint roles={list(candidates['roles'])} llm_required={candidates.get('llm_required_roles')}")
    return 0


def _confidence(role: str, name: str, file_path: str, op_name: str, architecture: str) -> float:
    score = 0.2
    file_path = file_path.replace("\\", "/")
    if op_name and op_name in file_path:
        score += 0.2
    if architecture and architecture in file_path:
        score += 0.25
    elif architecture and f"/arch" in file_path and architecture not in file_path:
        score -= 0.35
    preferred = EXACT_PREFERRED.get(role) or ()
    if name in preferred:
        score += 0.45
    elif any(name == pat for pat in ROLE_PATTERNS.get(role, ())):
        score += 0.3
    elif any(name.endswith(pat) for pat in ROLE_PATTERNS.get(role, ())):
        score += 0.15
    else:
        score -= 0.1
    if role.startswith("host") or role in {"get_tiling_key", "save_tiling_data", "init_tiling_data"}:
        if "/op_host/" in file_path:
            score += 0.15
        if "/op_kernel/" in file_path:
            score -= 0.4
    if role == "kernel_entry":
        if "/op_kernel/" in file_path:
            score += 0.2
        if "/op_host/" in file_path:
            score -= 0.4
        if name.endswith("Kernel"):
            score += 0.25
        if "entry" in name.lower() or "entry" in file_path:
            score += 0.25
        if "kernel_base" in file_path or file_path.endswith("kernel.h"):
            score += 0.15
        if "template_tiling_key" in file_path or "tiling_data" in file_path:
            score -= 0.5
        # Drop field/member noise (short lowercase / obvious non-types).
        if name[:1].islower() or name in {"pipe", "dqGm", "Init", "Process"}:
            score -= 0.45
    return max(0.0, min(1.0, score))


def _dedupe_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for item in items:
        key = f"{item.get('qualified_name')}|{item.get('file_path')}|{item.get('start_line')}"
        prev = best.get(key)
        if prev is None or item.get("confidence", 0) > prev.get("confidence", 0):
            best[key] = item
    return sorted(best.values(), key=lambda x: (-float(x.get("confidence") or 0), x.get("file_path") or "", x.get("name") or ""))


def _confirmed_files(uo_root: Path) -> list[str]:
    import json

    for path in sorted((uo_root / "runs").glob("*/phase0/scope_confirmed.yaml"), reverse=True):
        data = read_yaml(path)
        files = data.get("confirmed_file_list")
        if isinstance(files, list) and files:
            return [str(item.get("path") if isinstance(item, dict) else item).replace("\\", "/") for item in files]
    meta_path = uo_root / "cbm" / "index_meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        files = meta.get("indexed_files") or []
        return [str(item.get("path") if isinstance(item, dict) else item).replace("\\", "/") for item in files]
    return []


def _scan_paths(repo_root: Path, confirmed_files: list[str], architecture: str, role: str) -> list[Path]:
    paths: list[Path] = []
    for rel in confirmed_files:
        if architecture and architecture not in rel and "/op_host/" not in rel and "/op_kernel/" not in rel:
            continue
        if role == "kernel_entry" and "/op_kernel/" not in rel:
            continue
        if role != "kernel_entry" and "/op_host/" not in rel and "template_tiling_key" not in rel:
            continue
        path = repo_root / rel
        if path.exists() and path.suffix in {".h", ".cpp", ".cc", ".c"}:
            paths.append(path)
    if paths:
        return paths
    # fallback glob
    if role == "kernel_entry":
        return list(repo_root.glob(f"**/{architecture}/**/*kernel*.h"))[:40]
    return list(repo_root.glob(f"**/{architecture}/**/*tiling*.cpp"))[:40] + list(repo_root.glob(f"**/{architecture}/**/*tiling*.h"))[:40]


def _scan_global_kernels(repo_root: Path, confirmed_files: list[str], op_name: str, architecture: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    global_re = re.compile(r"__global__\s+[^=;{]*?\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
    for rel in confirmed_files:
        rel_n = rel.replace("\\", "/")
        if "/op_kernel/" not in rel_n:
            continue
        if architecture and architecture not in rel_n:
            continue
        path = repo_root / rel
        if not path.exists() or path.suffix not in {".h", ".cpp", ".cc", ".c"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in global_re.finditer(text):
            name = match.group(1)
            line = text.count("\n", 0, match.start()) + 1
            conf = _confidence("kernel_entry", name, rel_n, op_name, architecture) + 0.1
            out.append(
                {
                    "node_id": 0,
                    "name": name,
                    "qualified_name": f"{rel_n}::{name}",
                    "file_path": rel_n,
                    "start_line": line,
                    "end_line": line,
                    "label": "global_kernel",
                    "pattern": "__global__",
                    "confidence": min(1.0, conf),
                    "signature_snippet": snippet("\n".join(text.splitlines()[max(0, line - 1) : line + 5])),
                    "needs_llm": conf < 0.85,
                }
            )
    # also prefer *entry* headers as kernel entry candidates
    for rel in confirmed_files:
        rel_n = rel.replace("\\", "/")
        if architecture not in rel_n or "entry" not in Path(rel_n).name.lower():
            continue
        if "/op_kernel/" not in rel_n:
            continue
        path = repo_root / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*Entry[A-Za-z0-9_]*)\b", text):
            name = match.group(1)
            line = text.count("\n", 0, match.start()) + 1
            conf = _confidence("kernel_entry", name, rel_n, op_name, architecture) + 0.2
            out.append(
                {
                    "node_id": 0,
                    "name": name,
                    "qualified_name": f"{rel_n}::{name}",
                    "file_path": rel_n,
                    "start_line": line,
                    "end_line": line,
                    "label": "entry_symbol",
                    "pattern": "Entry",
                    "confidence": min(1.0, conf),
                    "signature_snippet": snippet("\n".join(text.splitlines()[max(0, line - 1) : line + 5])),
                    "needs_llm": conf < 0.85,
                }
            )
    return out


def _scan_register_macros(repo_root: Path, confirmed_files: list[str], architecture: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rel in confirmed_files:
        if "/op_host/" not in rel:
            continue
        path = repo_root / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in REGISTER_RE.finditer(text):
            out.append(
                {
                    "op_type": match.group(1).strip(),
                    "template_class": match.group(2).strip(),
                    "file_path": rel,
                    "line": text.count("\n", 0, match.start()) + 1,
                    "architecture_hint": architecture if architecture in rel else "",
                }
            )
    return out


if __name__ == "__main__":
    raise SystemExit(main())
