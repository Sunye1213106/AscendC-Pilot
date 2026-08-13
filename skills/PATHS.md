# PATHS

TG ↔ UO hard isolation. Paths below are under `.ascendc-pilot/<arch>/`.

`<arch>`：**`/uo-init` 必须显式选择**（从算子仓 `op_host/arch*` / `op_kernel/arch*` 发现，无静默默认）。TG / CE 使用已有 `.uo` 所在的 `<arch>`，不再从源码目录另选。

| Root | Path | Access |
| --- | --- | --- |
| UO_ROOT | `.ascendc-pilot/<arch>/uo` | TG 只读（含正式 `*.uo`） |
| TG_ROOT / OUT_ROOT | `.ascendc-pilot/<arch>/tg` | TG 读写 |
| CE_ROOT | `.ascendc-pilot/<arch>/ce` | CE 读写 |

Legacy markers (refused, not auto-migrated): `.ascendc-agent`, `.understand-operator`, top-level `.ascendc-pilot/uo/*.uo`. Move into `.ascendc-pilot/<arch>/` by hand.

硬隔离：禁止 TG 写入 UO_ROOT。
