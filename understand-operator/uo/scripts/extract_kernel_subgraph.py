from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml, snippet, stable_id, write_yaml

IF_CONSTEXPR_RE = re.compile(r"\bif\s*constexpr\s*\((.+?)\)", re.DOTALL)
IF_RUNTIME_RE = re.compile(r"\bif\s*\((.+?)\)", re.DOTALL)
MACRO_IF_RE = re.compile(r"^\s*#\s*if(?:n?def)?\s+(.+)$", re.MULTILINE)
TILING_DATA_READ_RE = re.compile(
    r"tilingData(?:->|\.)([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)"
)
KERNEL_DERIVED_READ_RE = re.compile(
    r"(?:constInfo|commonConstInfo|deterConstInfo|runInfo)(?:->|\.)([A-Za-z0-9_\.]+)"
)
# field == ENUM / field == Type::ENUM / field == static_cast<T>(Type::ENUM)
FIELD_EQ_ENUM_RE = re.compile(
    r"(?:(?:this\s*->\s*)?(?:[A-Za-z_]\w*\s*(?:\.|->)\s*)*)"
    r"([A-Za-z_]\w*)\s*==\s*"
    r"(?:static_cast\s*<[^>]+>\s*\(\s*)?"
    r"(?:([A-Za-z_]\w*)\s*::\s*)?"
    r"([A-Z][A-Z0-9_]{1,})\s*\)?"
)
ENUM_CLASS_RE = re.compile(
    r"enum\s+class\s+([A-Za-z_]\w*)\s*(?::\s*[^{]+)?\{([^}]*)\}",
    re.DOTALL,
)
ENUM_MEMBER_RE = re.compile(
    r"([A-Za-z_]\w*)\s*(?:=\s*([0-9]+))?\s*(?:,|$)",
)
CONSTEXPR_INT_RE = re.compile(
    r"^\s*constexpr\s+(u?int(?:8|16|32|64)_t|int|unsigned(?:\s+int)?)\s+"
    r"([A-Z][A-Z0-9_]*)\s*=\s*([0-9]+)\s*;",
    re.MULTILINE,
)
TEMPLATE_PARAM_RE = re.compile(r"\b(IS_[A-Z0-9_]+|is[A-Z][A-Za-z0-9_]*|has[A-Z][A-Za-z0-9_]*)\b")
LOOP_RE = re.compile(r"\bfor\s*\((.+?)\)", re.DOTALL)
OP_MARKERS = {
    "CopyIn": re.compile(r"\bCopyIn\b|\bDataCopy\b.*(?:GM|gm).*?(?:UB|L1|l1|ub)", re.IGNORECASE),
    "CopyOut": re.compile(r"\bCopyOut\b|\bDataCopy\b.*(?:UB|L1).*?(?:GM|gm|out)", re.IGNORECASE),
    "Compute": re.compile(r"\b(Compute|Matmul|Softmax|Muls|Adds|PipeBarrier)\b"),
    "Sync": re.compile(r"\b(PipeBarrier|SetFlag|WaitFlag)\b"),
    "Init": re.compile(r"\bInit\b"),
    "Process": re.compile(r"\bProcess\b"),
}


@dataclass
class EnumEntry:
    name: str
    value: int | None = None


@dataclass
class DeclaredDomain:
    kind: str  # enum_class | constexpr_block
    type_name: str
    entries: list[EnumEntry]
    file_path: str = ""
    start_line: int = 0

    @property
    def names(self) -> list[str]:
        return [e.name for e in self.entries]

    @property
    def name_set(self) -> set[str]:
        return {e.name for e in self.entries}


@dataclass
class FieldEnumUsage:
    field: str
    branch_literals: set[str] = field(default_factory=set)
    declared: DeclaredDomain | None = None


def extract_kernel_subgraph(repo_root: Path, op_name: str, *, architecture: str = "arch35") -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    entrypoints = read_yaml(uo_root / "ir" / "entrypoints.yaml")
    selected = ((entrypoints.get("roles") or {}).get("kernel_entry") or {}).get("selected")
    unresolved: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    branches: list[dict[str, Any]] = []

    kernel_files = _kernel_files(repo_root, op_name, architecture, selected)
    if not kernel_files:
        unresolved.append(
            {
                "id": "UNRES_KERNEL_FILES",
                "kind": "kernel_files_missing",
                "message": "No arch35 kernel files found for extraction",
                "file_path": "",
                "snippet": "",
            }
        )

    entry_id = "KPATH_ENTRY"
    nodes.append(
        {
            "id": entry_id,
            "layer": "kernel",
            "node_type": "KernelEntry",
            "name": (selected or {}).get("name") or "KernelEntry",
            "qualified_name": (selected or {}).get("qualified_name") or "KernelEntry",
            "file_path": (selected or {}).get("file_path") or "",
            "start_line": int((selected or {}).get("start_line") or 0),
            "end_line": int((selected or {}).get("end_line") or 0),
        }
    )
    nodes.append({"id": "KEY_TILINGKEY", "layer": "bridge", "node_type": "TilingKey", "name": "TilingKey", "qualified_name": "TilingKey", "file_path": "", "start_line": 0, "end_line": 0})
    edges.append({"id": "E_KEY_SELECTS_KPATH", "type": "selects", "source": "KEY_TILINGKEY", "target": entry_id})

    loaded_fields: set[str] = set()
    field_usage: dict[str, FieldEnumUsage] = {}
    declared_domains = collect_declared_domains(
        _enum_declaration_files(repo_root, op_name, architecture) + kernel_files
    )

    for path in kernel_files:
        rel = path.relative_to(repo_root).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        # compile-time macros
        for match in MACRO_IF_RE.finditer(text):
            cond = match.group(1).strip()
            line = text.count("\n", 0, match.start()) + 1
            branch = _make_branch(
                name=f"macro_{line}",
                rel=rel,
                line=line,
                condition=cond,
                binding_time="compile_time",
                determinant_source="CompileMacro",
                determinant_ref=cond.split()[0],
            )
            branches.append(branch)
            nodes.append(branch["node"])
            edges.append({"id": stable_id("E_", entry_id, branch["node"]["id"]), "type": "contains", "source": entry_id, "target": branch["node"]["id"]})

        # if constexpr
        for idx, match in enumerate(IF_CONSTEXPR_RE.finditer(text)):
            cond = " ".join(match.group(1).split())
            line = text.count("\n", 0, match.start()) + 1
            refs = TEMPLATE_PARAM_RE.findall(cond)
            branch = _make_branch(
                name=f"constexpr_{idx}",
                rel=rel,
                line=line,
                condition=cond,
                binding_time="compile_time",
                determinant_source="TemplateArg",
                determinant_ref=refs[0] if refs else cond,
                domain=_bool_domain_from_cond(cond),
            )
            branches.append(branch)
            nodes.append(branch["node"])
            edges.append({"id": stable_id("E_", entry_id, branch["node"]["id"]), "type": "contains", "source": entry_id, "target": branch["node"]["id"]})

        # runtime if (exclude constexpr already matched by requiring no constexpr keyword nearby)
        for idx, match in enumerate(IF_RUNTIME_RE.finditer(text)):
            # skip constexpr matches
            window_start = max(0, match.start() - 12)
            if "constexpr" in text[window_start:match.start()]:
                continue
            cond = " ".join(match.group(1).split())
            if len(cond) > 240:
                continue
            line = text.count("\n", 0, match.start()) + 1
            tiling_hits = list(TILING_DATA_READ_RE.findall(cond))
            derived_hits = list(KERNEL_DERIVED_READ_RE.findall(cond))
            eq_hits = extract_field_enum_comparisons(cond)
            branch_literals = sorted({lit for _, lit in eq_hits})
            for fld, lit in eq_hits:
                usage = field_usage.setdefault(fld, FieldEnumUsage(field=fld))
                usage.branch_literals.add(lit)

            if tiling_hits:
                source = "TilingDataField"
                ref = tiling_hits[0]
                loaded_fields.add(tiling_hits[0].split(".")[-1])
                kvar_id = stable_id("KVAR_", tiling_hits[0].split(".")[-1])
                nodes.append(
                    {
                        "id": kvar_id,
                        "layer": "kernel",
                        "node_type": "KernelVariable",
                        "name": tiling_hits[0].split(".")[-1],
                        "qualified_name": tiling_hits[0],
                        "file_path": rel,
                        "start_line": line,
                        "end_line": line,
                        "domain": branch_literals or None,
                    }
                )
                tdf_id = stable_id("TDF_", tiling_hits[0].split(".")[-1])
                nodes.append(
                    {
                        "id": tdf_id,
                        "layer": "bridge",
                        "node_type": "TilingDataField",
                        "name": tiling_hits[0].split(".")[-1],
                        "qualified_name": tiling_hits[0],
                        "file_path": rel,
                        "start_line": line,
                        "end_line": line,
                    }
                )
                edges.append({"id": stable_id("E_", tdf_id, kvar_id), "type": "loads_into", "source": tdf_id, "target": kvar_id})
            elif derived_hits:
                # Kernel-local derived state (FagConstInfo etc.) — not serialized tiling members.
                source = "KernelDerivedField"
                ref = derived_hits[0]
            else:
                source = "KernelVariable"
                ref = cond
            # Prefer field name as determinant when enum compare is present.
            if eq_hits and source == "KernelVariable":
                source = "KernelDerivedField" if derived_hits else "TilingDataField"
                ref = eq_hits[0][0]
            elif eq_hits and source == "KernelDerivedField":
                ref = eq_hits[0][0]

            branch = _make_branch(
                name=f"runtime_{idx}",
                rel=rel,
                line=line,
                condition=cond,
                binding_time="runtime",
                determinant_source=source,
                determinant_ref=ref,
                domain=branch_literals or None,
            )
            if _looks_like_enum_field_compare(cond) and not eq_hits:
                unresolved.append(
                    {
                        "id": stable_id("UNRES_ENUM_", str(line), rel),
                        "kind": "enum_domain_unknown",
                        "message": "enum-like field compare missing concrete SCREAMING_SNAKE literals",
                        "file_path": rel,
                        "start_line": line,
                        "snippet": snippet(cond),
                        "target_node": branch["node"]["id"],
                    }
                )
            branches.append(branch)
            nodes.append(branch["node"])
            edges.append({"id": stable_id("E_", entry_id, branch["node"]["id"]), "type": "contains", "source": entry_id, "target": branch["node"]["id"]})

        for kind, regex in OP_MARKERS.items():
            if regex.search(text):
                node_id = stable_id("KOP_", kind, Path(rel).stem)
                nodes.append(
                    {
                        "id": node_id,
                        "layer": "kernel",
                        "node_type": kind if kind in {"Init", "Process", "CopyIn", "CopyOut", "Compute", "Sync"} else "ComputeOperation",
                        "name": kind,
                        "qualified_name": f"{rel}::{kind}",
                        "file_path": rel,
                        "start_line": 1,
                        "end_line": 1,
                    }
                )
                edges.append({"id": stable_id("E_", entry_id, node_id), "type": "contains", "source": entry_id, "target": node_id})

        for idx, match in enumerate(LOOP_RE.finditer(text)):
            header = " ".join(match.group(1).split())
            if len(header) > 160:
                continue
            line = text.count("\n", 0, match.start()) + 1
            loop_kind = "tail" if "tail" in header.lower() else "main"
            node_id = stable_id("KLOOP_", loop_kind, str(line))
            nodes.append(
                {
                    "id": node_id,
                    "layer": "kernel",
                    "node_type": "Loop",
                    "name": f"{loop_kind}_loop",
                    "qualified_name": f"{rel}::loop@{line}",
                    "file_path": rel,
                    "start_line": line,
                    "end_line": line,
                    "loop_kind": loop_kind,
                    "condition": header,
                }
            )
            edges.append({"id": stable_id("E_", entry_id, node_id), "type": "contains", "source": entry_id, "target": node_id})

    # Resolve full declared domains against kernel branch hits; emit/merge KVAR nodes.
    enum_fields_resolved: set[str] = set()
    for fld, usage in sorted(field_usage.items()):
        declared = resolve_declared_domain(usage.branch_literals, declared_domains)
        usage.declared = declared
        payload = build_field_domain_payload(usage)
        if not payload["domain"]:
            continue
        enum_fields_resolved.add(fld)
        kvar_id = stable_id("KVAR_", fld)
        nodes.append(
            {
                "id": kvar_id,
                "layer": "kernel",
                "node_type": "KernelVariable",
                "name": fld,
                "qualified_name": fld,
                "file_path": (declared.file_path if declared else ""),
                "start_line": (declared.start_line if declared else 0),
                "end_line": (declared.start_line if declared else 0),
                "binding_time": "runtime",
                "determinant_source": "TilingDataField" if fld in loaded_fields else "KernelDerivedField",
                **payload,
            }
        )
        if fld in loaded_fields or declared is not None:
            tdf_id = stable_id("TDF_", fld)
            nodes.append(
                {
                    "id": tdf_id,
                    "layer": "bridge",
                    "node_type": "TilingDataField",
                    "name": fld,
                    "qualified_name": fld,
                    "file_path": "",
                    "start_line": 0,
                    "end_line": 0,
                }
            )
            edges.append(
                {
                    "id": stable_id("E_", tdf_id, kvar_id),
                    "type": "loads_into",
                    "source": tdf_id,
                    "target": kvar_id,
                }
            )

    # Enrich earlier per-line KVAR stubs that share the same field id.
    enriched = {stable_id("KVAR_", f): f for f in enum_fields_resolved}
    for node in nodes:
        fld = enriched.get(str(node.get("id")))
        if not fld:
            continue
        usage = field_usage[fld]
        node.update(build_field_domain_payload(usage))

    nodes.append({"id": "KOUT_OUTPUT", "layer": "kernel", "node_type": "Output", "name": "Output", "qualified_name": "Output", "file_path": "", "start_line": 0, "end_line": 0})
    edges.append({"id": "E_ENTRY_TO_OUTPUT", "type": "writes_output", "source": entry_id, "target": "KOUT_OUTPUT"})

    return {
        "version": 1,
        "op_name": op_name,
        "architecture": architecture,
        "layer": "kernel",
        "nodes": _dedupe_nodes(nodes),
        "edges": _dedupe_edges(edges),
        "branches": [
            {
                "id": b["node"]["id"],
                "binding_time": b["node"].get("binding_time"),
                "determinant_source": b["node"].get("determinant_source"),
                "determinant_ref": b["node"].get("determinant_ref"),
                "condition": b["node"].get("condition"),
                "domain": b["node"].get("domain"),
                "file_path": b["node"].get("file_path"),
                "start_line": b["node"].get("start_line"),
            }
            for b in branches
        ],
        "declared_enum_domains": [
            {
                "kind": d.kind,
                "type_name": d.type_name,
                "names": d.names,
                "entries": [{"name": e.name, "value": e.value} for e in d.entries],
                "file_path": d.file_path,
                "start_line": d.start_line,
            }
            for d in declared_domains
        ],
        "loaded_tiling_fields": sorted(loaded_fields | enum_fields_resolved),
        "unresolved": unresolved,
    }


def collect_declared_domains(files: list[Path]) -> list[DeclaredDomain]:
    domains: list[DeclaredDomain] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for path in files:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.as_posix()
        for domain in parse_enum_class_domains(text, rel) + parse_constexpr_block_domains(text, rel):
            key = (domain.type_name, tuple(domain.names))
            if key in seen:
                continue
            seen.add(key)
            domains.append(domain)
    return domains


def parse_enum_class_domains(text: str, file_path: str = "") -> list[DeclaredDomain]:
    out: list[DeclaredDomain] = []
    for match in ENUM_CLASS_RE.finditer(text):
        type_name = match.group(1)
        body = match.group(2)
        entries: list[EnumEntry] = []
        next_value = 0
        for mem in ENUM_MEMBER_RE.finditer(body):
            name = mem.group(1)
            if name in {"class", "struct", "enum"}:
                continue
            if mem.group(2) is not None:
                next_value = int(mem.group(2))
            entries.append(EnumEntry(name=name, value=next_value))
            next_value += 1
        if len(entries) < 2:
            continue
        line = text.count("\n", 0, match.start()) + 1
        out.append(
            DeclaredDomain(
                kind="enum_class",
                type_name=type_name,
                entries=entries,
                file_path=file_path,
                start_line=line,
            )
        )
    return out


def parse_constexpr_block_domains(text: str, file_path: str = "") -> list[DeclaredDomain]:
    """Group consecutive same-type constexpr NAME = N into enum-like domains."""
    matches = list(CONSTEXPR_INT_RE.finditer(text))
    if not matches:
        return []
    out: list[DeclaredDomain] = []
    i = 0
    while i < len(matches):
        ctype = matches[i].group(1)
        run = [matches[i]]
        j = i + 1
        while j < len(matches):
            prev_end = matches[j - 1].end()
            cur_start = matches[j].start()
            between = text[prev_end:cur_start]
            # Allow blank lines / comments; break on other code.
            if re.search(r"[^\s/#*]", between):
                break
            if matches[j].group(1) != ctype:
                break
            run.append(matches[j])
            j += 1
        entries = [EnumEntry(name=m.group(2), value=int(m.group(3))) for m in run]
        if _is_enum_like_constexpr_block(entries):
            line = text.count("\n", 0, run[0].start()) + 1
            # Synthetic type name from shared prefix or first/last token.
            type_name = _infer_block_type_name(entries)
            out.append(
                DeclaredDomain(
                    kind="constexpr_block",
                    type_name=type_name,
                    entries=entries,
                    file_path=file_path,
                    start_line=line,
                )
            )
        i = j if j > i else i + 1
    return out


def extract_field_enum_comparisons(cond: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for match in FIELD_EQ_ENUM_RE.finditer(cond):
        fld = match.group(1)
        lit = match.group(3)
        if not _is_screaming_snake(lit):
            continue
        # Skip template/bool style identifiers used as fields.
        if fld.startswith("IS_") or fld.startswith("HAS_"):
            continue
        hits.append((fld, lit))
    return hits


def resolve_declared_domain(hit_literals: set[str], catalogs: list[DeclaredDomain]) -> DeclaredDomain | None:
    if not hit_literals:
        return None
    best: DeclaredDomain | None = None
    best_key: tuple[int, int] = (-1, -1)
    for cat in catalogs:
        overlap = len(hit_literals & cat.name_set)
        if overlap == 0:
            continue
        # Prefer more overlap, then larger declared domain (fuller enum).
        key = (overlap, len(cat.entries))
        if key > best_key:
            best_key = key
            best = cat
    return best


def build_field_domain_payload(usage: FieldEnumUsage) -> dict[str, Any]:
    declared = usage.declared
    if declared is not None:
        full_names = declared.names
        entries = declared.entries
        source = declared.kind
        type_name = declared.type_name
    else:
        full_names = sorted(usage.branch_literals)
        entries = [EnumEntry(name=n) for n in full_names]
        source = "branch_literals_only"
        type_name = ""

    with_branch = sorted(n for n in full_names if n in usage.branch_literals)
    without_branch = sorted(n for n in full_names if n not in usage.branch_literals)
    return {
        "domain": full_names,
        "domain_with_kernel_branch": with_branch,
        "domain_without_kernel_branch": without_branch,
        "domain_entries": [{"name": e.name, "value": e.value, "has_kernel_branch": e.name in usage.branch_literals} for e in entries],
        "domain_source": source,
        "domain_type_name": type_name or None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract kernel subgraph with compile/runtime branch classification")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--architecture", default="arch35")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    payload = extract_kernel_subgraph(repo_root, op_name, architecture=args.architecture)
    if args.write:
        write_yaml(existing_operator_root(repo_root, op_name) / "ir" / "kernel_subgraph.yaml", payload)
    print(f"kernel nodes={len(payload['nodes'])} branches={len(payload['branches'])} unresolved={len(payload['unresolved'])}")
    return 0


def _make_branch(*, name: str, rel: str, line: int, condition: str, binding_time: str, determinant_source: str, determinant_ref: str, domain: list[Any] | None = None) -> dict[str, Any]:
    node_id = stable_id("KBR_", name, str(line))
    return {
        "node": {
            "id": node_id,
            "layer": "kernel",
            "node_type": "KernelBranch",
            "name": name,
            "qualified_name": f"{rel}::{name}",
            "file_path": rel,
            "start_line": line,
            "end_line": line,
            "condition": condition,
            "binding_time": binding_time,
            "determinant_source": determinant_source,
            "determinant_ref": determinant_ref,
            "domain": domain,
        }
    }


def _bool_domain_from_cond(cond: str) -> list[Any]:
    if any(tok in cond for tok in ("true", "false", "ENABLE", "DISABLE", "IS_")):
        return [False, True]
    return None  # type: ignore[return-value]


def _is_screaming_snake(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_]*", name)) and ("_" in name or len(name) >= 3)


def _looks_like_enum_field_compare(cond: str) -> bool:
    # Heuristic: camelCase/snake field compared with something that is not a number/bool.
    return bool(re.search(r"\b[A-Za-z_]\w*(?:Mode|Type|Kind|Flag|Layout)\b\s*==", cond))


def _is_enum_like_constexpr_block(entries: list[EnumEntry]) -> bool:
    if len(entries) < 2:
        return False
    values = [e.value for e in entries if e.value is not None]
    if len(values) != len(entries):
        return False
    if len(set(values)) != len(values):
        return False
    vmin, vmax = min(values), max(values)
    # Enum-like: starts near 0 and stays in a small dense range.
    if vmin > 1:
        return False
    if vmax > max(32, len(entries) * 3):
        return False
    # Reject sparse bitmasks / sizes (large average gap).
    span = vmax - vmin
    if span > len(entries) * 2:
        return False
    return True


def _infer_block_type_name(entries: list[EnumEntry]) -> str:
    names = [e.name for e in entries]
    if not names:
        return "ConstexprEnum"
    # Longest common prefix ending with underscore, else first token family.
    prefix = names[0]
    for name in names[1:]:
        while prefix and not name.startswith(prefix):
            prefix = prefix[:-1]
    prefix = prefix.rstrip("_")
    if len(prefix) >= 3:
        return prefix
    return f"Constexpr_{names[0]}"


def _enum_declaration_files(repo_root: Path, op_name: str, architecture: str) -> list[Path]:
    patterns = [
        f"op_kernel/{architecture}/**/*.h",
        f"op_kernel/{architecture}/**/*.hpp",
        f"op_host/{architecture}/**/*.h",
        f"op_host/{architecture}/**/*.hpp",
        f"{op_name}/op_kernel/{architecture}/**/*.h",
        f"{op_name}/op_kernel/{architecture}/**/*.hpp",
        f"{op_name}/op_host/{architecture}/**/*.h",
        f"{op_name}/op_host/{architecture}/**/*.hpp",
    ]
    uniq: dict[str, Path] = {}
    for pattern in patterns:
        for path in repo_root.glob(pattern):
            if path.is_file():
                uniq[path.resolve().as_posix()] = path
    return sorted(uniq.values(), key=lambda p: p.as_posix())[:120]


def _kernel_files(repo_root: Path, op_name: str, architecture: str, selected: dict[str, Any] | None) -> list[Path]:
    files: list[Path] = []
    if selected and selected.get("file_path"):
        rel = str(selected["file_path"]).replace("\\", "/").lstrip("./")
        for cand in (repo_root / rel, repo_root / op_name / rel):
            if cand.is_file():
                files.append(cand)
                break
    # Support both layouts:
    # - repo_root == operator package  -> op_kernel/arch35/...
    # - repo_root == workspace parent  -> <op>/op_kernel/arch35/...
    patterns = [
        f"op_kernel/{architecture}/**/*kernel*.h",
        f"op_kernel/{architecture}/**/*kernel*.cpp",
        f"op_kernel/{architecture}/**/*entry*.h",
        f"op_kernel/{architecture}/**/*common*.h",
        f"op_kernel/{architecture}/*.h",
        f"{op_name}/op_kernel/{architecture}/**/*kernel*.h",
        f"{op_name}/op_kernel/{architecture}/**/*kernel*.cpp",
        f"{op_name}/op_kernel/{architecture}/**/*entry*.h",
        f"{op_name}/op_kernel/{architecture}/**/*common*.h",
        f"{op_name}/op_kernel/{architecture}/*.h",
    ]
    for pattern in patterns:
        files.extend(repo_root.glob(pattern))
    # unique; prefer entry/kernel_base/kernel headers, skip pure utils noise last
    uniq: dict[str, Path] = {}
    for path in files:
        if not path.is_file():
            continue
        uniq[path.resolve().as_posix()] = path

    def rank(p: Path) -> tuple[int, int, str]:
        name = p.name.lower()
        if "entry" in name:
            return (0, 0, p.as_posix())
        if name.endswith("kernel.h") or name.endswith("kernel_base.h"):
            return (0, 1, p.as_posix())
        if "kernel" in name:
            return (1, 0, p.as_posix())
        if "common" in name:
            return (2, 0, p.as_posix())
        return (3, 0, p.as_posix())

    ranked = sorted(uniq.values(), key=rank)
    # Allow enough headers for branch extraction (entry + base + a few modules).
    return ranked[:40]


def _dedupe_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for node in nodes:
        nid = str(node.get("id"))
        prev = out.get(nid)
        if prev is None:
            out[nid] = node
            continue
        # Prefer node with richer domain payload.
        if node.get("domain_entries") and not prev.get("domain_entries"):
            out[nid] = {**prev, **node}
        elif node.get("domain") and not prev.get("domain"):
            out[nid] = {**prev, **node}
        else:
            # Keep first; merge missing keys from later.
            for key, value in node.items():
                if key not in prev or prev.get(key) in (None, "", [], {}):
                    prev[key] = value
    return list(out.values())


def _dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for edge in edges:
        out[str(edge.get("id"))] = edge
    return list(out.values())


if __name__ == "__main__":
    raise SystemExit(main())
