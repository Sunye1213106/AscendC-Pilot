# -*- coding: utf-8 -*-
"""Explicit instantiation harness for kernel if-constexpr folding.

Two things make the generated TU actually compilable:

* the entry signature (19 NTTPs, 36 `__gm__ uint8_t *` parameters) is parsed
  out of the kernel source rather than approximated, and
* the instantiation includes the defining TU, so clang sees the template
  definition and folds `if constexpr` for the chosen parameter values.

Full expansion of the FAG arch35 schema is 8705 legal instances (x3 dtypes =
26115 TUs), which is not a practical compile matrix. `sample_instances`
selects a pairwise-covering subset instead.
"""
from __future__ import annotations

from uo_init.paths import require_architecture
import random
import re
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

from uo_init.tpl_dsl import TplSchema, expand_legal_instances, parse_file

BOOL_TRUE = {"1", "true", "True", "TRUE"}


@dataclass
class EntrySignature:
    name: str
    template_params: list[tuple[str, str]] = field(default_factory=list)  # (type, name)
    param_types: list[str] = field(default_factory=list)
    source: str = ""

    @property
    def arity(self) -> int:
        return len(self.param_types)


@dataclass
class HarnessJob:
    values: dict[str, str]
    dtype: str
    source: str


TEMPLATE_ENTRY_RE = re.compile(
    r"template\s*<(?P<tparams>[^>]*)>\s*"
    r"(?P<quals>(?:__global__|__aicore__|inline|static|\s)*)"
    r"void\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)",
    re.DOTALL,
)


def _split_top(src: str, sep: str = ",") -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in src:
        if ch in "<([":
            depth += 1
        elif ch in ">)]":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return [p for p in out if p]


def parse_entry_signature(path: str | Path, name: str | None = None) -> EntrySignature:
    """Read the real template entry point out of the kernel TU."""
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    for m in TEMPLATE_ENTRY_RE.finditer(src):
        if name and m.group("name") != name:
            continue
        tparams: list[tuple[str, str]] = []
        for decl in _split_top(m.group("tparams")):
            bits = decl.split()
            if len(bits) >= 2:
                tparams.append((" ".join(bits[:-1]), bits[-1]))
        ptypes: list[str] = []
        for decl in _split_top(m.group("params")):
            # keep the type, drop the parameter name
            ptypes.append(re.sub(r"\s*\b\w+\s*$", "", decl).strip() or decl.strip())
        return EntrySignature(
            name=m.group("name"),
            template_params=tparams,
            param_types=ptypes,
            source=str(path).replace("\\", "/"),
        )
    raise ValueError(f"no template entry point found in {path}")


def _render_value(tparam_type: str, dim_kind: str, value: str) -> str:
    t = tparam_type.replace("typename", "").strip()
    if t == "bool" or dim_kind == "BOOL":
        return "true" if str(value) in BOOL_TRUE else "false"
    if dim_kind in ("DTYPE", "FORMAT") and not str(value).lstrip("-").isdigit():
        return str(value)
    if t and t != "bool" and str(value).lstrip("-").isdigit():
        return f"static_cast<{t}>({value})"
    return str(value)


def _ordered_values(schema: TplSchema, inst: dict[str, str]) -> list[str]:
    out = []
    for d in schema.dims:
        if d.name not in inst:
            dom = d.value_domain
            out.append(dom[0] if dom else "0")
        else:
            out.append(inst[d.name])
    return out


def emit_instantiation(
    schema: TplSchema,
    inst: dict[str, str],
    *,
    signature: EntrySignature | None = None,
    entry: str = "",
    dtype: str = "DT_FLOAT16",
    include: str | None = None,
) -> str:
    """Emit a self-contained TU that forces one template instance to be compiled."""
    vals = _ordered_values(schema, inst)
    if signature is None:
        if not entry:
            raise ValueError("entry or signature is required for emit_instantiation")
        rendered = [
            _render_value("", d.kind, v) for d, v in zip(schema.dims, vals)
        ]
        param_list = ", ".join(["__gm__ uint8_t *"] * 36)
        include = include or ""
    else:
        types = [t for t, _ in signature.template_params]
        rendered = [
            _render_value(types[i] if i < len(types) else "", d.kind, v)
            for i, (d, v) in enumerate(zip(schema.dims, vals))
        ]
        param_list = ", ".join(signature.param_types)
        entry = signature.name
        include = include if include is not None else signature.source

    args = ", ".join(rendered)
    lines = [
        f"// dtype_variant={dtype}",
        f"// instance={inst}",
    ]
    from uo_init.build_context import dtype_macro_for_source

    macro = dtype_macro_for_source(include) if include else None
    if macro:
        lines.append(f"#define {macro} {dtype}")
    if include:
        lines.append(f'#include "{include}"')
    lines += [
        "",
        f"template __global__ __aicore__ void {entry}<{args}>(",
        f"    {param_list});",
        "",
    ]
    return "\n".join(lines)


def count_legal_instances(schema: TplSchema) -> int:
    return len(expand_legal_instances(schema))


def _pairs(inst: dict[str, str], dims: list[str]) -> frozenset:
    present = [(d, inst[d]) for d in dims if d in inst]
    return frozenset(combinations(sorted(present), 2))


def sample_instances(
    schema: TplSchema,
    *,
    strategy: str = "pairwise",
    seed: int = 0,
    candidate_pool: int = 400,
    limit: int | None = None,
) -> list[dict[str, str]]:
    """Pick a small legal subset. `pairwise` covers every legal value pair."""
    legal = expand_legal_instances(schema)
    if strategy == "all":
        return legal[:limit] if limit else legal
    dims = [d.name for d in schema.dims]

    if strategy == "per_value":
        chosen: list[dict[str, str]] = []
        covered: set[tuple[str, str]] = set()
        for inst in legal:
            new = {(d, v) for d, v in inst.items()} - covered
            if new:
                covered |= new
                chosen.append(inst)
        return chosen[:limit] if limit else chosen

    if strategy != "pairwise":
        raise ValueError(f"unknown strategy {strategy!r}")

    rng = random.Random(seed)
    pair_sets = [(_pairs(inst, dims), inst) for inst in legal]
    universe: set = set()
    for ps, _ in pair_sets:
        universe |= ps
    uncovered = set(universe)
    chosen = []
    while uncovered:
        pool = pair_sets if len(pair_sets) <= candidate_pool else rng.sample(pair_sets, candidate_pool)
        best = max(pool, key=lambda item: len(item[0] & uncovered))
        gain = len(best[0] & uncovered)
        if gain == 0:
            # the sampled pool added nothing; fall back to a full scan once
            best = max(pair_sets, key=lambda item: len(item[0] & uncovered))
            if not (best[0] & uncovered):
                break
        uncovered -= best[0]
        chosen.append(best[1])
        if limit and len(chosen) >= limit:
            break
    return chosen


def pairwise_coverage(schema: TplSchema, chosen: list[dict[str, str]]) -> float:
    dims = [d.name for d in schema.dims]
    legal = expand_legal_instances(schema)
    universe: set = set()
    for inst in legal:
        universe |= _pairs(inst, dims)
    got: set = set()
    for inst in chosen:
        got |= _pairs(inst, dims)
    return (len(got & universe) / len(universe)) if universe else 1.0


def build_harness_jobs(
    key_hdr: str | Path,
    *,
    dtypes: list[str] | None = None,
    limit: int | None = None,
    strategy: str = "pairwise",
    entry_source: str | Path | None = None,
    entry_name: str,
) -> list[HarnessJob]:
    if not entry_name:
        raise ValueError("entry_name is required (use OpSpec.op_snake)")
    schema = parse_file(key_hdr)
    insts = sample_instances(schema, strategy=strategy, limit=limit)
    signature = (
        parse_entry_signature(entry_source, entry_name) if entry_source else None
    )
    dtypes = dtypes or ["DT_FLOAT16"]
    jobs: list[HarnessJob] = []
    for inst in insts:
        for dt in dtypes:
            jobs.append(
                HarnessJob(
                    values=inst,
                    dtype=dt,
                    source=emit_instantiation(schema, inst, dtype=dt, signature=signature),
                )
            )
    return jobs


def verify_harness_tu(path: str | Path, ctx, *, op_needle: str) -> list[tuple[str, str]]:
    """Parse a generated TU and return errors attributed to operator sources.

    An empty list means the emitted instantiation matched the real entry point:
    wrong arity or wrong NTTP types would surface here as errors in the harness
    file. Diagnostics from CANN's own headers are excluded, since they are
    present in the untouched kernel TU as well.

    ``op_needle`` must come from :attr:`OpSpec.op_needle` (or equivalent) —
    never hardcode an operator name here.
    """
    from clang import cindex

    if not op_needle:
        raise ValueError("op_needle is required (use OpSpec.op_needle)")
    from uo_init.diag_scope import diagnostic_in_operator

    index = cindex.Index.create()  # must outlive the TU
    tu = index.parse(
        str(path), args=ctx.kernel_args(dtype_variant=None, source_path=path)
    )
    out: list[tuple[str, str]] = []
    op_dir = str(getattr(ctx, "op_dir", "") or "")
    for d in tu.diagnostics:
        if d.severity < 3:
            continue
        fname = d.location.file.name.replace("\\", "/") if d.location.file else ""
        if diagnostic_in_operator(fname, op_dir, str(path)):
            out.append((d.spelling, fname))
    return out


CLANG_SEARCH = [
    "clang",
    r"C:\ProgramData\miniconda3\envs\uoclang\Library\bin\clang.exe",
    "/usr/bin/clang",
]


def find_clang(explicit: str | None = None) -> str | None:
    """Locate a clang driver. libclang alone cannot produce the folded AST."""
    import os
    import shutil

    env = [
        os.environ.get("CLANG_EXE"),
        os.environ.get("UO_CLANG"),
        (str(Path(os.environ["LLVM_BIN"]) / "clang.exe") if os.environ.get("LLVM_BIN") else None),
        (str(Path(os.environ["LLVM_HOME"]) / "bin" / "clang.exe") if os.environ.get("LLVM_HOME") else None),
    ]
    common = [
        r"C:\Program Files\LLVM\bin\clang.exe",
        r"C:\Program Files (x86)\LLVM\bin\clang.exe",
        r"C:\msys64\clang64\bin\clang.exe",
        r"C:\msys64\ucrt64\bin\clang.exe",
    ]
    for cand in ([explicit] if explicit else []) + env + common + CLANG_SEARCH:
        if not cand:
            continue
        found = shutil.which(cand) or (cand if Path(cand).exists() else None)
        if found:
            return found
    return None


def ast_dump_command(
    path: str | Path,
    ctx,
    *,
    clang_exe: str = "clang",
    entry: str,
) -> list[str]:
    """Command that makes `if constexpr` folding observable.

    libclang's cursor API does not expose explicit template instantiations: the
    generated TU parses, but `tu.cursor.get_children()` still shows only the
    FUNCTION_TEMPLATE pattern and never the specialisation. Reading the folded
    body therefore requires a textual AST dump from a clang driver binary.
    """
    if not entry:
        raise ValueError("entry (kernel function name) is required")
    return [
        clang_exe,
        "-fsyntax-only",
        "-Xclang",
        "-ast-dump",
        "-Xclang",
        f"-ast-dump-filter={entry}",
        *ctx.kernel_args(dtype_variant=None),
        str(path),
    ]


@dataclass
class FoldReport:
    instantiated: bool
    template_args: list[str] = field(default_factory=list)
    constexpr_ifs: int = 0
    discarded_branches: int = 0
    body_nodes: int = 0
    new_errors: list[str] = field(default_factory=list)


_TARG_RE = re.compile(r"TemplateArgument integral (\S+)")
_INDENT_RE = re.compile(r"^([|\- `]*)")
# Clang 18+ dumps specialisations as FunctionDecl … explicit_instantiation_*;
# older dumps used a bare `Function 0x…` node. DeclRefExpr also contains
# `Function 0x…` and must not be treated as the specialisation head.
_SPEC_OR_FUNC_RE = re.compile(
    r"\bFunctionDecl 0x[0-9a-f]+\b|(?<![A-Za-z])Function 0x[0-9a-f]+\b"
)


def _indent_of(line: str) -> int:
    return len(_INDENT_RE.match(line).group(1))


def _is_spec_head(line: str) -> bool:
    if "DeclRefExpr" in line:
        return False
    if "FunctionDecl" in line and "explicit_instantiation" in line:
        return True
    return bool(re.search(r"(?<![A-Za-z])Function 0x[0-9a-f]+\b", line))


def _specialisation_body(stdout: str) -> tuple[int, list[str]] | None:
    """Locate the explicit-instantiation body under a filtered -ast-dump."""
    lines = stdout.splitlines()
    start = next((i for i, l in enumerate(lines) if _TARG_RE.search(l)), None)
    if start is None:
        return None
    head = start
    while head >= 0 and not _is_spec_head(lines[head]):
        head -= 1
    if head < 0:
        return None
    base = _indent_of(lines[head])
    body: list[str] = []
    for l in lines[head + 1 :]:
        if (
            l.strip()
            and _indent_of(l) <= base
            and _SPEC_OR_FUNC_RE.search(l)
            and "DeclRefExpr" not in l
        ):
            break
        body.append(l)
    return head, body


def parse_fold_dump(stdout: str) -> FoldReport:
    """Extract the instantiated specialisation from a clang -ast-dump filter run."""
    found = _specialisation_body(stdout)
    if found is None:
        return FoldReport(instantiated=False)
    _, body = found
    targs = [m.group(1) for l in body for m in [_TARG_RE.search(l)] if m]
    if not targs:
        return FoldReport(instantiated=False)
    constexpr_ifs = sum(1 for l in body if "IfStmt" in l and "constexpr" in l)
    discarded = sum(1 for l in body if "<<<NULL>>>" in l)
    return FoldReport(
        instantiated=True,
        template_args=targs,
        constexpr_ifs=constexpr_ifs,
        discarded_branches=discarded,
        body_nodes=len(body),
    )


_CTRL_KIND_RE = re.compile(
    r"\b(IfStmt|SwitchStmt|ForStmt|WhileStmt|DoStmt|ConditionalOperator)\b"
)
_LINE_RE = re.compile(r"<[^>]*:(\d+):\d+")
_COND_HINT_RE = re.compile(
    r"\b(?:BinaryOperator|UnaryOperator|DeclRefExpr|IntegerLiteral|CXXBoolLiteralExpr)\b.*?'(.+?)'"
)


def parse_fold_controls(
    stdout: str,
    *,
    entry: str = "",
    file: str = "",
) -> list:
    """Pull folded control nodes out of a clang `-ast-dump` specialisation body.

    Returns :class:`~uo_init.clang_walk.CtrlNode` instances with `universe`
    already set so callers can mint `KBR_*` ids without a second pass.
    Discarded constexpr arms (`<<<NULL>>>`) are skipped — they never execute.
    """
    from uo_init.clang_walk import CtrlNode

    found = _specialisation_body(stdout)
    if found is None:
        return []
    _, body = found

    kind_map = {
        "IfStmt": "if",
        "SwitchStmt": "switch",
        "ForStmt": "for",
        "WhileStmt": "while",
        "DoStmt": "do",
        "ConditionalOperator": "ternary",
    }
    out: list[CtrlNode] = []
    for i, line in enumerate(body):
        m = _CTRL_KIND_RE.search(line)
        if not m:
            continue
        # A discarded constexpr arm has <<<NULL>>> under it at the next indent.
        indent = _indent_of(line)
        discarded = False
        for nxt in body[i + 1 : i + 8]:
            if _indent_of(nxt) <= indent and nxt.strip():
                break
            if "<<<NULL>>>" in nxt:
                discarded = True
                break
        if discarded:
            continue
        raw_kind = m.group(1)
        kind = kind_map.get(raw_kind, raw_kind.lower())
        if "constexpr" in line and kind == "if":
            kind = "if_constexpr"
        lm = _LINE_RE.search(line)
        line_no = int(lm.group(1)) if lm else 0
        # Best-effort condition text from the next few dump lines.
        cond = ""
        for nxt in body[i + 1 : i + 12]:
            if _indent_of(nxt) <= indent and nxt.strip() and i + 1 < len(body):
                if _CTRL_KIND_RE.search(nxt):
                    break
            hm = _COND_HINT_RE.search(nxt)
            if hm:
                cond = hm.group(1)
                break
        node = CtrlNode(
            id=f"{file}:{line_no}:0:{kind}:0",
            kind=kind,
            file=file or "<fold>",
            line=line_no,
            snippet=line.strip()[:120],
            condition=cond,
            function=entry,
            universe="PRODUCTION",
        )
        out.append(node)
    return out


@dataclass(frozen=True)
class MintedKernelBranch:
    """Stable `KBR_*` id plus the fold evidence that produced it."""

    id: str
    file: str
    line: int
    snippet: str = ""
    condition: str = ""
    function: str = ""
    kind: str = "if"
    dimensions: tuple[str, ...] = ()
    derived: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    dtype_variants: tuple[str, ...] = ()
    stage: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = {
            "id": self.id,
            "file": self.file,
            "line": self.line,
            "snippet": self.snippet,
            "condition": self.condition,
            "function": self.function,
            "kind": self.kind,
        }
        if self.dimensions:
            out["dimensions"] = list(self.dimensions)
        if self.derived:
            out["derived"] = list(self.derived)
        if self.symbols:
            out["symbols"] = list(self.symbols)
        if self.dtype_variants:
            out["dtype_variants"] = list(self.dtype_variants)
        if self.stage:
            out["stage"] = self.stage
        return out

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "MintedKernelBranch":
        return cls(
            id=str(row["id"]),
            file=str(row.get("file") or ""),
            line=int(row.get("line") or 0),
            snippet=str(row.get("snippet") or ""),
            condition=str(row.get("condition") or ""),
            function=str(row.get("function") or ""),
            kind=str(row.get("kind") or "if"),
            dimensions=tuple(str(x) for x in (row.get("dimensions") or [])),
            derived=tuple(str(x) for x in (row.get("derived") or [])),
            symbols=tuple(str(x) for x in (row.get("symbols") or [])),
            dtype_variants=tuple(str(x) for x in (row.get("dtype_variants") or [])),
            stage=str(row.get("stage") or ""),
        )


def mint_kernel_branches(
    controls: list,
    *,
    op_root: str = "",
    entry: str = "",
) -> list[MintedKernelBranch]:
    """Mint stable `KBR_*` ids for folded kernel controls (union-friendly)."""
    from uo_init.ids import branch_id as make_branch_id

    ordinals: dict[tuple[str, str, str], int] = {}
    out: list[MintedKernelBranch] = []
    for node in controls:
        key = (node.file, node.function or entry, node.condition or node.snippet)
        n = ordinals.get(key, 0)
        ordinals[key] = n + 1
        bid = make_branch_id(
            side="kernel",
            file=node.file,
            function=node.function or entry,
            guard=node.condition or node.snippet or node.kind,
            ordinal=n,
            root=op_root,
        )
        out.append(
            MintedKernelBranch(
                id=bid,
                file=str(node.file or ""),
                line=int(getattr(node, "line", 0) or 0),
                snippet=str(getattr(node, "snippet", "") or "")[:200],
                condition=str(getattr(node, "condition", "") or ""),
                function=str(node.function or entry or ""),
                kind=str(getattr(node, "kind", "if") or "if"),
            )
        )
    return out


def fold_report(
    path: str | Path,
    ctx,
    *,
    clang_exe: str | None = None,
    entry: str,
    baseline_errors: set[str] | None = None,
) -> FoldReport:
    """Compile a harness TU and report what the instantiation folded away."""
    import subprocess

    if not entry:
        raise ValueError("entry (kernel function name) is required")
    exe = find_clang(clang_exe)
    if exe is None:
        raise RuntimeError("no clang driver found; set clang_exe")
    cmd = ast_dump_command(path, ctx, clang_exe=exe, entry=entry)
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    rep = parse_fold_dump(proc.stdout)
    errs = {l for l in proc.stderr.splitlines() if ": error: " in l}
    rep.new_errors = sorted(errs - (baseline_errors or set()))
    return rep


def fold_controls(
    path: str | Path,
    ctx,
    *,
    clang_exe: str | None = None,
    entry: str,
    logical_file: str = "",
) -> list:
    """Run clang -ast-dump and return folded production control nodes.

    ``logical_file`` is the stable path used for `KBR_*` minting (kernel source),
    not the ephemeral harness TU path — otherwise pairwise jobs never union.

    When ``UO_FOLD_CACHE`` is enabled (default), results are keyed by harness
    source + kernel parse args + entry under ``uo/cache/fold/``.
    """
    import subprocess

    from uo_init import fold_cache

    if not entry:
        raise ValueError("entry (kernel function name) is required")
    exe = find_clang(clang_exe)
    if exe is None:
        raise RuntimeError("no clang driver found; set clang_exe")
    op_dir = getattr(ctx, "op_dir", None) or ""
    arch = require_architecture(getattr(ctx, "arch_dir", None))
    cache_key = ""
    if fold_cache.cache_enabled():
        try:
            cache_key = fold_cache.signature_for_path(
                path,
                ctx,
                entry=entry,
                logical_file=logical_file or entry,
                clang_exe=exe,
            )
            hit = fold_cache.load_fold_controls(
                cache_key, op_dir=op_dir or None, arch=arch
            )
            if hit is not None:
                return hit
        except Exception:  # noqa: BLE001
            cache_key = ""
    cmd = ast_dump_command(path, ctx, clang_exe=exe, entry=entry)
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    controls = parse_fold_controls(
        proc.stdout,
        entry=entry,
        file=logical_file or entry,
    )
    if cache_key:
        try:
            fold_cache.store_fold_controls(
                cache_key, controls, op_dir=op_dir or None, arch=arch
            )
        except Exception:  # noqa: BLE001
            pass
    return controls


def baseline_error_set(path: str | Path, ctx, *, clang_exe: str | None = None) -> set[str]:
    """Errors the untouched kernel TU already produces, to subtract from harness runs."""
    import subprocess

    exe = find_clang(clang_exe)
    if exe is None:
        raise RuntimeError("no clang driver found; set clang_exe")
    cmd = [exe, "-fsyntax-only", *ctx.kernel_args(dtype_variant=None), str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    return {l for l in proc.stderr.splitlines() if ": error: " in l}


def write_harness_dir(jobs: list[HarnessJob], out_dir: str | Path) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, job in enumerate(jobs):
        p = out_dir / f"harness_{i:04d}_{job.dtype}.cpp"
        p.write_text(job.source, encoding="utf-8")
        paths.append(p)
    return paths


def union_mint_kernel_branches(
    control_batches: Iterable[list],
    *,
    op_root: str = "",
    entry: str = "",
) -> list[MintedKernelBranch]:
    """Mint `KBR_*` per batch then union — same folded guard keeps one id.

    Pairwise specialisations discard different constexpr arms; unioning the
    surviving controls across jobs recovers the production kernel branch set
    without requiring a full Cartesian template sweep.
    """
    seen: set[str] = set()
    ordered: list[MintedKernelBranch] = []
    for batch in control_batches:
        for item in mint_kernel_branches(batch, op_root=op_root, entry=entry):
            if item.id not in seen:
                seen.add(item.id)
                ordered.append(item)
    return ordered


def _fold_one(
    path: Path,
    ctx,
    clang_exe: str | None,
    entry: str,
    logical_file: str,
) -> list:
    return fold_controls(
        path, ctx, clang_exe=clang_exe, entry=entry, logical_file=logical_file
    )


def collect_folded_kernel_branches(
    jobs: list[HarnessJob],
    ctx,
    *,
    entry: str,
    work_dir: str | Path,
    op_root: str = "",
    clang_exe: str | None = None,
    workers: int = 4,
    logical_file: str = "",
) -> list[MintedKernelBranch]:
    """Write harness TUs, fold with clang -ast-dump (parallel), union `KBR_*`.

    Parallelism is process-I/O bound (subprocess clang). Accuracy is unchanged:
    each job still gets a full dump; we only overlap wall time.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if not entry:
        raise ValueError("entry (kernel function name) is required")
    paths = write_harness_dir(jobs, work_dir)
    if not paths:
        return []
    stable = logical_file or entry
    n_workers = max(1, min(workers, len(paths)))
    batches: list[list] = [[] for _ in paths]
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futs = {
            pool.submit(_fold_one, p, ctx, clang_exe, entry, stable): i
            for i, p in enumerate(paths)
        }
        for fut in as_completed(futs):
            batches[futs[fut]] = fut.result()
    return union_mint_kernel_branches(batches, op_root=op_root, entry=entry)
