from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8")


def patch_resolver() -> None:
    rel = "engines/understand-operator/uo/scripts/resolve_entrypoints.py"
    text = read(rel)
    if "def _registration_scan_paths(" not in text:
        marker = '''def _scan_registration_graph(
    repo_root: Path,
    confirmed_files: list[str],
    architecture: str,
    existing_nodes: dict[str, dict[str, Any]],
    *,
    op_name: str = "",
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
'''
        helper = '''def _registration_scan_paths(
    repo_root: Path,
    confirmed_files: list[str],
    architecture: str,
) -> list[Path]:
    """Return scoped registration sources, with a safe first-run fallback.

    Confirmed scope remains authoritative when it contains host/graph files.
    A fresh repository has no scope ledger or CBM metadata yet, so inspect
    only compatible ``op_host`` and ``op_graph`` C/C++ sources instead of
    silently producing an empty registration graph.
    """
    suffixes = {".h", ".hpp", ".cpp", ".cc", ".c"}
    paths: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | None) -> None:
        if path is None or not path.is_file() or path.suffix not in suffixes:
            return
        try:
            rel = to_repo_relative(repo_root, path)
        except Exception:  # noqa: BLE001
            rel = path.as_posix()
        rel_n = rel.replace("\\\\", "/")
        if not arch_compatible(rel_n, architecture):
            return
        key = path.resolve().as_posix()
        if key in seen:
            return
        seen.add(key)
        paths.append(path)

    if confirmed_files:
        for rel in confirmed_files:
            rel_n = str(rel).replace("\\\\", "/")
            if not (_path_has_dir(rel_n, "op_host") or _path_has_dir(rel_n, "op_graph")):
                continue
            add(_resolve_source_file(repo_root, rel_n, architecture=architecture))
        if paths:
            return sorted(paths, key=lambda p: p.as_posix())

    for dirname in ("op_host", "op_graph"):
        base = repo_root / dirname
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            add(path)
    return sorted(paths, key=lambda p: p.as_posix())


''' + marker
        if marker not in text:
            raise RuntimeError("registration function marker missing")
        text = text.replace(marker, helper, 1)

    old = '''    for rel in confirmed_files:
        path = _resolve_source_file(repo_root, rel, architecture=architecture)
        if path is None:
            continue
        try:
            repo_rel = to_repo_relative(repo_root, path)
        except Exception:  # noqa: BLE001
            repo_rel = rel.replace("\\\\", "/")
'''
    new = '''    for path in _registration_scan_paths(repo_root, confirmed_files, architecture):
        try:
            repo_rel = to_repo_relative(repo_root, path)
        except Exception:  # noqa: BLE001
            repo_rel = path.as_posix()
'''
    if old in text:
        text = text.replace(old, new, 1)
    elif new not in text:
        raise RuntimeError("registration loop marker missing")
    write(rel, text)


def patch_proposal() -> None:
    rel = "engines/understand-operator/uo/scripts/propose_extract_plan.py"
    text = read(rel)
    old = 'MAX_NON_SINK = _env_limit("UO_EXTRACT_MAX_NON_SINK", 120)'
    new = 'MAX_NON_SINK = _env_limit("UO_EXTRACT_MAX_NON_SINK", 512)'
    if old in text:
        text = text.replace(old, new, 1)
    elif new not in text:
        raise RuntimeError("non-sink default marker missing")
    write(rel, text)


def patch_tests() -> None:
    rel = "engines/understand-operator/tests/test_fag_graph_identity_and_perf.py"
    text = read(rel)
    if "collect_entrypoint_candidates" not in text:
        text = text.replace(
            "from uo.scripts.extract_host_subgraph import _chain_item_key, _writer_role_indexes\n",
            "from uo.scripts.extract_host_subgraph import _chain_item_key, _writer_role_indexes\n"
            "from uo.scripts.resolve_entrypoints import collect_entrypoint_candidates\n"
            "from uo.scripts.propose_extract_plan import MAX_NON_SINK\n",
            1,
        )
    if "test_fresh_repo_scans_neutral_host_registration_without_scope" not in text:
        text += '''


def test_fresh_repo_scans_neutral_host_registration_without_scope(tmp_path: Path) -> None:
    host = tmp_path / "op_host" / "flash_attention_score_grad_tiling.cpp"
    host.parent.mkdir(parents=True)
    host.write_text(
        """ge::graphStatus TilingFlashAttentionGradScore(gert::TilingContext *context) {
    return ge::GRAPH_SUCCESS;
}
IMPL_OP_OPTILING(FlashAttentionScoreGrad)
    .Tiling(TilingFlashAttentionGradScore);
""",
        encoding="utf-8",
    )
    doc = collect_entrypoint_candidates(
        tmp_path, "flash_attention_score_grad", architecture="arch35"
    )
    graph = doc["entrypoint_graph"]
    roles = {str(node.get("role")) for node in graph.get("nodes") or []}
    names = {str(node.get("name")) for node in graph.get("nodes") or []}
    assert "public_host_entry" in roles
    assert "FlashAttentionScoreGrad" in names
    assert "TilingFlashAttentionGradScore" in names
    assert any(
        edge.get("type") == "dispatches_to"
        and edge.get("confidence") == "source_verified"
        for edge in graph.get("edges") or []
    )


def test_default_non_sink_budget_covers_real_fag_candidate_volume() -> None:
    assert MAX_NON_SINK >= 177
'''
    write(rel, text)


def main() -> None:
    patch_resolver()
    patch_proposal()
    patch_tests()
    print("real FAG discovery fixes applied")


if __name__ == "__main__":
    main()
