# PATHS

TG ↔ UO hard isolation. Paths below are under `.ascendc-pilot/<arch>/`.

| Root | Path | Access |
| --- | --- | --- |
| UO_ROOT | `.ascendc-pilot/<arch>/uo` | TG 只读（含正式 `*.uo`） |
| TG_ROOT / OUT_ROOT | `.ascendc-pilot/<arch>/tg` | TG 读写 |
| CE_ROOT | `.ascendc-pilot/<arch>/ce` | CE 读写 |

Legacy markers (resolve only): `.ascendc-agent`, `.understand-operator`, top-level `.ascendc-pilot/uo/*.uo` (migrated into `<arch>/uo/`).

硬隔离：禁止 TG 写入 UO_ROOT。
