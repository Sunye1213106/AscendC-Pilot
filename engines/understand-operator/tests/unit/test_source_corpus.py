from __future__ import annotations

from uo_init.source_corpus import ProcessLocalClangCache, SourceCorpus


def test_source_corpus_persists_only_source_facts(tmp_path) -> None:
    src = tmp_path / "op_host" / "x.cpp"
    src.parent.mkdir(parents=True)
    src.write_text('#include "x.h"\nvoid f() {}\n', encoding="utf-8")
    corpus = SourceCorpus(tmp_path)
    corpus.add(src, role="host")
    row = corpus.files["op_host/x.cpp"]
    assert row["role"] == "host"
    assert corpus.include_graph["op_host/x.cpp"] == ["x.h"]
    assert corpus.function_fingerprint("op_host/x.cpp", extractor_version="v1")
    cache = ProcessLocalClangCache(translation_units={"x": object()})
    cache.clear()
    assert not cache.translation_units
