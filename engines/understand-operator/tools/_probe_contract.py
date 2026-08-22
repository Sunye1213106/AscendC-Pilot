# -*- coding: utf-8 -*-
from pathlib import Path
import sqlite3

from uo_init.store.reader import find_uo_product
from uo_init.uo_query import open_query

OPS = {
    "FAG": Path(r"d:\TEST\ops-transformer\attention\flash_attention_score_grad"),
    "NSA": Path(r"d:\TEST\ops-transformer\attention\nsa_compress"),
    "GMM": Path(r"d:\TEST\ops-transformer\gmm\grouped_matmul"),
    "IFA": Path(r"d:\TEST\ops-transformer\attention\incre_flash_attention"),
}


def probe(name: str, root: Path) -> dict:
    product = find_uo_product(root, architecture="arch35")
    conn = sqlite3.connect(f"file:{Path(product).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    catalog = conn.execute(
        """
        SELECT name, kind, json_extract(data, '$.catalog') AS catalog,
               json_extract(data, '$.role') AS role
        FROM entity
        WHERE json_extract(data, '$.catalog') = 'ge.graphStatus'
        ORDER BY name
        """
    ).fetchall()
    spans = conn.execute(
        """
        SELECT COUNT(*) AS n,
               SUM(CASE WHEN line_end > line_start THEN 1 ELSE 0 END) AS wide
        FROM entity
        WHERE kind IN ('FUNCTION','METHOD','KERNEL')
        """
    ).fetchone()
    rooted = conn.execute(
        """
        SELECT json_extract(data, '$.provenance') AS prov, COUNT(*) AS n
        FROM relation
        WHERE kind = 'ROOTED_AT'
        GROUP BY prov
        """
    ).fetchall()
    conn.close()
    q = open_query(root, architecture="arch35")
    failed = q.agent_query(pattern="GRAPH_FAILED")
    empty = q.agent_query(pattern="ImpossibleCoverDimXYZ")
    cover = empty if False else q.agent_query(pattern="Dim=__no_such_dim__")
    q.close()
    cards = failed.get("cards") or []
    return {
        "op": name,
        "product": str(product),
        "catalog_roots": [dict(r) for r in catalog],
        "fn_span": dict(spans),
        "rooted_at": [dict(r) for r in rooted],
        "graph_failed_kinds": [c.get("kind") for c in cards],
        "graph_failed_catalog": [
            (c.get("extras") or {}).get("catalog") for c in cards
        ],
        "graph_failed_ok": failed.get("ok"),
        "empty_cover_completeness": cover.get("completeness"),
        "empty_cover_matching": cover.get("matching_block_count"),
    }


if __name__ == "__main__":
    import json
    from uo_init.store.reader import close_uo_connections

    out = []
    for name, root in OPS.items():
        try:
            out.append(probe(name, root))
        except Exception as exc:  # noqa: BLE001
            out.append({"op": name, "error": str(exc)[:400]})
        close_uo_connections()
    print(json.dumps(out, ensure_ascii=False, indent=2))
