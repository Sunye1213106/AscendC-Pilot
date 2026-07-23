# PATHS

TG ↔ UO hard isolation.

| Root | Path | Access |
| --- | --- | --- |
| UO_ROOT | `.ascendc-pilot/uo` | TG 只读 |
| TG_ROOT / OUT_ROOT | `.ascendc-pilot/tg` | TG 读写 |
| CE_ROOT | `.ascendc-pilot/ce` | CE 读写 |

Legacy markers (resolve only): `.ascendc-agent`, `.understand-operator`.

硬隔离：禁止 TG 写入 UO_ROOT。
