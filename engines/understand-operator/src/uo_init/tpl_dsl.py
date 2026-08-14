# -*- coding: utf-8 -*-
"""ASCENDC_TPL_* DSL textual parser (schema invisible in normal clang AST)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


BW_RE = re.compile(r"ASCENDC_TPL_(\d+)_BW")
DECL_KIND_RE = re.compile(r"ASCENDC_TPL_(UINT|BOOL|DTYPE|FORMAT)_DECL\s*\(")
SEL_KIND_RE = re.compile(
    r"ASCENDC_TPL_(UINT|BOOL|DTYPE|FORMAT)_SEL\s*\(|"
    r"ASCENDC_TPL_TILING_STRUCT_SEL\s*\("
)


@dataclass
class TplDim:
    name: str
    kind: str
    bw: int
    vals: list[str]
    bit_lo: int = 0
    bit_hi: int = 0

    @property
    def value_domain(self) -> list[str]:
        """Values excluding UI_LIST/UI_RANGE marker at vals[0] for UINT."""
        if self.kind == "UINT" and self.vals:
            marker = self.vals[0]
            if "UI_LIST" in marker or "UI_RANGE" in marker:
                return self.vals[1:]
        return list(self.vals)


@dataclass
class TplSchema:
    op_tag: str
    dims: list[TplDim] = field(default_factory=list)
    selections: list[list[dict]] = field(default_factory=list)

    @property
    def total_bits(self) -> int:
        return sum(d.bw for d in self.dims)

    def encode_uint(self, dim: TplDim, value: int | str) -> int:
        """UINT encodes index in the declared value domain (UI_LIST marker stripped).

        Matches CANN ``FastEncodeTilingKeyDirect``: find value in domain, pack index.
        """
        if dim.kind != "UINT":
            raise ValueError(f"{dim.name} is not UINT")
        domain = dim.value_domain
        sval = str(value)
        try:
            return domain.index(sval)
        except ValueError as e:
            raise ValueError(f"{dim.name} value {value!r} not in {domain}") from e

    def encode_bool(self, value: int | bool | str) -> int:
        return 1 if value in (1, True, "1", "true", "True") else 0

    def encode_tiling_key(self, inst: dict[str, str | int | bool]) -> int:
        """Pack one concrete ARGS_SEL instance into a uint64 tiling key."""
        key = 0
        shift = 0
        for dim in self.dims:
            raw = inst.get(dim.name)
            if raw is None:
                domain = dim.value_domain
                if not domain:
                    raise ValueError(f"missing value for {dim.name}")
                raw = domain[0]
            if dim.kind == "UINT":
                encode_val = self.encode_uint(dim, raw)
            elif dim.kind == "BOOL":
                encode_val = self.encode_bool(raw)
            else:
                encode_val = int(raw)
            mask = (1 << dim.bw) - 1
            key |= (encode_val & mask) << shift
            shift += dim.bw
        if shift > 64:
            raise ValueError(f"tiling key bits {shift} exceed 64")
        return key

    def decode_tiling_key(self, key: int) -> dict[str, str]:
        """Inverse of :meth:`encode_tiling_key` (best-effort for UINT/BOOL)."""
        out: dict[str, str] = {}
        shift = 0
        for dim in self.dims:
            mask = (1 << dim.bw) - 1
            encode_val = (int(key) >> shift) & mask
            shift += dim.bw
            if dim.kind == "UINT":
                domain = dim.value_domain
                out[dim.name] = domain[encode_val] if encode_val < len(domain) else str(encode_val)
            else:
                out[dim.name] = str(encode_val)
        return out


def encode_tiling_key(schema: TplSchema, inst: dict[str, str | int | bool]) -> int:
    return schema.encode_tiling_key(inst)


def _join_continuations(src: str) -> str:
    return re.sub(r"\\\r?\n", " ", src)


def _balanced_paren_body(src: str, open_paren_idx: int) -> str:
    """open_paren_idx points at '('; return inside excluding outer parens."""
    depth = 0
    for j in range(open_paren_idx, len(src)):
        if src[j] == "(":
            depth += 1
        elif src[j] == ")":
            depth -= 1
            if depth == 0:
                return src[open_paren_idx + 1 : j]
    raise ValueError("unbalanced parenthesis")


def _split_args(inner: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in inner:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p != ""]


def _uint_bit_width(token: str) -> int:
    """Width from ``ASCENDC_TPL_N_BW``, a decimal literal, or a named macro.

    Missing / unknown tokens keep a conservative 8-bit width so extract does
    not crash; callers still see the dim.
    """
    raw = (token or "").strip()
    if not raw:
        return 8
    m = BW_RE.fullmatch(raw) or BW_RE.search(raw)
    if m:
        return int(m.group(1))
    if re.fullmatch(r"\d+", raw):
        return int(raw)
    return 8


_QUOTED_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE)
_DEFINE_LINE_RE = re.compile(
    r"^\s*#\s*define\s+([A-Za-z_]\w*)(?:\(([^)]*)\))?\s*(.*?)\s*$",
    re.M,
)
_GET_TPL_HINT = "GET_TPL_TILING_KEY"
_TPL_HINT = "ASCENDC_TPL_"


def cann_include_search_roots() -> list[Path]:
    try:
        from uo_init.paths import cann_root
    except Exception:
        return []
    root = cann_root()
    if root is None:
        return []
    rels = (
        "cann-opbase/x86_64-linux/pkg_inc",
        "cann-opbase/x86_64-linux/pkg_inc/op_common",
        "cann-opbase/x86_64-linux/include",
        "cann-opbase/x86_64-linux/include/op_common",
        "cann-asc-devkit/x86_64-linux/asc/include",
        "cann-asc-devkit/x86_64-linux/ascendc/include/highlevel_api",
    )
    return [root / rel for rel in rels if (root / rel).is_dir()]


def collect_defines(text: str) -> dict[str, tuple[list[str] | None, str]]:
    """``#define NAME`` / ``#define NAME(a,...)`` after line-continuation join."""
    src = _join_continuations(text or "")
    out: dict[str, tuple[list[str] | None, str]] = {}
    for match in _DEFINE_LINE_RE.finditer(src):
        name, params, body = match.group(1), match.group(2), (match.group(3) or "").strip()
        if not body or body.startswith("#"):
            continue
        if params is None:
            out[name] = (None, body)
            continue
        args = [p.strip() for p in params.split(",") if p.strip()]
        out[name] = (args, body)
    return out


def _subst_macro(body: str, params: list[str], args: list[str]) -> str:
    named = list(params)
    va: list[str] = []
    if named and named[-1] in {"...", "__VA_ARGS__"}:
        named = named[:-1]
        va = args[len(named) :]
        body = body.replace("__VA_ARGS__", ", ".join(va))
    for param, value in zip(named, args):
        body = re.sub(rf"\b{re.escape(param)}\b", value, body)
    return body


def expand_interesting_macros(text: str, defines: dict[str, tuple[list[str] | None, str]]) -> str:
    """Inline macros whose body is a TPL / GET_TPL packing helper."""
    interesting = {
        name: spec
        for name, spec in defines.items()
        if name != "GET_TPL_TILING_KEY"
        and (_TPL_HINT in spec[1] or _GET_TPL_HINT in spec[1])
    }
    if not interesting:
        return text
    src = _join_continuations(text or "")
    for _ in range(24):
        changed = False
        for name, (params, body) in interesting.items():
            if params is None:
                nxt = re.sub(rf"\b{re.escape(name)}\b", body, src)
                if nxt != src:
                    src = nxt
                    changed = True
                continue
            if not params:
                nxt = re.sub(rf"\b{re.escape(name)}\s*\(\s*\)", body, src)
                if nxt != src:
                    src = nxt
                    changed = True
                continue
            match = re.search(rf"\b{re.escape(name)}\s*\(", src)
            if not match:
                continue
            open_pos = src.find("(", match.start())
            try:
                inner = _balanced_paren_body(src, open_pos)
            except ValueError:
                continue
            close = open_pos + 1 + len(inner)
            args = _split_args(inner)
            repl = _subst_macro(body, params, args)
            src = src[: match.start()] + repl + src[close + 1 :]
            changed = True
            break
        if not changed:
            break
    return src


def load_quoted_include_texts(path: Path, *, extra_roots: list[Path] | None = None) -> list[str]:
    """Quoted includes from ``path`` (a few levels), plus CANN search roots."""
    parent = Path(path).parent
    try:
        src = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    roots = [parent, *(extra_roots or []), *cann_include_search_roots()]
    texts: list[str] = []
    seen: set[Path] = set()
    pending: list[tuple[str, Path]] = [(src, parent)]
    depth = 0
    while pending and depth < 4:
        nxt: list[tuple[str, Path]] = []
        for text, base in pending:
            for inc in _QUOTED_INCLUDE_RE.findall(text):
                low = inc.replace("\\", "/").lower()
                if not any(tok in low for tok in ("tiling", "tpl", "template_argument", "atvoss")):
                    continue
                search = [base, *roots]
                for root in search:
                    cand = (root / inc.replace("\\", "/")).resolve()
                    if not cand.is_file() or cand in seen:
                        continue
                    seen.add(cand)
                    try:
                        body = cand.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        break
                    texts.append(body)
                    nxt.append((body, cand.parent))
                    break
        pending = nxt
        depth += 1
    return texts


def expand_tpl_source(text: str, extra_texts: Iterable[str] | None = None) -> str:
    defines = collect_defines(text)
    for extra in extra_texts or ():
        defines.update(collect_defines(extra))
    return expand_interesting_macros(text, defines)


def parse_args_decl(src: str) -> TplSchema:
    src = _join_continuations(src)
    m = re.search(r"ASCENDC_TPL_ARGS_DECL\s*\(", src)
    if not m:
        return TplSchema(op_tag="")
    body = _balanced_paren_body(src, m.end() - 1)
    top = _split_args(body)
    op_tag = top[0] if top else ""
    # re-scan DECL macros inside body (after op tag)
    dims: list[TplDim] = []
    off = 0
    for dm in DECL_KIND_RE.finditer(body):
        kind = dm.group(1)
        inner = _balanced_paren_body(body, dm.end() - 1)
        parts = _split_args(inner)
        name = parts[0] if parts else ""
        if not name:
            continue
        if kind == "UINT":
            bw = _uint_bit_width(parts[1] if len(parts) > 1 else "")
            vals = parts[2:]
        elif kind == "BOOL":
            bw, vals = 1, parts[1:]
        else:
            bw, vals = 8, parts[1:]
        dims.append(TplDim(name=name, kind=kind, bw=bw, vals=vals))
    # assign bit ranges
    bit = 0
    for d in dims:
        d.bit_lo = bit
        d.bit_hi = bit + d.bw - 1
        bit += d.bw
    return TplSchema(op_tag=op_tag, dims=dims)


def parse_args_sel(src: str) -> list[list[dict]]:
    """Return list of ARGS_SEL groups; each group is list of {name,kind,vals}."""
    src = _join_continuations(src)
    groups: list[list[dict]] = []
    for m in re.finditer(r"ASCENDC_TPL_ARGS_SEL\s*\(", src):
        body = _balanced_paren_body(src, m.end() - 1)
        sels: list[dict] = []
        for sm in re.finditer(
            r"ASCENDC_TPL_(UINT|BOOL|DTYPE|FORMAT)_SEL\s*\(", body
        ):
            kind = sm.group(1)
            inner = _balanced_paren_body(body, sm.end() - 1)
            parts = _split_args(inner)
            sels.append({"name": parts[0], "kind": kind, "vals": parts[1:]})
        groups.append(sels)
    return groups


def parse_file(path: str | Path) -> TplSchema:
    header = Path(path)
    text = header.read_text(encoding="utf-8", errors="replace")
    extras = load_quoted_include_texts(header)
    text = expand_tpl_source(text, extras)
    schema = parse_args_decl(text)
    schema.selections = parse_args_sel(text)
    return schema


def expand_legal_instances(schema: TplSchema) -> list[dict[str, str]]:
    """Expand ARGS_SEL groups into concrete dim->value maps (cartesian per group)."""
    import itertools

    out: list[dict[str, str]] = []
    for group in schema.selections:
        axes: list[tuple[str, list[str]]] = []
        for sel in group:
            name = sel["name"]
            vals = sel["vals"]
            # UINT_SEL often: name, UI_LIST, v1, v2... or name, UI_RANGE, lo, hi
            if vals and ("UI_LIST" in vals[0] or "UI_RANGE" in vals[0]):
                domain = vals[1:]
            else:
                domain = vals
            axes.append((name, domain))
        if not axes:
            continue
        names = [a[0] for a in axes]
        for combo in itertools.product(*[a[1] for a in axes]):
            out.append(dict(zip(names, combo)))
    return out


def bit_comment_ranges(src: str) -> dict[str, tuple[int, int]]:
    """Parse `// bit: hi-lo` or `// bit: n` comments near DECL lines if present."""
    src = _join_continuations(src)
    found: dict[str, tuple[int, int]] = {}
    for m in re.finditer(
        r"ASCENDC_TPL_(?:UINT|BOOL|DTYPE|FORMAT)_DECL\s*\(\s*(\w+)[^)]*\)[^\n]*//\s*bit:\s*(\d+)(?:-(\d+))?",
        src,
    ):
        name = m.group(1)
        a, b = int(m.group(2)), m.group(3)
        if b is None:
            found[name] = (a, a)
        else:
            lo, hi = sorted((a, int(b)))
            found[name] = (lo, hi)
    return found
