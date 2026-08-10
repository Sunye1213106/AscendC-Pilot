from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.host_defuse_validate import validate_host_defuse


def test_log_format_assignment_is_not_a_host_definition(tmp_path: Path) -> None:
    root = tmp_path / "toy"
    host = root / "op_host" / "arch35"
    host.mkdir(parents=True)
    source = host / "host.cpp"
    source.write_text(
        '''
        void F() {
          int real = inputValue;
          OP_LOGD("F", "blockIdx = %ld: actual = %f", real, 1.0f);
        }
        ''',
        encoding="utf-8",
    )

    cm = CodeMap(op_name="toy", architecture="arch35")
    real = cm.upsert(
        EntityKind.PREDICATE, "inputValue",
        eid="HOSTDEF::real",
        attrs={"predicate_role":"host_definition","lhs":"real","expression":"inputValue","provenance":"source_host_defuse"},
        file="toy/op_host/arch35/host.cpp", line=3, status="confirmed",
    )
    fake = cm.upsert(
        EntityKind.PREDICATE, '%ld: actual = %f", real, 1.0f)',
        eid="HOSTDEF::fake",
        attrs={"predicate_role":"host_definition","lhs":"blockIdx","expression":"%ld","provenance":"source_host_defuse"},
        file="toy/op_host/arch35/host.cpp", line=4, status="confirmed",
    )
    leaf = cm.upsert(
        EntityKind.VARIABLE, "ld", eid="HOSTUNRESOLVED::ld",
        attrs={"dependency_unresolved":True,"provenance":"source_host_unresolved_dependency"},
        file="toy/op_host/arch35/host.cpp", line=4, status="partial",
    )
    cm.link(RelationKind.DERIVES, leaf.id, fake.id, attrs={"provenance":"source_host_unresolved_dependency"}, status="partial")

    validate_host_defuse(cm, root, architecture="arch35")

    assert real.id in cm.entities
    assert fake.id not in cm.entities
    assert leaf.id not in cm.entities
    stats = cm.meta["host_defuse_validation"]
    assert stats["invalid_definition_nodes_removed"] == 1
    assert stats["dangling_dependency_nodes_removed"] == 1
