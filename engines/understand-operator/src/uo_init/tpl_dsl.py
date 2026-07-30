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
        name = parts[0]
        if kind == "UINT":
            bw = int(BW_RE.match(parts[1]).group(1))
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
    text = Path(path).read_text(encoding="utf-8", errors="replace")
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
