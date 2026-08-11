# -*- coding: utf-8 -*-
"""The manifest, the log protocol, and the engine not knowing an operator.

Protocol scrape tests use a fictional rich protocol embedded here — not a
real Ascend operator's field names.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from replay import manifest as M
from replay import runner as R

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "tests" / "fixtures"


# Fictional protocol for slots_of / parse_log machinery (not a real operator).
RICH_PROTOCOL = """\
version: 1
marks:
  case: '^###CASE (?P<case_id>\\S+)'
  done: '^###DONE (?P<case_id>\\S+) ok=(?P<ok>\\d+) key=(?P<key>\\d+)'
scrapes:
  - into: dim
    when: ["GetTilingKey"]
    pairs: '(\\w+)\\[(\\d+)\\]'
    fields: [DimA, DimB, EnableX]
  - into: state
    when: ["isExceed"]
    pairs: '(\\w+)\\[(\\d+)\\]'
  - into: state
    when: ["OpName:[GetSparseType]"]
    pairs: '(\\w+)\\s*=\\s*(-?\\d+)'
  - into: state
    when: ["OpName:[DoPreSfmgTiling]"]
    pairs: '(\\w+)\\s*(?:=|is)\\s*(-?\\d+)'
  - into: series
    name: sparse_parse_info
    when: ["Sparse idx"]
    each: 'idx\\s*=\\s*(?P<idx>\\d+).*?Begin\\s*=\\s*(?P<begin>\\d+).*?End\\s*=\\s*(?P<end>\\d+)'
reject:
  when: ["[ERROR]", "OpName:"]
  after: "OpName:"
  limit: 160
report_state:
  - StateCache
  - StateSwizzle
  - StateSparse
"""


@pytest.fixture(scope="module")
def toy_manifest() -> M.OperatorManifest:
    return M.OperatorManifest.load(
        FIXTURES / "_synthetic_toy" / "arch0" / "operator.yaml"
    )


@pytest.fixture
def rich_manifest(tmp_path: Path) -> M.OperatorManifest:
    return M.OperatorManifest.load(write_manifest(tmp_path, MINIMAL, RICH_PROTOCOL))


def write_manifest(tmp_path: Path, body: str, protocol: str = "") -> Path:
    pkg = tmp_path / "tests" / "fixtures" / "toy" / "arch1"
    pkg.mkdir(parents=True)
    (pkg / "operator.yaml").write_text(body, encoding="utf-8")
    (pkg / "log_protocol.yaml").write_text(
        protocol or "version: 1\nmarks:\n"
        "  case: '^###CASE (?P<case_id>\\S+)'\n"
        "  done: '^###DONE (?P<case_id>\\S+) ok=(?P<ok>\\d+) key=(?P<key>\\d+)'\n",
        encoding="utf-8")
    return pkg / "operator.yaml"


MINIMAL = """
version: 1
operator: {name: toy, path: family/toy, arch: arch1}
sources: {tiling_key_header: 'op_kernel/{arch}/{op}_tiling_key.h'}
replay: {host: wsl, distro: Some-Distro, entry: /run.sh, done_marker: FINISHED}
"""


def test_a_manifest_says_where_the_operator_lives(toy_manifest):
    assert toy_manifest.name == "_synthetic_toy"
    assert toy_manifest.arch == "arch0"
    assert toy_manifest.relative_path == "synthetic/toy"


def test_the_header_path_expands_the_operator_and_arch(tmp_path):
    got = M.OperatorManifest.load(write_manifest(tmp_path, MINIMAL))
    assert got.tiling_key_header == "op_kernel/arch1/toy_tiling_key.h"


def test_a_missing_required_key_says_which_one(tmp_path):
    body = MINIMAL.replace("path: family/toy, ", "")
    with pytest.raises(M.ManifestError, match="'path'"):
        M.OperatorManifest.load(write_manifest(tmp_path, body))


def test_the_environment_overrides_the_machine_specific_entries(
        tmp_path, monkeypatch):
    body = MINIMAL.replace(
        "entry: /run.sh,", "entry: /run.sh, overrides: {distro: TOY_DISTRO},")
    monkeypatch.setenv("TOY_DISTRO", "Another-Distro")
    got = M.OperatorManifest.load(write_manifest(tmp_path, body))
    assert got.distro == "Another-Distro"


def test_an_override_that_is_not_set_leaves_the_manifest_value(
        tmp_path, monkeypatch):
    body = MINIMAL.replace(
        "entry: /run.sh,", "entry: /run.sh, overrides: {distro: TOY_DISTRO},")
    monkeypatch.delenv("TOY_DISTRO", raising=False)
    assert M.OperatorManifest.load(
        write_manifest(tmp_path, body)).distro == "Some-Distro"


def test_a_manifest_that_is_not_there_says_where_it_looked(tmp_path):
    with pytest.raises(M.ManifestError, match="no manifest at"):
        M.OperatorManifest.load(tmp_path / "nowhere.yaml")


def test_fixture_packages_are_listed_explicitly():
    found = M.available_fixtures(REPO)
    assert ("_synthetic_toy", "arch0") in found
    assert not any(op == "flash_attention_score_grad" for op, _ in found)


def test_pilot_checkout_does_not_auto_discover_packages():
    assert M.available(REPO) == []


def test_a_scrape_must_name_a_slot_that_exists(tmp_path):
    protocol = ("version: 1\nmarks: {}\n"
                "scrapes:\n  - into: nonsense\n    pairs: '(\\w+)=(\\d+)'\n")
    with pytest.raises(M.ManifestError, match="expected one of"):
        M.OperatorManifest.load(write_manifest(tmp_path, MINIMAL, protocol))


def test_a_series_without_a_per_sample_pattern_is_refused(tmp_path):
    protocol = "version: 1\nmarks: {}\nscrapes:\n  - into: series\n    name: s\n"
    with pytest.raises(M.ManifestError, match="per-sample structure"):
        M.OperatorManifest.load(write_manifest(tmp_path, MINIMAL, protocol))


def test_a_mark_that_is_not_a_regex_says_so(tmp_path):
    protocol = "version: 1\nmarks:\n  case: '^###CASE ((('\n"
    with pytest.raises(M.ManifestError, match="not a regex"):
        M.OperatorManifest.load(write_manifest(tmp_path, MINIMAL, protocol))


def test_the_dimension_order_follows_the_declaration(rich_manifest):
    fields = rich_manifest.log.dim_fields
    assert fields[0] == "DimA"
    assert len(fields) == len(set(fields))


def test_a_value_and_an_intermediate_land_in_different_slots(rich_manifest):
    got = M.slots_of(rich_manifest.log, [
        "GetTilingKey DimA[2] DimB[1] notADimension[9]",
        "isExceed StateCache[1] StateSwizzle[0] StateSparse[3]",
    ])
    assert got["dim"] == {"DimA": 2, "DimB": 1}
    assert got["state"]["StateSparse"] == 3
    assert "notADimension" not in got["dim"]


def test_an_intermediate_line_is_not_filtered_to_a_declared_list(rich_manifest):
    got = M.slots_of(rich_manifest.log, ["isExceed StateCache[0] somethingNew[7]"])
    assert got["state"]["somethingNew"] == 7


def test_the_conditions_behind_the_sparse_type_are_collected(rich_manifest):
    line = ("OpName:[GetSparseType] denseCondition = 1, casualCondition = 0, "
            "bandCondition = 1, isS1GreaterThanS2 = 1, isS1LessThanS2 = 0")
    got = M.slots_of(rich_manifest.log, [line])
    assert got["state"]["denseCondition"] == 1
    assert got["state"]["casualCondition"] == 0
    assert got["state"]["isS1LessThanS2"] == 0


def test_a_line_mixing_equals_and_is_gives_up_both(rich_manifest):
    line = "OpName:[DoPreSfmgTiling] sfmgUsedCoreNum = 4, sfmgDyBufferLen is 56448"
    got = M.slots_of(rich_manifest.log, [line])
    assert got["state"] == {"sfmgUsedCoreNum": 4, "sfmgDyBufferLen": 56448}


def test_a_series_keeps_one_entry_per_sample(rich_manifest):
    got = M.slots_of(rich_manifest.log, [
        "Sparse idx = 0: Begin = 10, End = 20",
        "Sparse idx = 1: Begin = 20, End = 40",
    ])
    assert got["series"]["sparse_parse_info"] == [
        {"idx": 0, "begin": 10, "end": 20},
        {"idx": 1, "begin": 20, "end": 40},
    ]


def test_a_refusal_keeps_what_comes_after_the_operator_marker(rich_manifest):
    got = M.slots_of(rich_manifest.log,
                     ["[ERROR] something OpName:[Op] shape is wrong"])
    assert got["reject"] == "[Op] shape is wrong"


def test_a_line_naming_the_operator_without_an_error_is_not_a_refusal(rich_manifest):
    got = M.slots_of(rich_manifest.log, ["[INFO] OpName:[Op] all is well"])
    assert got["reject"] == ""


LOG = """\
###CASE c0
[INFO] GetTilingKey DimA[1] DimB[0]
[INFO] isExceed StateCache[1] StateSwizzle[0] StateSparse[2]
###DONE c0 ok=1 key=12345
###CASE c1
[ERROR] bad OpName:[Op] s1 must be positive
###DONE c1 ok=0 key=0
"""


def test_each_case_gets_only_its_own_lines(rich_manifest):
    got = R.ReplayRunner(rich_manifest).parse_log(LOG)
    assert set(got) == {"c0", "c1"}
    assert got["c0"].ok and got["c0"].key == 12345
    assert got["c0"].logged == {"DimA": 1, "DimB": 0}
    assert got["c0"].diag["StateSparse"] == 2
    assert not got["c1"].ok
    assert got["c1"].reject == "[Op] s1 must be positive"
    assert got["c1"].logged == {}


def test_output_before_the_first_case_belongs_to_no_case(rich_manifest):
    got = R.ReplayRunner(rich_manifest).parse_log(
        "[INFO] GetTilingKey DimA[9]\n" + LOG)
    assert got["c0"].logged == {"DimA": 1, "DimB": 0}


def test_a_case_the_driver_never_finished_is_still_reported(rich_manifest):
    got = R.ReplayRunner(rich_manifest).parse_log(
        "###CASE c9\n[INFO] GetTilingKey DimA[3]\n")
    assert got["c9"].logged == {"DimA": 3}
    assert not got["c9"].ok


def test_the_wide_table_columns_come_from_the_protocol(rich_manifest, monkeypatch):
    monkeypatch.setenv("UO_OPERATOR", "_synthetic_toy")
    monkeypatch.setenv("UO_ARCH", "arch0")
    from replay import inputs as I
    from replay import package_data

    package_data.clear_caches()
    I.reload()
    runner = R.ReplayRunner(rich_manifest)
    runner._parsed["dims"] = ["A", "B"]
    header = runner.wide_header()
    assert header[0] == "case_id"
    assert "dim_A" in header and "log_DimA" in header
    assert header[-4:] == ["StateCache", "StateSwizzle", "StateSparse", "reject"]


ENGINE = Path(R.__file__).parent
FORBIDDEN = [
    "flash_attention_score_grad", "FlashAttentionScoreGrad",
    "splitAxis", "isExceedL2Cache", "GetTilingKey", "GetSparseType",
    "sparseType", "enableSwizzle", "isTndSwizzle", "isNzOut",
    "Ubuntu", "BATCH_DONE", "run_replay.sh", "arch35",
    "QUERY", "PSE_SHIFT", "ATTEN_MASK", "ACTUAL_SEQ", "INPUT_FORMAT",
    "isTnd", "layoutType",
]


def _executable_source(path: Path) -> str:
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            body.pop(0)
    return ast.unparse(tree)


@pytest.mark.parametrize("module", ["runner.py", "manifest.py",
                                    "bridge_spec.py", "materialized.py",
                                    "contract_audit.py", "semantics.py"])
def test_the_engine_names_no_operator(module):
    code = _executable_source(ENGINE / module)
    offenders = [name for name in FORBIDDEN if name in code]
    assert offenders == [], (
        f"{module} names {offenders}; these belong in the operator package")


def test_the_default_runner_is_found_without_being_named(tmp_path):
    write_manifest(tmp_path, MINIMAL)
    assert R.manifest_path(tmp_path).parent.name == "arch1"


def test_several_packages_must_be_told_apart(tmp_path, monkeypatch):
    write_manifest(tmp_path, MINIMAL)
    other = tmp_path / "tests" / "fixtures" / "toy2" / "arch1"
    other.mkdir(parents=True)
    body2 = MINIMAL.replace("name: toy,", "name: toy2,")
    (other / "operator.yaml").write_text(body2, encoding="utf-8")
    (other / "log_protocol.yaml").write_text(
        "version: 1\nmarks: {}\n", encoding="utf-8"
    )
    monkeypatch.delenv("UO_OPERATOR", raising=False)
    monkeypatch.delenv("UO_ARCH", raising=False)
    with pytest.raises(M.ManifestError, match="several operator packages"):
        R.manifest_path(tmp_path)


def test_no_package_at_all_says_what_to_do(tmp_path, monkeypatch):
    monkeypatch.delenv("UO_OPERATOR", raising=False)
    monkeypatch.delenv("UO_ARCH", raising=False)
    with pytest.raises(M.ManifestError, match="no operator package"):
        R.manifest_path(tmp_path)


def test_the_module_level_names_still_resolve(monkeypatch):
    monkeypatch.setenv("UO_OPERATOR", "_synthetic_toy")
    monkeypatch.setenv("UO_ARCH", "arch0")
    R.reset()
    assert isinstance(R.CACHE, Path)
    assert R.MANIFEST.arch == "arch0"
    with pytest.raises(AttributeError):
        R.NOT_A_THING


def test_pointing_the_engine_at_another_operator_changes_what_it_reads(
        tmp_path, toy_manifest):
    other = M.OperatorManifest.load(write_manifest(tmp_path, MINIMAL))
    try:
        R.use(other)
        assert R.MANIFEST.name == "toy"
        assert R.LOG_FIELDS == []
    finally:
        R.use(toy_manifest)
    assert R.MANIFEST.name == "_synthetic_toy"
