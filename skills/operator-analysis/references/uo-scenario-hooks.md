# UO query hooks for scenarios

**When to load**：给 CE 推断场景之前选 `uo-query` mode。  
场景 id 以 `skills/code-engineering/references/scenario-catalog.md` 为准，此处不复制 attach 表。

UO 只定位结构。不判断 golden、happens-before、profiler。结构事实可以答完；根因仍 PARTIAL。

| 要找什么 | mode |
| --- | --- |
| Cast / DataCopy / DataCopyPad / EnQue / DeQue | `kernel_api` |
| INPUT dtype | `search` INPUT/OUTPUT |
| Buffer / queue 方向 / 3buff / 4buff | `buffer`（看 `mutex_policy`） |
| 切分字段写点 / 公式 / 占核 | `field`（问句标识符；空则 `local_aliases`） / `tiling_data` |
| kernel 找不到 / 561003 / 某维有没有编 | `template_match` → `legal_key`（必须看 `dim_coverage` / `total_matched`） |
| Pre / Main / Post / 三相 launch | `kernel_launch`；禁止先搜 `Process` / `*_apt.cpp` |
| SetScheduleMode / Host TilingContext | `locate`；不是 `kernel_api` |
| 同名函数 / virtual override | `locate` 短名（全部 `definition_sites`） |
| diff 邻域 | `impact` |
| tail / 运行时分支 | `kernel_branch` |

Flag 配对只是 identity 级出现；TQue 的 EnQue/DeQue 不走那条检查。
空图命中按 `hint` 再查；禁止 `findstr /S`。最后才 `acp ro-search --paths <已 citation 文件>`。
