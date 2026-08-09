from __future__ import annotations

from uo_init.diagnostics.audit import audit_codemap
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes import host_kernel, template


def _base_map() -> CodeMap:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(EntityKind.ARCH, "arch35")
    cm.upsert(EntityKind.INPUT, "query")
    cm.upsert(EntityKind.FUNCTION, "TilingFunc", attrs={"layer": "host"})
    cm.upsert(EntityKind.TILING_KEY, "IsRegbase")
    cm.upsert(EntityKind.TILING_KEY, "IsRope")
    cm.upsert(EntityKind.KERNEL, "KernelA")
    cm.upsert(EntityKind.KERNEL, "KernelB")
    return cm


def test_host_kernel_pass_does_not_invent_cartesian_selection() -> None:
    cm = _base_map()
    host_kernel.run(cm)
    semantic = [
        r
        for r in cm.relations.values()
        if r.kind_name() in {RelationKind.SELECTS.value, RelationKind.LAUNCHES.value}
    ]
    assert semantic == []
    assert cm.meta["has_evidence_backed_host_kernel_path"] is False


def test_template_pass_only_instantiates_explicit_kernel_target() -> None:
    cm = _base_map()
    template.run(
        cm,
        context={
            "template_bindings": [
                {
                    "template": "FagTemplate",
                    "instance": "FagTemplate<0>",
                    "tiling_key": "IsRegbase",
                    "kernel": "KernelA",
                    "args": {"MODE": 0},
                }
            ]
        },
    )
    instance = cm.by_name("FagTemplate<0>", kind=EntityKind.TEMPLATE_INSTANCE)[0]
    targets = {
        cm.entities[r.dst].name
        for r in cm.relations.values()
        if r.src == instance.id
        and r.kind_name() == RelationKind.INSTANTIATES.value
        and cm.entities.get(r.dst) is not None
        and cm.entities[r.dst].kind_name() == EntityKind.KERNEL.value
    }
    assert targets == {"KernelA"}


def test_audit_rejects_presence_without_real_path() -> None:
    report = audit_codemap(_base_map())
    assert report["ok"] is False
    codes = {item["code"] for item in report["blocking"]}
    assert "MISSING_EVIDENCE_BACKED_HOST_KERNEL_PATH" in codes


def test_audit_accepts_evidence_backed_input_to_kernel_path() -> None:
    cm = _base_map()
    query = cm.by_name("query", kind=EntityKind.INPUT)[0]
    key = cm.by_name("IsRegbase", kind=EntityKind.TILING_KEY)[0]
    kernel = cm.by_name("KernelA", kind=EntityKind.KERNEL)[0]
    cm.link(RelationKind.DERIVES, query.id, key.id, attrs={"provenance": "host_derivation"})
    cm.link(RelationKind.SELECTS, key.id, kernel.id, attrs={"provenance": "kernel_ir"})
    report = audit_codemap(cm)
    assert report["evidence_backed_host_kernel_path"] is True
    assert "MISSING_EVIDENCE_BACKED_HOST_KERNEL_PATH" not in {
        item["code"] for item in report["blocking"]
    }


def test_audit_rejects_universal_key_kernel_matrix() -> None:
    cm = _base_map()
    query = cm.by_name("query", kind=EntityKind.INPUT)[0]
    keys = cm.by_kind(EntityKind.TILING_KEY)
    kernels = cm.by_kind(EntityKind.KERNEL)
    cm.link(RelationKind.DERIVES, query.id, keys[0].id)
    for key in keys:
        for kernel in kernels:
            cm.link(RelationKind.SELECTS, key.id, kernel.id)
    report = audit_codemap(cm)
    assert "SUSPICIOUS_CARTESIAN_KEY_KERNEL" in {
        item["code"] for item in report["blocking"]
    }
