from __future__ import annotations

import argparse, hashlib, json, os, sqlite3, sys, tempfile
from pathlib import Path
from typing import Any

import yaml

if __package__ in (None, ""):
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path: sys.path.insert(0, str(root))
from understand_operator._operator.artifacts import existing_operator_root, safe_op_name
from understand_operator._operator.spec import spec_bundle_hash


def build_query_index(repo: Path, op_name: str) -> Path:
    root = existing_operator_root(repo.resolve(), op_name); target = root / "indexes" / "operator_kb.sqlite"; target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".sqlite", dir=target.parent, delete=False) as handle: temporary = Path(handle.name)
    try:
        db = sqlite3.connect(temporary); _schema(db)
        for level, rel, key in (("raw", "graphs/raw/nodes.yaml", "nodes"), ("derived", "graphs/derived/nodes.yaml", "nodes")):
            for entry in _list(root / rel, key): _entity(db, level, entry)
        for level, rel in (("raw", "graphs/raw/edges.yaml"), ("derived", "graphs/derived/edges.yaml")):
            for entry in _list(root / rel, "edges"): _relation(db, level, entry)
        for entry in _list(root / "graphs/derived/expansions.yaml", "expansions"):
            derived_id = entry.get("derived_id")
            for raw_id in entry.get("raw_node_refs") or []:
                db.execute("insert into expansions values(?,?,?)", (derived_id, raw_id, "node"))
            for raw_id in entry.get("raw_edge_refs") or []:
                db.execute("insert into expansions values(?,?,?)", (derived_id, raw_id, "edge"))
        for entry in _list(root / "graphs/raw/paths.yaml", "paths"):
            db.execute("insert into paths values(?,?,?,?)", (entry.get("id"), entry.get("start_id"), entry.get("end_id"), json.dumps(entry, ensure_ascii=False)))
        for key, value in _metadata(root).items(): db.execute("insert into metadata values(?,?)", (key, value))
        try:
            db.execute("create virtual table entity_fts using fts5(id, label, aliases, symbol, file, path)")
            db.execute("insert into entity_fts(id,label,aliases,symbol,file,path) select id,label,'','','',detail_ref from entities")
            db.execute("insert into metadata values(?,?)", ("fts5", "enabled"))
        except sqlite3.OperationalError:
            db.execute("insert into metadata values(?,?)", ("fts5", "unavailable"))
        db.commit(); db.close(); os.replace(temporary, target); return target
    except Exception:
        temporary.unlink(missing_ok=True); raise


def _schema(db: sqlite3.Connection) -> None:
    db.executescript('''create table entities(id text primary key,graph_level text not null,kind text not null,label text,normalized_label text,detail_ref text,fields_json text);
create table relations(id text primary key,graph_level text not null,type text not null,source_id text not null,target_id text not null,detail_ref text,fields_json text);
create table aliases(alias text not null,normalized_alias text not null,entity_id text not null);create table source_anchors(id text primary key,file text not null,symbol text,start_line integer,end_line integer,encoding text,code_hash text,file_hash text);create table entity_sources(entity_id text not null,source_anchor_id text not null);create table expansions(derived_id text,raw_id text,raw_kind text);create table paths(path_id text primary key,start_id text,end_id text,path_json text);create table metadata(key text primary key,value text);
create index idx_entities_kind on entities(kind);create index idx_entities_label on entities(normalized_label);create index idx_relations_source on relations(source_id);create index idx_relations_target on relations(target_id);create index idx_relations_type on relations(type);create index idx_aliases_normalized on aliases(normalized_alias);create index idx_sources_file_line on source_anchors(file,start_line,end_line);''')


def _entity(db: sqlite3.Connection, level: str, entry: dict[str, Any]) -> None:
    fields = entry.get("fields") if isinstance(entry.get("fields"), dict) else {}; label = str(entry.get("label") or entry.get("id") or ""); entity_id = str(entry.get("id"))
    db.execute("insert into entities values(?,?,?,?,?,?,?)", (entity_id, level, str(entry.get("kind") or "fact"), label, _norm(label), entry.get("detail_ref"), json.dumps(fields, ensure_ascii=False)))
    for alias in fields.get("aliases") or []: db.execute("insert into aliases values(?,?,?)", (str(alias), _norm(str(alias)), entity_id))
    for source in entry.get("source_refs") or []:
        db.execute("insert into entity_sources values(?,?)", (entity_id, str(source)))


def _relation(db: sqlite3.Connection, level: str, entry: dict[str, Any]) -> None:
    db.execute("insert into relations values(?,?,?,?,?,?,?)", (entry.get("id"), level, entry.get("type"), entry.get("source_id"), entry.get("target_id"), entry.get("detail_ref"), json.dumps(entry, ensure_ascii=False)))


def _list(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.exists(): return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}; values = data.get(key) if isinstance(data, dict) else []
    return [value for value in values if isinstance(value, dict)] if isinstance(values, list) else []


def _metadata(root: Path) -> dict[str, str]:
    result = {"schema_version": "1", "spec_bundle_hash": spec_bundle_hash()}
    for key, rel in (("facts_hash", "facts"), ("raw_graph_hash", "graphs/raw"), ("derived_graph_hash", "graphs/derived")):
        digest = hashlib.sha256(); folder = root / rel
        for path in sorted(folder.rglob("*.yaml")) if folder.exists() else []: digest.update(path.read_bytes())
        result[key] = "sha256:" + digest.hexdigest()
    return result


def _norm(value: str) -> str: return "".join(char for char in value.lower() if char.isalnum())
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("repo", nargs="?", default="."); parser.add_argument("--op-name", required=True); args = parser.parse_args(argv); print(build_query_index(Path(args.repo), safe_op_name(args.op_name, Path(args.repo)))); return 0
if __name__ == "__main__": raise SystemExit(main())
