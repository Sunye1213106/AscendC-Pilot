"""Bind atomic predicates from branch conditions onto CSV/KEY/TDF/KVAR.

Per-operator token/alias tables are NOT hardcoded here. They come from:
  1. UO `kernel/variables.yaml` set_by / classification
  2. Weak KEY_id heuristics from `tiling/key_space.yaml`
  3. uo-query merge → `realization/binding_lexicon.yaml` (LLM + evidence; tg-csv-contract 仅 thin inventory 补洞)
"""

from __future__ import annotations

import re
from typing import Any

from .binding_lexicon import lexicon_from_key_space, merge_lexicons, normalize_lexicon

CSV_PREFIX = "VAR_CSV_"

# Ascend common dtype literals (cross-op). Prefer lexicon overrides when present.
DTYPE_VALUES = {
    "DT_FLOAT16": 0,
    "DT_BF16": 1,
    "DT_FLOAT": 2,
    "DT_FLOAT32": 2,
}

# Cross-op foldable bool/arith literals only — not operator macros.
ARITH_CONSTANTS: dict[str, int] = {
    "NUM_TWO": 2,
    "NUM_ONE": 1,
    "NUM_ZERO": 0,
    "true": 1,
    "false": 0,
    "TRUE": 1,
    "FALSE": 0,
}


def csv_var(column: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in str(column)).strip("_")
    return f"{CSV_PREFIX}{safe}"


# Generic Ascend C loop / block locals (not product-specific names).
LOOP_LOCAL_PATTERNS = (
    re.compile(r"(?i)\btaskid\b"),
    re.compile(r"(?i)\bislastloop\b"),
    re.compile(r"(?i)\bneedsync"),
    re.compile(r"(?i)\bactual[mn]\b"),
    re.compile(r"(?i)\bloop\b"),
    re.compile(r"(?i)\bloopid\b"),
    re.compile(r"(?i)\bloop_id\b"),
    re.compile(r"(?i)\bblockid\b"),
    re.compile(r"(?i)\bblock_id\b"),
    re.compile(r"(?i)\bblockidx\b"),
    re.compile(r"(?i)\bcblockidx\b"),
    re.compile(r"(?i)\bcoreidx\b"),
    re.compile(r"(?i)\bprevruninfo\b"),
    re.compile(r"(?i)\bruninfo\b"),
    re.compile(r"(?i)\bisnexts2"),
    re.compile(r"(?i)\bislasts1"),
    re.compile(r"(?i)\b(vblockidx|vsubblockidx|bidx|nloops|pingpangidx)\b"),
    re.compile(r"(?i)\b(coordinate|coordinateinfo)\b"),
    re.compile(r"(?i)\b(globalidx|s2idxtmp|s2outertmp|halfn1)\b"),
    re.compile(r"(?i)\b(core_id|round_id|batchid)\b"),
)

PLATFORM_MACRO_PATTERNS = (
    re.compile(r"(?i)ASC_DEVKIT"),
    re.compile(r"(?i)_H_\s*$"),
    re.compile(r"(?i)^[A-Z0-9_]+_H_$"),
    re.compile(r"(?i)\b__\w+__\b"),
)

OUT_OF_SCOPE_RUNTIME_NAME_PATTERNS = (
    *LOOP_LOCAL_PATTERNS,
    re.compile(r"(?i)g_?coretype"),
    re.compile(r"(?i)coretype"),
    re.compile(r"(?i)blockends"),
    re.compile(r"(?i)mm_idx"),
    re.compile(r"(?i)ASC_DEVKIT"),
)

# Deprecated empty shims for old imports — always empty; use BindContext.lexicon.
TOKEN_KEY_VALUE: dict[str, tuple[str, int]] = {}
EXTRA_KEY_TOKENS: dict[str, tuple[str, int]] = {}
CSV_FIELD_ALIASES: dict[str, tuple[str, Any]] = {}
UNBOUND_TEMPLATE_NAMES: set[str] = set()


def is_loop_local_text(text: str) -> bool:
    return any(p.search(text or "") for p in LOOP_LOCAL_PATTERNS)


def is_platform_macro_text(text: str) -> bool:
    return any(p.search(text or "") for p in PLATFORM_MACRO_PATTERNS)


def is_out_of_scope_runtime_entity(*, name: str = "", condition: str = "", determinant_source: str = "") -> str | None:
    """Return LOOP_LOCAL / PLATFORM_MACRO if entity must be dropped from CSV runtime coverage."""
    blob = " ".join([name, condition, determinant_source])
    if is_loop_local_text(blob) or any(p.search(name or "") for p in OUT_OF_SCOPE_RUNTIME_NAME_PATTERNS):
        if is_platform_macro_text(blob) or is_platform_macro_text(name):
            return "PLATFORM_MACRO"
        if is_loop_local_text(blob) or any(p.search(name or "") for p in LOOP_LOCAL_PATTERNS):
            return "LOOP_LOCAL"
        if any(p.search(name or "") for p in OUT_OF_SCOPE_RUNTIME_NAME_PATTERNS):
            return "PLATFORM_MACRO" if re.search(r"(?i)coretype|ASC_DEVKIT", name or "") else "LOOP_LOCAL"
    if is_platform_macro_text(blob) or is_platform_macro_text(condition) or is_platform_macro_text(name):
        return "PLATFORM_MACRO"
    if str(determinant_source or "") == "CompileMacro" and (
        str(condition or "").endswith("_H_") or "ASC_DEVKIT" in str(condition or "").upper()
    ):
        return "PLATFORM_MACRO"
    return None


class BindContext:
    """KB + lexicon indexes used while binding atoms."""

    def __init__(
        self,
        snapshot: dict[str, Any] | None = None,
        *,
        csv_columns: list[str] | None = None,
        lexicon: dict[str, Any] | None = None,
        op_name: str = "",
        shape_closure: set[str] | None = None,
    ) -> None:
        files = (snapshot or {}).get("files") if isinstance((snapshot or {}).get("files"), dict) else {}
        self.csv_columns = {str(c) for c in (csv_columns or [])}
        self.op_name = str(op_name or "")
        self.missing_tdf_producers: set[str] = set()
        self.kvar_by_name: dict[str, dict[str, Any]] = {}
        self.enum_literal_values: dict[str, Any] = {}
        self.free_kvar_specs: dict[str, dict[str, Any]] = {}
        self.csv_field_aliases: dict[str, tuple[str, Any]] = {}
        self.arith_constants: dict[str, int] = dict(ARITH_CONSTANTS)
        self.key_tokens: dict[str, tuple[str, int]] = {}
        self.shape_closure: set[str] = {str(x) for x in (shape_closure or []) if x}
        self.shape_alias_to_var: dict[str, str] = {}

        key_space = _as_dict(files.get("tiling/key_space.yaml"))
        boot = lexicon_from_key_space(key_space)
        self.lexicon = normalize_lexicon(merge_lexicons(boot, lexicon))
        for name, spec in (self.lexicon.get("key_tokens") or {}).items():
            if isinstance(spec, dict) and spec.get("var"):
                self.key_tokens[str(name).upper()] = (str(spec["var"]), int(spec.get("true_value", 1)))
        for name, spec in (self.lexicon.get("csv_field_aliases") or {}).items():
            if isinstance(spec, dict) and spec.get("column"):
                self.csv_field_aliases[str(name).lower()] = (str(spec["column"]), spec.get("value"))
        self.arith_constants.update(self.lexicon.get("arith_constants") or {})

        if self.op_name:
            op_pat = re.escape(self.op_name.upper().replace("-", "_"))
            self._op_platform_re = re.compile(rf"(?i)\b{op_pat}\b")
        else:
            self._op_platform_re = None

        self._index_tiling_links(_as_dict(files.get("cross_layer/tiling_to_kernel.yaml")))
        self._index_kernel_variables(_as_dict(files.get("kernel/variables.yaml")))
        self._index_compile_macros(_as_dict(files.get("kernel/compile_macros.yaml")))
        self._index_shape_closure()

    def _index_shape_closure(self) -> None:
        """Map short names / tokens onto VAR_* ids present in shape_closure."""
        for vid in self.shape_closure:
            self.shape_alias_to_var[vid] = vid
            self.shape_alias_to_var[vid.upper()] = vid
            short = vid
            for prefix in ("VAR_KEY_", "VAR_KVAR_", "VAR_CSV_", "VAR_", "KEY_", "KVAR_"):
                if short.upper().startswith(prefix):
                    short = short[len(prefix) :]
                    break
            if short:
                self.shape_alias_to_var[short] = vid
                self.shape_alias_to_var[short.upper()] = vid
                self.shape_alias_to_var[short.lower()] = vid
        for item in self.lexicon.get("key_derivations") or []:
            if not isinstance(item, dict):
                continue
            vid = str(item.get("id") or "")
            if not vid or vid not in self.shape_closure:
                continue
            leaf = vid
            for prefix in ("VAR_KEY_", "VAR_KVAR_", "VAR_", "KEY_"):
                if leaf.upper().startswith(prefix):
                    leaf = leaf[len(prefix) :]
                    break
            if leaf:
                self.shape_alias_to_var[leaf] = vid
                self.shape_alias_to_var[leaf.upper()] = vid

    def _index_tiling_links(self, doc: dict[str, Any]) -> None:
        for link in doc.get("links") or []:
            if not isinstance(link, dict):
                continue
            if str(link.get("code") or "") == "missing_tiling_field_producer":
                field = str(link.get("field") or "").strip()
                if field:
                    self.missing_tdf_producers.add(field)
                    self.missing_tdf_producers.add(field.split(".")[-1])

    def _index_kernel_variables(self, doc: dict[str, Any]) -> None:
        for item in doc.get("runtime_variables") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            vid = str(item.get("id") or "")
            if name:
                self.kvar_by_name[name] = item
                self.kvar_by_name[name.upper()] = item
            if vid:
                self.kvar_by_name[vid] = item
                if vid.upper().startswith("KVAR_"):
                    short = vid[5:]
                    self.kvar_by_name.setdefault(short, item)
                    self.kvar_by_name.setdefault(short.upper(), item)
                    self.kvar_by_name.setdefault(short.lower(), item)
            for entry in item.get("domain_entries") or []:
                if not isinstance(entry, dict):
                    continue
                ename = str(entry.get("name") or "")
                if not ename or entry.get("value") is None:
                    continue
                self.enum_literal_values[ename] = entry.get("value")
                self.enum_literal_values[ename.upper()] = entry.get("value")

    def _index_compile_macros(self, doc: dict[str, Any]) -> None:
        _ = doc


def bind_atom(atom: dict[str, Any], ctx: BindContext) -> dict[str, Any]:
    """Return atom_binding record: status bound|unbound + target/reason."""
    raw = str(atom.get("raw") or atom.get("id") or "")
    kind = str(atom.get("kind") or "")
    name = str(atom.get("name") or atom.get("lhs") or "")
    negated = bool(atom.get("negated"))
    cmp_op = atom.get("cmp")
    rhs = atom.get("rhs")

    if _is_platform(raw, ctx) or _is_platform(name, ctx):
        return _unbound(atom, "PLATFORM_MACRO")
    if _is_loop_local(raw) or _is_loop_local(name):
        return _unbound(atom, "LOOP_LOCAL")

    if raw.lstrip("!").startswith("IsSameType_") or name.startswith("IsSameType"):
        target = _bind_is_same_type(raw.lstrip("!"))
        if target:
            return _bound(atom, target, "dtype_issametype", negated=negated)
        return _unbound(atom, "UNBOUND_DTYPE")

    if "ORIG_DTYPE" in raw.upper() or "ORIG_DTYPE" in name.upper():
        target = _bind_orig_dtype(atom)
        if target:
            return _bound(atom, target, "dtype_macro", negated=negated)
        return _unbound(atom, "UNBOUND_DTYPE")

    base_name = _strip_qualifiers(name)
    alias_key = _normalize_member(name)

    if kind == "ident":
        if alias_key in ctx.csv_field_aliases:
            column, value = ctx.csv_field_aliases[alias_key]
            if value is not None:
                return _bound(atom, {"op": "eq", "var": csv_var(column), "value": value}, "csv_field_alias", negated=negated)

    if kind == "ident" or (kind == "cmp" and cmp_op in {None, "eq", "ne"} and _looks_like_flag(base_name, ctx)):
        key_hit = _lookup_key_token(base_name, ctx)
        if key_hit:
            var_id, true_value = key_hit
            if kind == "cmp" and cmp_op in {"eq", "ne"}:
                wants_true = _truthy_rhs(rhs)
                if cmp_op == "ne":
                    wants_true = not wants_true
                value = true_value if wants_true else (1 - int(true_value) if true_value in (0, 1) else 0)
                expr = {"op": "eq", "var": var_id, "value": value}
            else:
                expr = {"op": "eq", "var": var_id, "value": true_value}
            return _bound(atom, expr, "template_arg_to_key", negated=negated)

    if alias_key in ctx.csv_field_aliases:
        column, value = ctx.csv_field_aliases[alias_key]
        if value is not None:
            expr = {"op": "eq", "var": csv_var(column), "value": value}
            if kind == "cmp" and cmp_op in {"eq", "ne"}:
                wants = _truthy_rhs(rhs)
                if cmp_op == "ne":
                    wants = not wants
                expr = {"op": "eq", "var": csv_var(column), "value": value if wants else 0}
            return _bound(atom, expr, "csv_field_alias", negated=negated)
        if kind == "cmp" and value is None:
            from .expr_bind import ExprBindError, bind_cmp_atom_to_ir

            try:
                return _bound(atom, bind_cmp_atom_to_ir(atom, ctx), "csv_field_alias_cmp", negated=negated)
            except ExprBindError as exc:
                return _unbound(atom, exc.reason)

    tdf_field = _extract_tdf_field(raw) or _extract_tdf_field(name)
    if tdf_field:
        leaf = tdf_field.split(".")[-1]
        if leaf in ctx.missing_tdf_producers or tdf_field in ctx.missing_tdf_producers:
            return _unbound(atom, "NO_HOST_PRODUCER")
        alias = _normalize_member(leaf)
        if alias in ctx.csv_field_aliases:
            column, value = ctx.csv_field_aliases[alias]
            if value is not None:
                return _bound(atom, {"op": "eq", "var": csv_var(column), "value": value}, "tdf_to_csv", negated=negated)
        if leaf in ctx.kvar_by_name or tdf_field in ctx.kvar_by_name:
            return _try_kvar(atom, leaf, ctx, negated)
        return _unbound(atom, "NO_HOST_PRODUCER")

    if kind == "cmp":
        from .expr_bind import ExprBindError, bind_cmp_atom_to_ir

        try:
            return _bound(atom, bind_cmp_atom_to_ir(atom, ctx), "expr_bind_cmp", negated=negated)
        except ExprBindError as exc:
            return _unbound(atom, exc.reason)

    kvar = ctx.kvar_by_name.get(base_name) or ctx.kvar_by_name.get(base_name.upper())
    if kvar:
        return _try_kvar(atom, base_name, ctx, negated)

    if kind == "call":
        call_name = _strip_qualifiers(str(atom.get("name") or ""))
        if "::" in call_name:
            call_name = call_name.split("::")[-1]
        key_hit = _lookup_key_token(call_name, ctx)
        if key_hit:
            var_id, true_value = key_hit
            return _bound(atom, {"op": "eq", "var": var_id, "value": true_value}, "template_arg_to_key", negated=negated)
        if _is_loop_local(call_name):
            return _unbound(atom, "LOOP_LOCAL")
        shape_hit = _try_shape_closure(call_name, atom, ctx, negated)
        if shape_hit:
            return shape_hit
        return _unbound(atom, "UNBOUND_CALL")

    shape_hit = _try_shape_closure(base_name or name or raw, atom, ctx, negated)
    if shape_hit:
        return shape_hit
    return _unbound(atom, "UNBOUND_ATOM")


def _try_shape_closure(name: str, atom: dict[str, Any], ctx: BindContext, negated: bool) -> dict[str, Any] | None:
    """Bind symbol if it maps to a VAR_* already in the shape-determined closure."""
    if not ctx.shape_closure:
        return None
    leaf = _strip_qualifiers(str(name or ""))
    if "::" in leaf:
        leaf = leaf.split("::")[-1]
    if "." in leaf:
        leaf = leaf.split(".")[-1]
    if _is_loop_local(leaf) or _is_platform(leaf, ctx):
        return None
    candidates = [
        leaf,
        leaf.upper(),
        _normalize_member(leaf),
        str(atom.get("name") or ""),
        str(atom.get("raw") or "").lstrip("!"),
    ]
    var_id = ""
    for cand in candidates:
        if not cand:
            continue
        hit = ctx.shape_alias_to_var.get(cand) or ctx.shape_alias_to_var.get(cand.upper())
        if hit and hit in ctx.shape_closure:
            var_id = hit
            break
    if not var_id:
        return None
    kind = str(atom.get("kind") or "")
    cmp_op = atom.get("cmp")
    rhs = atom.get("rhs")
    if kind == "cmp" and cmp_op in {"eq", "ne"}:
        wants_true = _truthy_rhs(rhs)
        if cmp_op == "ne":
            wants_true = not wants_true
        value = 1 if wants_true else 0
        return _bound(atom, {"op": "eq", "var": var_id, "value": value}, "shape_closure", negated=negated)
    return _bound(atom, {"op": "eq", "var": var_id, "value": 1}, "shape_closure", negated=negated)

def bind_atoms(atoms: list[dict[str, Any]], ctx: BindContext) -> list[dict[str, Any]]:
    return [bind_atom(atom, ctx) for atom in atoms]


def substitute_norm_expr(norm_expr: dict[str, Any] | None, bindings: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Replace atom placeholders with bound IR; return None if any unbound."""
    if not isinstance(norm_expr, dict):
        return None
    by_id = {str(b.get("atom") or ""): b for b in bindings}

    def walk(node: Any) -> Any:
        if not isinstance(node, dict):
            return node
        if node.get("op") == "atom":
            bid = str(node.get("id") or "")
            binding = by_id.get(bid)
            if not binding or binding.get("status") != "bound":
                raise ValueError(f"unbound atom {bid}")
            target = binding.get("target")
            if not isinstance(target, dict):
                raise ValueError(f"bad target for {bid}")
            return dict(target)
        out = dict(node)
        for key in ("arg", "lhs", "rhs", "condition", "then", "else", "expr"):
            if key in out:
                out[key] = walk(out[key])
        if "args" in out:
            out["args"] = [walk(a) for a in out["args"]]
        return out

    try:
        return walk(norm_expr)
    except ValueError:
        return None


def _try_kvar(atom: dict[str, Any], name: str, ctx: BindContext, negated: bool) -> dict[str, Any]:
    kvar = ctx.kvar_by_name.get(name) or ctx.kvar_by_name.get(name.upper()) or {}
    kvar_id = str(kvar.get("id") or "")
    if "ORIG_DTYPE" in name.upper():
        return _unbound(atom, "UNBOUND_DTYPE")
    classification = str(kvar.get("classification") or "").lower()
    if classification == "loop_local":
        return _unbound(atom, "LOOP_LOCAL")
    if classification == "platform":
        return _unbound(atom, "PLATFORM_MACRO")
    set_by = kvar.get("set_by") if isinstance(kvar.get("set_by"), dict) else {}
    if set_by.get("csv"):
        return _bound(atom, {"op": "ne", "var": csv_var(str(set_by["csv"])), "value": 0}, "kvar_set_by_csv", negated=negated)
    if set_by.get("key"):
        key = str(set_by.get("key"))
        var = key if key.startswith("VAR_") else f"VAR_{key}" if key.startswith("KEY_") else f"VAR_KEY_{key.upper()}"
        return _bound(atom, {"op": "eq", "var": var, "value": 1}, "kvar_set_by_key", negated=negated)
    if set_by.get("tiling"):
        var = f"VAR_{kvar_id}" if kvar_id and not kvar_id.startswith("VAR_") else (kvar_id or f"VAR_KVAR_{name.upper()}")
        return _bound(atom, {"op": "eq", "var": var, "value": 1}, "kvar_set_by", negated=negated)
    if _is_loop_local(name):
        return _unbound(atom, "LOOP_LOCAL")
    return _unbound(atom, "UNBOUND_KVAR")


def _bind_orig_dtype(atom: dict[str, Any]) -> dict[str, Any] | None:
    cmp_op = atom.get("cmp") or "eq"
    rhs = atom.get("rhs")
    rhs_name = str(rhs if not isinstance(rhs, dict) else rhs.get("name") or rhs.get("value") or "")
    raw = str(atom.get("raw") or "")
    match = re.search(r"(DT_[A-Z0-9_]+)", raw)
    if match:
        rhs_name = match.group(1)
    if rhs_name not in DTYPE_VALUES:
        return None
    value = DTYPE_VALUES[rhs_name]
    if cmp_op == "ne":
        return {"op": "ne", "var": "VAR_KEY_INPUTDTYPE", "value": value}
    return {"op": "eq", "var": "VAR_KEY_INPUTDTYPE", "value": value}


def _bind_is_same_type(raw: str) -> dict[str, Any] | None:
    key = raw.lower()
    if "float" in key and "16" not in key and "bf" not in key:
        return {"op": "eq", "var": csv_var("Dtype"), "value": "fp32"}
    if "bf16" in key or "bfloat16" in key:
        return {"op": "eq", "var": csv_var("Dtype"), "value": "bf16"}
    if "fp16" in key or "float16" in key or "half" in key:
        return {"op": "eq", "var": csv_var("Dtype"), "value": "fp16"}
    return None


def _lookup_key_token(name: str, ctx: BindContext) -> tuple[str, int] | None:
    clean = _strip_qualifiers(name).upper()
    if "::" in clean:
        clean = clean.split("::")[-1]
    if clean in ctx.key_tokens:
        return ctx.key_tokens[clean]
    return None


def _bound(atom: dict[str, Any], target: dict[str, Any], via: str, *, negated: bool) -> dict[str, Any]:
    expr = target
    if negated:
        expr = {"op": "not", "arg": target}
    return {"atom": atom.get("id"), "status": "bound", "target": expr, "via": via, "raw": atom.get("raw")}


def _unbound(atom: dict[str, Any], reason: str) -> dict[str, Any]:
    return {"atom": atom.get("id"), "status": "unbound", "reason": reason, "raw": atom.get("raw"), "target": None, "via": None}


def _is_platform(text: str, ctx: BindContext | None = None) -> bool:
    if any(p.search(text or "") for p in PLATFORM_MACRO_PATTERNS):
        return True
    if ctx is not None and getattr(ctx, "_op_platform_re", None) is not None:
        return bool(ctx._op_platform_re.search(text or ""))
    return False


def _is_loop_local(text: str) -> bool:
    return any(p.search(text or "") for p in LOOP_LOCAL_PATTERNS)


def _looks_like_flag(name: str, ctx: BindContext) -> bool:
    clean = _strip_qualifiers(name).upper()
    if "::" in clean:
        clean = clean.split("::")[-1]
    return clean.startswith("IS_") or clean in ctx.key_tokens


def _strip_qualifiers(name: str) -> str:
    return str(name or "").strip().replace("->", ".").replace(" ", "")


def _normalize_member(name: str) -> str:
    text = _strip_qualifiers(name).lower().replace("::", ".")
    if text.startswith("this."):
        text = text[5:]
    return text


def _extract_tdf_field(text: str) -> str | None:
    s = str(text or "")
    match = re.search(r"(?i)tilingdata\s*->\s*([A-Za-z_][\w.]*)", s)
    if match:
        return match.group(1)
    match = re.search(r"(?i)tilingdata\.([A-Za-z_][\w.]*)", s)
    if match:
        return match.group(1)
    return None


def _tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*", str(text or ""))


def _truthy_rhs(rhs: Any) -> bool:
    if isinstance(rhs, bool):
        return rhs
    if isinstance(rhs, (int, float)):
        return rhs != 0
    return str(rhs).lower() in {"true", "1", "yes"}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
