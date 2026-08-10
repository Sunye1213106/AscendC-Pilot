# -*- coding: utf-8 -*-
"""Phase 1–2 acceptance: unified CodeMap IR + .uo store."""

from __future__ import annotations

from pathlib import Path

from uo_init.build import compile_codemap
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.reachability import compute_reachable
from uo_init.query.engine import CodeMapQuery
from uo_init.store.reader import read_codemap
from uo_init.store.writer import write_codemap


class _Summary:
    def __init__(self, writes=None, reads=None, calls=None, params=None):
        self.writes = writes or []
        self.reads = reads or []
        self.calls = calls or []
        self.params = params or []


class _Write:
    def __init__(self, path, function="DoOpTiling", file="host.cpp", line=10, rhs="x"):
        self.path = path
        self.function = function
        self.file = file
        self.line = line
        self.rhs = rhs

    def guards(self):
        return ["queryType == DT_FLOAT16"]


class _HostIR:
    def __init__(self):
        self.backend = "clang"
        self.summaries = {
            "DoOpTiling": _Summary(
                writes=["tiling.queryType"],
                reads=["queryType"],
                calls=[("EncodeKey", ())],
            ),
            "EncodeKey": _Summary(writes=["key.IsDtype"], reads=["queryType"]),
        }
        self.writes = [
            _Write("tiling.queryType"),
            _Write("key.IsDtype", function="EncodeKey", line=20),
        ]
        self.call_sites = []


class _Branch:
    def __init__(self):
        self.condition = "IS_DETERMINISTIC"
        self.file = "kernel.cpp"
        self.line = 42
        self.id = "KBR_1"
        self.dimensions = ["IsDtype"]
        self.variants = ["fp16"]
        self.function = "FlashAttentionScoreGrad"


class _KernelIR:
    def __init__(self):
        self.branches = [_Branch()]
        self.variants = ["fp16"]
        self.notes = []


def test_codemap_host_kernel_path(tmp_path: Path):
    host = _HostIR()
    kernel = _KernelIR()
    result = compile_codemap(
        op_name="flash_attention_score_grad",
        architecture="arch35",
        op_root=tmp_path,
        host_ir=host,
        kernel_ir=kernel,
        inputs=["query", "queryType"],
        key_fields=[
            {
                "name": "IsDtype",
                "input_roots": ["queryType"],
                "exactness": "exact",
            }
        ],
        template_bindings=[
            {
                "template": "FlashAttentionScoreGrad",
                "tiling_key": "IsDtype",
                "args": {"T": "half"},
            }
        ],
        commit=True,
    )
    assert result["ok"]
    cm: CodeMap = result["codemap"]
    summary = cm.summary()
    assert summary["has_host"]
    assert summary["has_kernel"]
    assert summary["has_host_kernel_path"]
    assert cm.by_kind(EntityKind.INPUT)
    assert cm.by_kind(EntityKind.TILING_KEY)
    assert cm.by_kind(EntityKind.KERNEL)

    path = Path(result["path"])
    assert path.is_file()
    assert path.suffix == ".uo"
    assert ".ascendc-pilot" in path.parts
    assert path.parent.name == "uo"

    loaded = read_codemap(path)
    assert loaded.by_kind(EntityKind.KERNEL)
    q = CodeMapQuery(codemap=loaded, path=str(path))
    trail = q.find_path("queryType", end_kind="KERNEL")
    assert trail, "expected INPUT/VARIABLE → … → KERNEL path"
    assert any(e.get("kind") == "KERNEL" for e in trail)


def test_reachability_pass_contract():
    from uo_init.clang_walk import CallSite, FuncRecord

    functions = {
        "A": FuncRecord(name="A", file="a.cpp", line=1),
        "B": FuncRecord(name="B", file="b.cpp", line=1),
        "C": FuncRecord(name="C", file="c.cpp", line=1),
    }
    sites = [
        CallSite(caller="A", callee="B", file="a.cpp", line=2),
        CallSite(caller="B", callee="C", file="b.cpp", line=3),
    ]
    reach = compute_reachable(functions, sites, frame_files=frozenset({"a.cpp"}))
    assert reach == frozenset({"A", "B", "C"})


def test_write_read_roundtrip(tmp_path: Path):
    cm = CodeMap(op_name="op", architecture="arch35")
    inp = cm.upsert(EntityKind.INPUT, "query")
    key = cm.upsert(EntityKind.TILING_KEY, "IsDtype")
    ker = cm.upsert(EntityKind.KERNEL, "K")
    cm.link(RelationKind.DERIVES, inp.id, key.id)
    cm.link(RelationKind.SELECTS, key.id, ker.id)
    out = tmp_path / "op.arch35.uo"
    written = write_codemap(cm, out)
    assert written["ok"]
    loaded = read_codemap(out)
    assert loaded.host_kernel_path_exists()
