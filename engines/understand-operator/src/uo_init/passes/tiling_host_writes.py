# -*- coding: utf-8 -*-
"""Resolve current-source Host writes to qualified TilingData fields.

Architecture-local Host sources and shared top-level Host sources that explicitly
reference the requested architecture are scanned.  A write is accepted only
when receiver type/member identity resolves to one concrete TilingData owner;
short field names alone never select a target.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.symbol_identity import normalize_symbol
from uo_init.source_layout import selected_host_files as _layout_host_files

_SUFFIXES = {".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"}
_WORD_RE = re.compile(r"\b[A-Za-z_]\w*\b")
_SETTER_RE = re.compile(
    r"(?P<receiver>[A-Za-z_]\w*(?:\s*(?:\.|->)\s*[A-Za-z_]\w*)*)\s*"
    r"(?:\.|->)\s*set_(?P<field>[A-Za-z_]\w*)\s*\("
)
_DIRECT_RE = re.compile(
    r"(?P<lhs>[A-Za-z_]\w*(?:\s*(?:\.|->)\s*[A-Za-z_]\w*)+)\s*"
    r"(?<![=!<>])=(?!=)\s*(?P<rhs>[^;]+);", re.S,
)


def enrich_tiling_host_writes(
    codemap: CodeMap,
    operator_root: str | Path,
    *,
    architecture: str = "",
) -> CodeMap:
    root = Path(operator_root).expanduser().resolve()
    types = {e.name: e for e in codemap.by_kind(EntityKind.TILING_DATA)}
    if not types:
        return codemap
    known = set(types)
    fields: dict[tuple[str, str], Entity] = {}
    nested: dict[str, set[str]] = defaultdict(set)
    for field in codemap.by_kind(EntityKind.TILING_FIELD):
        owner = str(field.attrs.get("owner") or "")
        fields[(owner, field.name)] = field
        nested[field.name].update(_referenced_types(str(field.attrs.get("cpp_type") or ""), known))

    paths = _selected_host_files(root, architecture)
    texts: list[tuple[Path, str, str]] = []
    receiver_types: dict[str, set[str]] = defaultdict(set)
    type_alt = "|".join(re.escape(name) for name in sorted(known, key=len, reverse=True))
    decl_re = re.compile(
        rf"\b(?P<type>{type_alt})\b(?:\s*<[^;{{}}]*>)?\s*(?:const\s*)?[*&]*\s*(?P<name>[A-Za-z_]\w*)\b"
    )
    for path in paths:
        raw = path.read_text(encoding="utf-8", errors="replace")
        masked = _mask_non_code(raw)
        texts.append((path, raw, masked))
        for match in decl_re.finditer(masked):
            receiver_types[match.group("name")].add(match.group("type"))

    _purge(codemap)
    sites = resolved = ambiguous = 0
    written: set[str] = set()
    for path, raw, masked in texts:
        file = _rel(root, path)
        for match in _SETTER_RE.finditer(masked):
            close = _matching_paren(masked, match.end() - 1)
            if close < 0:
                continue
            sites += 1
            receiver = normalize_symbol(match.group("receiver"))
            field_name = match.group("field")
            targets = _targets(receiver, field_name, receiver_types, fields, nested, known)
            line = _line(raw, match.start())
            expr = raw[match.end():close].strip()
            if len(targets) == 1:
                _write(codemap, targets[0], file, line, receiver, expr, "setter")
                written.add(targets[0].id); resolved += 1
            else:
                _unresolved(codemap, file, line, receiver, field_name, expr, targets)
                ambiguous += 1

        for match in _DIRECT_RE.finditer(masked):
            lhs = normalize_symbol(match.group("lhs"))
            parts = [p for p in lhs.split(".") if p]
            if len(parts) < 2:
                continue
            receiver, field_name = ".".join(parts[:-1]), parts[-1]
            owners = _receiver_owners(receiver, receiver_types, fields, nested, known)
            if not owners:
                continue
            targets = _unique([fields[(o, field_name)] for o in owners if (o, field_name) in fields])
            sites += 1
            line = _line(raw, match.start())
            expr = raw[match.start("rhs"):match.end("rhs")].strip()
            if len(targets) == 1:
                _write(codemap, targets[0], file, line, receiver, expr, "assignment")
                written.add(targets[0].id); resolved += 1
            else:
                _unresolved(codemap, file, line, receiver, field_name, expr, targets)
                ambiguous += 1

    _attach_defaults(codemap, root, fields)
    closure = dict(codemap.meta.get("kernel_tiling_closure") or {})
    closure.update({
        "selected_host_writer_files": [_rel(root, p) for p in paths],
        "tiling_host_writer_sites": sites,
        "tiling_resolved_host_writer_sites": resolved,
        "tiling_host_writer_fields": len(written),
        "tiling_ambiguous_writer_sites": ambiguous,
        "tiling_host_writer_policy": "qualified-receiver-arch-shared/v2",
    })
    codemap.meta["kernel_tiling_closure"] = closure
    return codemap


def _selected_host_files(root: Path, architecture: str) -> list[Path]:
    return [p.resolve() for p in _layout_host_files(root, architecture)]


def _targets(receiver, field_name, receiver_types, fields, nested, known) -> list[Entity]:
    owners = _receiver_owners(receiver, receiver_types, fields, nested, known)
    return _unique([fields[(o, field_name)] for o in owners if (o, field_name) in fields])


def _receiver_owners(receiver, receiver_types, fields, nested, known) -> set[str]:
    parts = [p for p in normalize_symbol(receiver).split(".") if p]
    if not parts:
        return set()
    owners = set(receiver_types.get(parts[0]) or ())
    if not owners:
        owners.update(nested.get(parts[0]) or ())
    for segment in parts[1:]:
        nxt: set[str] = set()
        for owner in owners:
            field = fields.get((owner, segment))
            if field is not None:
                nxt.update(_referenced_types(str(field.attrs.get("cpp_type") or ""), known))
        if not nxt:
            nxt.update(nested.get(segment) or ())
        owners = nxt
    return owners


def _purge(codemap: CodeMap) -> None:
    provs = {"source_tilingdata_host_write_verified", "source_tilingdata_host_write_unresolved"}
    remove_ent = {eid for eid,e in codemap.entities.items() if str(e.attrs.get("provenance") or "") in provs}
    remove_rel = {rid for rid,r in codemap.relations.items() if str(r.attrs.get("provenance") or "") == "source_tilingdata_host_write_verified"}
    for rid,r in list(codemap.relations.items()):
        if r.src in remove_ent or r.dst in remove_ent: remove_rel.add(rid)
    for rid in remove_rel: codemap.relations.pop(rid, None)
    for eid in remove_ent: codemap.entities.pop(eid, None)


def _write(codemap, field, file, line, receiver, expr, mode) -> None:
    owner = str(field.attrs.get("owner") or "")
    node = codemap.upsert(
        EntityKind.PREDICATE, f"{owner}::{field.name} <- {expr[:120]}",
        eid=f"TDWRITEV::{file}::{line}::{owner}::{field.name}",
        attrs={"predicate_role":"tilingdata_writer","owner":owner,"field":field.name,"receiver":receiver,
               "expression":expr[:600],"write_mode":mode,"provenance":"source_tilingdata_host_write_verified"},
        file=file,line=line,status="confirmed",
    )
    codemap.link(RelationKind.WRITES,node.id,field.id,
        attrs={"provenance":"source_tilingdata_host_write_verified","file":file,"line":line,"mode":mode},status="confirmed")
    site={"file":file,"line":line,"receiver":receiver,"expression":expr[:300],"mode":mode}
    if site not in field.attrs.setdefault("host_writer_sites",[]): field.attrs["host_writer_sites"].append(site)
    field.attrs["host_writer_site_count"]=len(field.attrs["host_writer_sites"])


def _unresolved(codemap,file,line,receiver,field_name,expr,candidates) -> None:
    codemap.upsert(EntityKind.OTHER,f"{receiver}.set_{field_name}",eid=f"TDWRITEUNRES::{file}::{line}::{field_name}",
        attrs={"role":"tilingdata_writer_unresolved","reason":"field_owner_ambiguous" if candidates else "field_owner_unknown",
               "receiver":receiver,"field":field_name,"expression":expr[:600],
               "candidate_fields":[f.attrs.get("qualified_name") for f in candidates],
               "provenance":"source_tilingdata_host_write_unresolved"},
        file=file,line=line,status="partial",confidence=0.5)


def _attach_defaults(codemap, root, fields) -> None:
    cache: dict[str,list[str]]={}
    for field in fields.values():
        if not field.file or not field.line_start: continue
        if field.file not in cache:
            p=_resolve_file(root,field.file); cache[field.file]=p.read_text(encoding="utf-8",errors="replace").splitlines() if p else []
        lines=cache[field.file]; n=int(field.line_start or 0)
        if 1<=n<=len(lines):
            m=re.search(rf"\b{re.escape(field.name)}\b\s*=\s*([^;]+);",lines[n-1])
            if m:
                field.attrs["default_initializer"]=m.group(1).strip(); field.attrs["default_initializer_site"]={"file":field.file,"line":n}


def _referenced_types(raw: str, known: set[str]) -> set[str]:
    return set(_WORD_RE.findall(raw or "")) & known


def _unique(items) -> list[Entity]:
    out=[]; seen=set()
    for item in items:
        if item.id not in seen: seen.add(item.id); out.append(item)
    return out


def _matching_paren(text,open_pos):
    if open_pos<0 or open_pos>=len(text) or text[open_pos]!="(": return -1
    d=0
    for i in range(open_pos,len(text)):
        if text[i]=="(": d+=1
        elif text[i]==")":
            d-=1
            if d==0:return i
    return -1


def _mask_non_code(text: str) -> str:
    out=list(text); i=0; state="code"; quote=""
    while i<len(text):
        ch=text[i]; nxt=text[i+1] if i+1<len(text) else ""
        if state=="code":
            if ch=="/" and nxt=="/": out[i]=out[i+1]=" "; i+=2; state="line"; continue
            if ch=="/" and nxt=="*": out[i]=out[i+1]=" "; i+=2; state="block"; continue
            if ch in {'\"',"'"}: quote=ch; out[i]=" "; i+=1; state="string"; continue
            i+=1; continue
        if state=="line":
            if ch=="\n":state="code"
            else:out[i]=" "
            i+=1;continue
        if state=="block":
            if ch=="*" and nxt=="/":out[i]=out[i+1]=" ";i+=2;state="code"
            else:
                if ch!="\n":out[i]=" "
                i+=1
            continue
        if ch=="\\" and i+1<len(text):out[i]=out[i+1]=" ";i+=2;continue
        if ch==quote:out[i]=" ";i+=1;state="code"
        else:
            if ch!="\n":out[i]=" "
            i+=1
    return "".join(out)


def _resolve_file(root: Path, raw: str) -> Path | None:
    rel=raw.replace("\\","/").lstrip("./"); candidates=[root.parent/rel,root/rel]
    if rel.startswith(root.name+"/"):candidates.append(root/rel[len(root.name)+1:])
    for p in candidates:
        if p.is_file():return p
    return None


def _rel(root: Path,path: Path)->str:
    try:return path.relative_to(root.parent).as_posix()
    except ValueError:return path.as_posix()


def _line(text: str,offset: int)->int:return text.count("\n",0,max(0,offset))+1
