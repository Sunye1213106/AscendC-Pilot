from __future__ import annotations

from pathlib import Path

from uo_init.diagnostics.audit import audit_codemap
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes import compile_time
from uo_init.passes.host_defuse import _function_scopes, _identifiers, trace_host_key_roots
from uo_init.passes.host_tiling_key import bind_host_tiling_key_expressions
from uo_init.passes.symbol_identity import normalize_symbol


def _host_root(tmp_path: Path) -> Path:
    root = tmp_path / "toy"
    (root / "op_host" / "arch35").mkdir(parents=True)
    return root


def test_member_identity_strips_this_without_using_bare_initializer(tmp_path: Path) -> None:
    root = _host_root(tmp_path)
    (root / "op_host" / "arch35" / "toy.h").write_text(
        """
        struct Params { bool isNzOut = false; };
        enum class Mode { OFF = 0, ON = 1 };
        """,
        encoding="utf-8",
    )
    (root / "op_host" / "arch35" / "toy.cpp").write_text(
        """
        void T::DoOpTiling() {
          fBaseParams.isNzOut = context_->GetInputDesc(0)->GetDataType() == ge::DT_FLOAT;
        }
        uint64_t T::GetTilingKey() const {
          return GET_TPL_TILING_KEY(fBaseParams.isNzOut);
        }
        """,
        encoding="utf-8",
    )

    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(EntityKind.ARCH, "arch35")
    cm.upsert(EntityKind.INPUT, "query", attrs={"api_kind": "tensor", "api_index": 0, "provenance": "source_reg_op"})
    key = cm.upsert(EntityKind.TILING_KEY, "IsNzOut", attrs={"source_declared": True, "decl_order": 0})
    field = cm.upsert(EntityKind.FIELD, "this.fBaseParams.isNzOut", attrs={"layer": "host"})

    bind_host_tiling_key_expressions(cm, root)
    trace_host_key_roots(cm, root)

    assert normalize_symbol(field.name) == "fBaseParams.isNzOut"
    assert field.attrs.get("host_key_argument") is True
    sites = field.attrs.get("producer_sites") or []
    assert any(site.get("file", "").endswith("toy.cpp") and site.get("lhs") == "fBaseParams.isNzOut" for site in sites)
    assert not any(site.get("file", "").endswith("toy.h") for site in sites)
    assert not any(site.get("lhs") == "isNzOut" for site in sites)
    assert field.attrs.get("rooted_by_current_source") is True

    packing = [
        r for r in cm.relations.values()
        if r.dst == key.id and r.kind_name() == RelationKind.DERIVES.value
        and r.attrs.get("provenance") == "source_get_tpl_tiling_key"
    ]
    assert len(packing) == 1


def test_member_short_name_never_aliases_back_to_member_target(tmp_path: Path) -> None:
    root = _host_root(tmp_path)
    (root / "op_host" / "arch35" / "toy.h").write_text(
        "struct Params { bool x = false; };\n",
        encoding="utf-8",
    )
    (root / "op_host" / "arch35" / "toy.cpp").write_text(
        """
        void T::DoOpTiling() {
          local = x;
          fBaseParams.x = local;
        }
        uint64_t T::GetTilingKey() const {
          return GET_TPL_TILING_KEY(fBaseParams.x);
        }
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(EntityKind.INPUT, "query", attrs={"api_kind": "tensor", "api_index": 0})
    cm.upsert(EntityKind.TILING_KEY, "X", attrs={"source_declared": True, "decl_order": 0})
    member = cm.upsert(EntityKind.FIELD, "this.fBaseParams.x")
    bind_host_tiling_key_expressions(cm, root)
    trace_host_key_roots(cm, root)
    sites = member.attrs.get("producer_sites") or []
    assert {site.get("lhs") for site in sites} == {"fBaseParams.x"}


def test_ambiguous_short_name_is_not_linked_to_every_entity(tmp_path: Path) -> None:
    root = _host_root(tmp_path)
    (root / "op_host" / "arch35" / "toy.cpp").write_text(
        "uint64_t T::GetTilingKey() const { return GET_TPL_TILING_KEY(x); }\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    key = cm.upsert(EntityKind.TILING_KEY, "K", attrs={"source_declared": True, "decl_order": 0})
    foo = cm.upsert(EntityKind.FIELD, "foo.x")
    bar = cm.upsert(EntityKind.FIELD, "bar.x")

    bind_host_tiling_key_expressions(cm, root)
    packing_node = next(
        cm.entities[r.src] for r in cm.relations.values()
        if r.dst == key.id and r.attrs.get("provenance") == "source_get_tpl_tiling_key"
    )
    incoming = [r for r in cm.relations.values() if r.dst == packing_node.id]
    assert not any(r.src in {foo.id, bar.id} for r in incoming)
    assert any(cm.entities[r.src].attrs.get("host_key_argument") for r in incoming if r.src in cm.entities)


def test_identifier_scan_ignores_strings_cast_types_and_calls() -> None:
    expr = '''
      strcmp(inputLayout, "TND") == 0 &&
      tensor.GetData<int64_t>() != nullptr &&
      static_cast<optiling::DtypeEnum>(queryType) == optiling::DtypeEnum::FLOAT16 &&
      /* all but fake words */ realValue > 0 // same set fake words
    '''
    identifiers = set(_identifiers(expr))
    assert "inputLayout" in identifiers
    assert "queryType" in identifiers
    assert "realValue" in identifiers
    assert "optiling::DtypeEnum::FLOAT16" in identifiers
    for noise in ("TND", "tensor.GetData", "int64_t", "optiling::DtypeEnum", "all", "but", "fake", "words", "same", "set"):
        assert noise not in identifiers


def test_function_scope_parser_does_not_name_control_statement_if() -> None:
    text = """
    void T::Run() {
      if (x) {
        y = 1;
      }
    }
    """
    scopes = _function_scopes(text)
    assert [scope.name for scope in scopes] == ["T::Run"]


def test_compile_time_does_not_promote_uppercase_branch_spelling() -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    br = cm.upsert(EntityKind.BRANCH, "x == BN2", attrs={"condition": "x == BN2"})
    compile_time.run(cm)
    assert not cm.by_name("BN2", kind=EntityKind.COMPILE_VAR)
    assert not any(r.dst == br.id and r.kind_name() == RelationKind.CONTROLS.value for r in cm.relations.values())


def test_audit_rejects_branch_only_fake_key_root() -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.meta["source_declared_tiling_key_count"] = 1
    cm.meta["host_tiling_key_packing"] = {"calls": 1, "fields_bound": 1, "argument_count_mismatches": []}
    cm.upsert(EntityKind.ARCH, "arch35")
    cm.upsert(EntityKind.INPUT, "query", attrs={"api_kind": "tensor", "api_index": 0})
    cm.upsert(EntityKind.OUTPUT, "out")
    cm.upsert(EntityKind.TILING_DATA, "TD")
    cm.upsert(EntityKind.TILING_FIELD, "x")
    cm.upsert(EntityKind.KERNEL, "K")
    key = cm.upsert(EntityKind.TILING_KEY, "SplitAxis", attrs={"source_declared": True, "decl_order": 0, "host_packing_expressions": ["splitAxis"]})
    packing = cm.upsert(EntityKind.PREDICATE, "splitAxis", attrs={"predicate_role": "host_tiling_key_argument", "expression": "splitAxis"})
    runtime = cm.upsert(EntityKind.FIELD, "fBaseParams.splitAxis", attrs={"host_key_argument": True})
    branch = cm.upsert(EntityKind.BRANCH, "mode == BN2")
    constant = cm.upsert(EntityKind.COMPILE_VAR, "BN2", attrs={"compile_root": True, "provenance": "source_enum"})
    cm.link(RelationKind.DERIVES, packing.id, key.id, attrs={"provenance": "source_get_tpl_tiling_key"})
    cm.link(RelationKind.DERIVES, runtime.id, packing.id, attrs={"provenance": "source_get_tpl_tiling_key_symbol"})
    cm.link(RelationKind.CONTROLS, constant.id, branch.id)
    cm.link(RelationKind.CONTROLS, branch.id, runtime.id)

    report = audit_codemap(cm)
    codes = {item["code"] for item in report["blocking"]}
    assert "MISSING_HOST_TILINGKEY_PRODUCERS" in codes
    assert "UNROOTED_TILING_KEYS" in codes
    assert report["summary"]["tiling_key_host_producer_coverage"] == "0/1"
    assert report["summary"]["tiling_key_root_coverage"] == "0/1"


def test_audit_accepts_source_producer_root_chain() -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.meta["source_declared_tiling_key_count"] = 1
    cm.meta["host_tiling_key_packing"] = {"calls": 1, "fields_bound": 1, "argument_count_mismatches": []}
    query = cm.upsert(EntityKind.INPUT, "query", attrs={"api_kind": "tensor", "api_index": 0, "provenance": "source_reg_op"})
    key = cm.upsert(EntityKind.TILING_KEY, "SplitAxis", attrs={"source_declared": True, "decl_order": 0, "host_packing_expressions": ["splitAxis"]})
    packing = cm.upsert(EntityKind.PREDICATE, "splitAxis", attrs={"predicate_role": "host_tiling_key_argument", "expression": "splitAxis"})
    runtime = cm.upsert(
        EntityKind.FIELD,
        "fBaseParams.splitAxis",
        attrs={"host_key_argument": True, "producer_site_count": 1, "producer_sites": [{"file": "op_host/arch35/a.cpp", "line": 10}]},
    )
    producer = cm.upsert(EntityKind.PREDICATE, "query dependent", attrs={"predicate_role": "host_definition"})
    cm.link(RelationKind.DERIVES, query.id, producer.id, attrs={"provenance": "source_host_api_accessor"})
    cm.link(RelationKind.DERIVES, producer.id, runtime.id, attrs={"provenance": "source_host_defuse"})
    cm.link(RelationKind.DERIVES, runtime.id, packing.id, attrs={"provenance": "source_get_tpl_tiling_key_symbol"})
    cm.link(RelationKind.DERIVES, packing.id, key.id, attrs={"provenance": "source_get_tpl_tiling_key"})

    report = audit_codemap(cm)
    assert report["summary"]["tiling_key_host_producer_coverage"] == "1/1"
    assert report["summary"]["tiling_key_root_coverage"] == "1/1"
    assert report["tiling_key_evidence"][0]["producer_sites"]


def test_member_packed_from_input_null_check_has_producer(tmp_path: Path) -> None:
    root = _host_root(tmp_path)
    (root / "op_host" / "arch35" / "toy.cpp").write_text(
        """
        void T::DoOpTiling() {
          obj.flag = input != nullptr;
        }
        uint64_t T::GetTilingKey() const {
          return GET_TPL_TILING_KEY(obj.flag);
        }
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(EntityKind.INPUT, "input", attrs={"api_kind": "tensor", "api_index": 0, "provenance": "source_reg_op"})
    cm.upsert(EntityKind.TILING_KEY, "HasInput", attrs={"source_declared": True, "decl_order": 0})
    field = cm.upsert(EntityKind.FIELD, "obj.flag")

    bind_host_tiling_key_expressions(cm, root)
    trace_host_key_roots(cm, root)

    assert field.attrs.get("host_key_argument") is True
    assert int(field.attrs.get("producer_site_count") or 0) >= 1
    assert field.attrs.get("rooted_by_current_source") is True
    assert field.attrs.get("upstream_unresolved") is not True


def test_packing_local_is_not_stolen_by_same_named_tiling_field(tmp_path: Path) -> None:
    root = _host_root(tmp_path)
    (root / "op_host" / "arch35" / "mode.h").write_text(
        "enum class Mode { OFF = 0, ON = 1 };\n",
        encoding="utf-8",
    )
    (root / "op_host" / "arch35" / "toy.cpp").write_text(
        """
        uint64_t T::GetTilingKey() const {
          Mode flag = Mode::OFF;
          if (cond) {
            flag = Mode::ON;
          }
          return GET_TPL_TILING_KEY(static_cast<uint8_t>(flag));
        }
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(EntityKind.INPUT, "query", attrs={"api_kind": "tensor", "api_index": 0, "provenance": "source_reg_op"})
    key = cm.upsert(EntityKind.TILING_KEY, "Flag", attrs={"source_declared": True, "decl_order": 0})
    td_field = cm.upsert(
        EntityKind.TILING_FIELD,
        "flag",
        eid="TDF::SomeTilingData::flag",
        attrs={"owner": "SomeTilingData"},
    )

    bind_host_tiling_key_expressions(cm, root)
    trace_host_key_roots(cm, root)

    packing = next(
        cm.entities[r.src]
        for r in cm.relations.values()
        if r.dst == key.id and r.attrs.get("provenance") == "source_get_tpl_tiling_key"
    )
    sources = [
        cm.entities[r.src]
        for r in cm.relations.values()
        if r.dst == packing.id and r.attrs.get("provenance") == "source_get_tpl_tiling_key_symbol"
    ]
    assert td_field.id not in {e.id for e in sources}
    assert any(e.kind_name() == EntityKind.VARIABLE.value and e.attrs.get("host_key_argument") for e in sources)
    host = next(e for e in sources if e.kind_name() == EntityKind.VARIABLE.value)
    assert int(host.attrs.get("producer_site_count") or 0) >= 1
    assert host.attrs.get("rooted_by_current_source") is True


def test_audit_ignores_non_declared_extra_tiling_keys() -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.meta["source_declared_tiling_key_count"] = 1
    cm.meta["host_tiling_key_packing"] = {"calls": 1, "fields_bound": 1, "argument_count_mismatches": []}
    query = cm.upsert(EntityKind.INPUT, "query", attrs={"api_kind": "tensor", "api_index": 0, "provenance": "source_reg_op"})
    key = cm.upsert(EntityKind.TILING_KEY, "SplitAxis", attrs={"source_declared": True, "decl_order": 0, "host_packing_expressions": ["splitAxis"]})
    packing = cm.upsert(EntityKind.PREDICATE, "splitAxis", attrs={"predicate_role": "host_tiling_key_argument", "expression": "splitAxis"})
    runtime = cm.upsert(
        EntityKind.FIELD,
        "fBaseParams.splitAxis",
        attrs={"host_key_argument": True, "producer_site_count": 1, "producer_sites": [{"file": "op_host/arch35/a.cpp", "line": 10}]},
    )
    producer = cm.upsert(EntityKind.PREDICATE, "query dependent", attrs={"predicate_role": "host_definition"})
    cm.upsert(EntityKind.TILING_KEY, "TemplateExtra", attrs={"source_declared": False})
    cm.link(RelationKind.DERIVES, query.id, producer.id, attrs={"provenance": "source_host_api_accessor"})
    cm.link(RelationKind.DERIVES, producer.id, runtime.id, attrs={"provenance": "source_host_defuse"})
    cm.link(RelationKind.DERIVES, runtime.id, packing.id, attrs={"provenance": "source_get_tpl_tiling_key_symbol"})
    cm.link(RelationKind.DERIVES, packing.id, key.id, attrs={"provenance": "source_get_tpl_tiling_key"})

    report = audit_codemap(cm)
    codes = {item["code"] for item in report["blocking"]}
    assert "TILING_KEY_CARDINALITY_MISMATCH" not in codes
