# -*- coding: utf-8 -*-
"""The manifest, the log protocol, and the engine not knowing an operator.

The last of those is the point of P1 and the only one that can regress
silently: everything still works when a name creeps back into the engine, it
just stops working for the second operator, which nobody notices until there
is one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from replay import manifest as M
from replay import runner as R

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "tests" / "fixtures"


@pytest.fixture(scope="module")
def fag_manifest() -> M.OperatorManifest:
    return M.OperatorManifest.load(
        FIXTURES / "flash_attention_score_grad" / "arch35" / "operator.yaml")


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


# --- reading a manifest -------------------------------------------------


def test_a_manifest_says_where_the_operator_lives(fag_manifest):
    assert fag_manifest.name == "flash_attention_score_grad"
    assert fag_manifest.arch == "arch35"
    assert fag_manifest.relative_path == "attention/flash_attention_score_grad"


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
    assert ("flash_attention_score_grad", "arch35") in found
    assert ("_synthetic_toy", "arch0") in found


def test_pilot_checkout_does_not_auto_discover_packages():
    assert M.available(REPO) == []


# --- the log protocol ---------------------------------------------------


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


def test_the_dimension_order_follows_the_declaration(fag_manifest):
    fields = fag_manifest.log.dim_fields

    assert fields[0] == "splitAxis"
    assert len(fields) == len(set(fields))


def test_a_value_and_an_intermediate_land_in_different_slots(fag_manifest):
    got = M.slots_of(fag_manifest.log, [
        "GetTilingKey splitAxis[2] isTnd[1] notADimension[9]",
        "isExceedL2Cache[1] enableSwizzle[0] sparseType[3]",
    ])

    assert got["dim"] == {"splitAxis": 2, "isTnd": 1}
    assert got["state"]["sparseType"] == 3
    assert "notADimension" not in got["dim"]


def test_an_intermediate_line_is_not_filtered_to_a_declared_list(fag_manifest):
    """Naming a subset would drop whatever the operator starts logging next."""
    got = M.slots_of(fag_manifest.log,
                     ["isExceedL2Cache[0] somethingNew[7]"])

    assert got["state"]["somethingNew"] == 7


def test_the_conditions_behind_the_sparse_type_are_collected(fag_manifest):
    line = ("OpName:[GetSparseType] denseCondition = 1, casualCondition = 0, "
            "bandCondition = 1, isS1GreaterThanS2 = 1, isS1LessThanS2 = 0")

    got = M.slots_of(fag_manifest.log, [line])
    assert got["state"]["denseCondition"] == 1
    assert got["state"]["casualCondition"] == 0
    assert got["state"]["isS1LessThanS2"] == 0


def test_a_line_mixing_equals_and_is_gives_up_both(fag_manifest):
    line = "OpName:[DoPreSfmgTiling] sfmgUsedCoreNum = 4, sfmgDyBufferLen is 56448"

    got = M.slots_of(fag_manifest.log, [line])
    assert got["state"] == {"sfmgUsedCoreNum": 4, "sfmgDyBufferLen": 56448}


def test_a_series_keeps_one_entry_per_sample(fag_manifest):
    got = M.slots_of(fag_manifest.log, [
        "Sparse idx = 0: Begin = 10, End = 20",
        "Sparse idx = 1: Begin = 20, End = 40",
    ])

    assert got["series"]["sparse_parse_info"] == [
        {"idx": 0, "begin": 10, "end": 20},
        {"idx": 1, "begin": 20, "end": 40},
    ]


def test_a_refusal_keeps_what_comes_after_the_operator_marker(fag_manifest):
    """The host's own prefix is dropped; the operator's name is not."""
    got = M.slots_of(fag_manifest.log,
                     ["[ERROR] something OpName:[Op] shape is wrong"])

    assert got["reject"] == "[Op] shape is wrong"


def test_a_line_naming_the_operator_without_an_error_is_not_a_refusal(
        fag_manifest):
    got = M.slots_of(fag_manifest.log, ["[INFO] OpName:[Op] all is well"])

    assert got["reject"] == ""


# --- the runner reading a run -------------------------------------------


LOG = """\
###CASE c0
[INFO] GetTilingKey splitAxis[1] isTnd[0]
[INFO] isExceedL2Cache[1] enableSwizzle[0] sparseType[2]
###DONE c0 ok=1 key=12345
###CASE c1
[ERROR] bad OpName:[Op] s1 must be positive
###DONE c1 ok=0 key=0
"""


def test_each_case_gets_only_its_own_lines(fag_manifest):
    got = R.ReplayRunner(fag_manifest).parse_log(LOG)

    assert set(got) == {"c0", "c1"}
    assert got["c0"].ok and got["c0"].key == 12345
    assert got["c0"].logged == {"splitAxis": 1, "isTnd": 0}
    assert got["c0"].diag["sparseType"] == 2
    assert not got["c1"].ok
    assert got["c1"].reject == "[Op] s1 must be positive"
    assert got["c1"].logged == {}


def test_output_before_the_first_case_belongs_to_no_case(fag_manifest):
    got = R.ReplayRunner(fag_manifest).parse_log(
        "[INFO] GetTilingKey splitAxis[9]\n" + LOG)

    assert got["c0"].logged == {"splitAxis": 1, "isTnd": 0}


def test_a_case_the_driver_never_finished_is_still_reported(fag_manifest):
    got = R.ReplayRunner(fag_manifest).parse_log(
        "###CASE c9\n[INFO] GetTilingKey splitAxis[3]\n")

    assert got["c9"].logged == {"splitAxis": 3}
    assert not got["c9"].ok


def test_the_wide_table_columns_come_from_the_protocol(fag_manifest, monkeypatch):
    monkeypatch.setenv("UO_OPERATOR", "flash_attention_score_grad")
    monkeypatch.setenv("UO_ARCH", "arch35")
    from replay import inputs as I
    from replay import package_data

    package_data.clear_caches()
    I.reload()
    runner = R.ReplayRunner(fag_manifest)
    runner._parsed["dims"] = ["A", "B"]

    header = runner.wide_header()
    assert header[0] == "case_id"
    assert "dim_A" in header and "log_splitAxis" in header
    assert header[-4:] == ["isExceedL2Cache", "enableSwizzle", "sparseType",
                           "reject"]


# --- the engine does not know an operator -------------------------------

ENGINE = Path(R.__file__).parent
#: Names that only mean something for one operator, or one developer's box.
FORBIDDEN = [
    "flash_attention_score_grad", "FlashAttentionScoreGrad",
    "splitAxis", "isExceedL2Cache", "GetTilingKey", "GetSparseType",
    "sparseType", "enableSwizzle", "isTndSwizzle", "isNzOut",
    "Ubuntu", "BATCH_DONE", "run_replay.sh", "arch35",
    # P3: the bridge used to name every tensor and transcribe the layout
    # codes out of a header.
    "QUERY", "PSE_SHIFT", "ATTEN_MASK", "ACTUAL_SEQ", "INPUT_FORMAT",
    "isTnd", "layoutType",
]


def _executable_source(path: Path) -> str:
    """The module with its prose removed.

    Docstrings and comments are allowed to say which operator a piece of
    history was about; that is explanation, not behaviour. What must not
    survive is a name the engine acts on.
    """
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
    """A name here works today and only fails on the second operator."""
    code = _executable_source(ENGINE / module)
    offenders = [name for name in FORBIDDEN if name in code]

    assert offenders == [], (
        f"{module} names {offenders}; these belong in the operator package")


def test_the_default_runner_is_found_without_being_named(tmp_path):
    """A repository with one package needs no environment to say which."""
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
    """Twenty-odd scripts read these; they must survive the manifest."""
    monkeypatch.setenv("UO_OPERATOR", "flash_attention_score_grad")
    monkeypatch.setenv("UO_ARCH", "arch35")
    R.reset()
    assert isinstance(R.CACHE, Path)
    assert R.LOG_FIELDS[0] == "splitAxis"
    assert R.MANIFEST.arch == "arch35"
    with pytest.raises(AttributeError):
        R.NOT_A_THING


def test_pointing_the_engine_at_another_operator_changes_what_it_reads(
        tmp_path, fag_manifest):
    other = M.OperatorManifest.load(write_manifest(tmp_path, MINIMAL))
    try:
        R.use(other)
        assert R.MANIFEST.name == "toy"
        assert R.LOG_FIELDS == []
    finally:
        R.use(fag_manifest)
    assert R.MANIFEST.name == "flash_attention_score_grad"
