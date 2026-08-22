from pathlib import Path
from uo_init.uo_query import open_query
from uo_init.store.reader import close_uo_connections
import json

root = Path(r"d:\TEST\ops-transformer\gmm\grouped_matmul")
q = open_query(root, architecture="arch35")
out = q.agent_query(pattern="LocalTensor")
print(json.dumps({
    "ok": out.get("ok"),
    "count": out.get("count"),
    "cards": [
        {
            "kind": c.get("kind"),
            "name": c.get("name"),
            "id": c.get("id"),
            "file": c.get("file"),
            "line": c.get("line"),
            "catalog": (c.get("extras") or {}).get("catalog"),
            "snippet": (c.get("snippet") or "")[:160],
        }
        for c in (out.get("cards") or [])
    ],
}, ensure_ascii=False, indent=2))
q.close()
close_uo_connections()
