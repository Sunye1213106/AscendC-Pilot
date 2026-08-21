# TG Solve — Gotchas

- **正式产物是 `worklog.md` + cases 表**：不要再写 `tg/closure/**` 证书森林。
- **cases 必须脚本可直接吃**：填满 `init.yaml` 列；现有 runner 用 `--case` 跑。
- **Host Replay 无 NPU**：只看 tiling key / TD / OP_CHECK / 分支。`Replay reject ≠ E`。
- **worklog 文首 `open:`**：每 case 四段（场景与命中、构造、收窄、引理）。open 非空不得签发。
- **引理 span 来自 uo-query**：Grep 只作定位辅助，禁止把 Host reject 写成不可达证明。
- **需要改构造就保持 open**：不要假装闭合。
