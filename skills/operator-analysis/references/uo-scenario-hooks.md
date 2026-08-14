# UO query hooks for scenarios

**When to load**：给 CE 推断场景之前选 `uo-query` mode。  
场景 id 以 `skills/code-engineering/references/scenario-catalog.md` 为准，此处不复制 attach 表。

UO 只定位结构。不判断 golden、happens-before、profiler。

| 要找什么 | mode |
| --- | --- |
| Cast / DataCopy / DataCopyPad / EnQue / DeQue | `kernel_api` |
| INPUT dtype | `search` INPUT/OUTPUT |
| Buffer / queue 方向 | `buffer` |
| 切分字段写点 / 公式 | `field` / `tiling_data` |
| diff 邻域 | `impact` |
| tail / 运行时分支 | `kernel_branch` |

Flag 配对只是 identity 级出现；TQue 的 EnQue/DeQue 不走那条检查。
