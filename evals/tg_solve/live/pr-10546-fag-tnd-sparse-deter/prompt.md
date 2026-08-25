<task>
你是 Solve Owner。Plan 已经立账。你只反解引擎没法从谓词写成 case 列的臂，交 `schema: tg-solve-fill/v1`。不要手写义务条数，不要枚举行。
</task>

<input>
- Plan: `D:/PR-review/AscendC-Pilot/evals/fixtures/tg-plan/pr-10546-fag-tnd-sparse-deter/session/trial-c25-fill1.yaml`
- Init: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10546/attention/flash_attention_score_grad/.ascendc-pilot/arch35/tg/init.yaml`
- Solve index: `D:/PR-review/AscendC-Pilot/evals/tg_solve/live/pr-10546-fag-tnd-sparse-deter/solve_index.yaml`
- project_root: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10546/attention/flash_attention_score_grad`
</input>

<method>

先读 `D:/PR-review/AscendC-Pilot/evals/tg_solve/live/pr-10546-fag-tnd-sparse-deter/method.md`，那就是本窗形式规范。禁止打开 `evals/fixtures` 下除 Plan 输入路径以外的文件。禁止读 rubric / grade / trial。


## 你负责哪一半

Plan 立账，Solve 结账。

- Plan 已经给出 Target、Dimension 的臂、Guard、L2 exclusions。
- 引擎已经把 case.* 谓词编成 `solve_index.auto` 的 seed，并把 OPEN 义务展开完。
- **你只填**：HIT 路径上恒成立的 `baseline`；`needs_hit` 里每一臂的 `seed`（反解 probe/replay）；`auto: false` 的 Guard 的 `guard_hits`。引擎会把这些 seed 合并到每条义务上，缺的列用 `init.defaults` 补齐。

禁止：
- 写 `columns` / `rows` / `recipe`
- 按 L0/L1/L2/L3 手算或抄条数
- 把 leftover 格子一条条列成行
- 宣布 HIT / CLOSED

## 步骤

1. 读 `solve_index.yaml`：`needs_hit` 是你必须交的臂；`auto` 已经有 case seed，不要重复；`guards` 里 `auto: false` 才要 `guard_hits`。
2. 读 Plan 的 `requirement` 与这些臂的 `cuts`（`probe.*` / `replay.*`）。
3. 用 `uo_query` 查这些标识符的写点与分支，再读白名单源码，找出**改哪些 case 列**能让该臂成立。
4. 写 `baseline`：所有 HIT 义务都要满足的入口（确定性开关、布局、g 比率方向）。不要把 Guard 的杀整值写进 baseline。
5. 每个 `needs_hit` 臂给一个 **非空** `seed`。两臂必须能分开（至少一列取值不同）。seed 只写你真正用来反解该 probe/replay 的 case 列，不要拿别的 Dimension 已经在切的开关来顶替。不要 `seed: {}`。
6. `auto: false` 的 Guard 给 `guard_hits`：一行能打到该门的 miss 见证（布局补集用一个非 HIT 布局值）。
7. 只有你能证明「这组臂合并后列值冲突」时才写 `unreachable`（`partitions` + 加引号的 `reason`）。判不准的留给引擎合并：冲突的义务引擎会自己标 unreachable。

## 填空语法

```yaml
schema: tg-solve-fill/v1
baseline:
  is_deter: 1
hits:
  - dim: D-align
    arm: p-even
    seed: {B: 4}
  - dim: D-align
    arm: p-odd
    seed: {B: 3}
guard_hits:
  - id: G-not-tnd
    seed: {Input_Layout: BNSD}
unreachable: []
```

`reason` 必须加双引号。int 列不要加引号。

## 观测

`uo_query`：不带 pattern 拿索引；`pattern=<标识符>` 拿符号卡片；拿到 `file`+`line` 后精读。`count: 0` 以 Plan/packet 赋值为准。

</method>

<output>
最终消息正文就是 `schema: tg-solve-fill/v1` YAML 全文。不要 Write。Host 只读最终消息。
</output>
