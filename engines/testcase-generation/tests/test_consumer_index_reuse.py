"""Consumer index reuse across TG evidence passes."""

from __future__ import annotations

from pathlib import Path

from testcase_agent.consumer_index import load_or_build_consumer_index


def test_consumer_index_reuse(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "gen_csv.py").write_text(
        "COLUMNS = ['Input_Layout', 'keep_prob']\n"
        "def get_column_index(name):\n"
        "    return COLUMNS.index(name)\n",
        encoding="utf-8",
    )
    out_root = tmp_path / "tg"
    (out_root / "realization").mkdir(parents=True)

    first = load_or_build_consumer_index(out_root, consumer)
    assert first.source_read_count >= 1
    assert first.ast_parse_count >= 1

    second = load_or_build_consumer_index(out_root, consumer)
    assert second.source_read_count == 0
    assert second.ast_parse_count == 0
    assert second.files == first.files
