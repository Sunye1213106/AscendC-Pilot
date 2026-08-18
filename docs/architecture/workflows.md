# 工作流流程图

阶段与 Action 的精确表见 [Workflow Reference](../reference/workflows.generated.md)。本页只画**用户可跟随的主路径**：谁先跑、何处需要确认、产物交给谁。

执行方标记：`[D]` 确定性 Engine，`[S]` 子代理，`[H]` 主控向用户确认。

---

## 产品主链

```text
算子源码 + architecture
        │
        ▼
   /uo-init  ──►  .uo CodeMap
        │
        ├── /uo-query         只读提问
        ├── /uo-investigate   查 unresolved（不改 .uo）
        ├── /uo-update        源码变了再刷新
        │
        ├── /tg-init ──► /tg-plan ──► /tg-solve     覆盖闭环
        │
        ├── /ce-plan ──► /ce-apply                  自己有需求：计划 → 按 todo 改码
        ├── /ce-review                              已有 diff / PR：只读双轴审查
        └── /handoff                                会话交接（无 ce- 前缀）
```

`uo-init` / `uo-update` 必须同时有 `--project` 与 `--architecture`（来自仓内 `arch*`）。其余 workflow 以已有 `.uo` 为准，不再另扫 `arch*`。

---

## 启动（所有 workflow 共用）

`/uo-query` **不是** Host Session Driver 工作流：简单查询直接 `pilot_cli` `uo-query`（禁止单独一轮只宣布路数），复杂查询同一轮派 `uo-query` 子代理，**禁止** `pilot_run` / `acp start uo-query`。其余 slash（建库、TG、CE、investigate）走下面的 start 链。

```text
用户意图（自然语言或 /slash）
        │
        ├── /uo-query 或只读提问
        │         │
        │         ▼
        │   简单查询直接 `pilot_cli` `uo-query`；复杂查询同一轮 Task
        │   （禁止单独一轮只宣布路数）
        │         │
        │         ├── 简单查询：当前会话 `pilot_cli` `uo-query`
        │         └── 复杂查询：同一轮 Task(agent=uo-query) × N → 主控综合
        │                   图上缺口自动第 2 轮；方向选择则 AskQuestion 选项
        │
        ▼
  Host 工具 pilot_run(workflow, project, architecture?)
        │
        ├── 缺 project / architecture
        │         │
        │         ▼
        │   `pilot_cli` scan-architectures（仅 uo-init/update）
        │         │
        │         ▼
        │   AskQuestion（选项原样）──► 再 start 一次
        │   用户打断并在对话里回复 → interpret-user-turn（对上选项则继续；否则跟新消息，不重问）
        │
        ├── 同产物族已有未完成写 run / 残留 .uo
        │         │
        │         ▼
        │   AskQuestion：同工作流 → 继续上次 | 删除重开
        │               同族换工作流（如 uo-init ↔ uo-update）→ 开始 {请求} | 删除重开
        │
        └── 参数齐（含不同族并行：uo 写与 tg-* / ce-* 可同时跑）
                  │
                  ▼
            Host `pilot_run`（Driver 内部 start→auto；模型不要 bash `acp start`）
                  │
                  ├── host_step = dispatch_subagent  → Task(stub 原样) → dispatch-result
                  │     （`host_step.tasks` ≥2：同一轮并行多个 Task，Primary 综合后再 dispatch-result）
                  ├── host_step = ask_human          → 可点选框 → answer
                  ├── host_step = done               → 结束并释放本产物族锁
                  └── host_step = failed             → inspect-failure；不要翻 Pilot 源码
```

控制面围着 **同一份 `.uo`（算子 + arch + digest）**，不是全局执行槽。只读提问不占锁（主控路由，不 start）。`uo-investigate` / `ce-review` / `handoff` 是 shared：不占锁、不写 exclusive `active_run`。写工作流按 `occupancy_group`（`uo` / `tg` / `ce-plan` / `ce-apply`）互斥；不同族并行。

`complete` / `host_step.done` 之后 **释放本族锁**：`state/slots/{family}/workflow.yaml`（或 shared 的 `runs/{run_id}/live_state.yaml`）清掉，run 快照落到 `runs/{run_id}/final_state.yaml`。`uo-init` / `uo-update` 还会发布新 `canonical_graph_digest`，把钉在旧 digest 上的 session 标 STALE。正式产物（`.uo` / tg / ce）保留。`control/active_run.yaml` 只是最近一次 exclusive 指针，不是互斥权威。

第一次启动**不要**传 `force_new`。那是删除重开，会按 workflow 策略 wipe 产物。处女项目上 `--force-new` 是 no-op。

同族换工作流时（例如活动是 uo-init、请求 uo-update）：「开始 uo-update」= 释放该族锁并 start 请求的工作流（不删 `.uo`）；「删除重开」才按新工作流策略清理。只读提问不与写工作流互抢。

---

## UO

### `/uo-init` — 建立 CodeMap

全部 `[D]`，脚本能补头时零 LLM。闭合标准：verify pass，写出 `<op>.<arch>.uo`。

```text
prepare [D]  准备范围 / BuildVariant / Clang 探针 / 脚本 include-heal
    │
    ├── 脚本仍缺头 → heal：propose_include_heal [S] → heal_promote [D] → 重跑 prepare
    │
    ▼
extract [D]  Clang 抽 CompilerFacts（`apply_saved_extras` 把 extras 变成 `-I`）
    │
    ▼
analyze [D]  确定性 Pass 串跨层边；证不全记 unresolved
    │
    ▼
commit  [D]  写入 <op>.<arch>.uo
    │
    ▼
verify  [D]  结构合法性 → uo/checks/integrity.yaml + quality.yaml
    │
    ▼
done        Primary 读 quality.yaml，向用户报告节点/关系/未闭合及原因
```

Rework（失败才走，不画进主链）：prepare→heal（`INCLUDE_HEAL_UNRESOLVED`）；heal→prepare；extract→prepare；analyze→extract；commit→analyze；verify→analyze / commit / prepare。不要手改 extras 或共享 `spec/build_context.yaml`。

### `/uo-update` — 源码变了刷新

```text
detect [D]  检测源码变更
    │
    ▼
plan   [D]  增量更新计划
    │
    ▼
apply  [D]  应用更新
    │
    ▼
export [D]  完整性校验  ──gate: integrity
    │
    ▼
diff   [D]  差异摘要
    │
    ▼
done        Primary 读 quality.yaml，向用户报告刷新后的节点/关系/未闭合
```

`intent=diff_only` 可 detect → diff，跳过中间更新链。

### `/uo-query` — 只读提问（可见 LLM 路由）

查询**没有** Host Session Driver 传输环（`host_driver=False` ≠ 没有 method bundle）。简单查询直接执行，首屏就是答案；复杂查询同一轮委派。禁止仅为问题分类而委派子代理。

```text
用户问题
  └── 简单查询直接 `pilot_cli` `uo-query`；复杂查询同一轮 Task
        ├── 简单查询：主控直接调用 `pilot_cli` `uo-query`
        │         → stdout 向用户陈述（禁止单独一轮只宣布路数）
        ├── 复杂查询、一个独立查询目标
        │         → 一个 Task(agent=uo-query)
        └── 复杂查询、多个独立查询目标
                  → 同一轮并行 1～5 路 Task
                  → 每个 Task 写 FOCUS 与建议的首次调用
                  → 主控按各子代全文综合，禁止发明没引用的事实
                  → 未闭合再开一轮 Task
```

子代不写 `answer.yaml`、不自己 finalize。复杂查询直接委派 Task，主控综合。`authorize` 把 `uo-query` 当作非 Host 驱动 actor：即使刚跑完 `uo-init`（阶段 leftover 不含 `uo-query`），主控仍可 `Task(agent=uo-query)`。不要为此 `acp start uo-query`。Delegated Task 的正文即全部，不要另行查找 session `prompt.md`；直接用插件 `pilot_cli` 工具（`command=uo-query --project …`），不要 bash。

### `/uo-investigate` — 查 unresolved

```text
investigate [S uo-gap-investigator]  →  report
```

不修改正式 `.uo`。

---

## TG

消费已有 CodeMap。正式产物只有 `init.yaml` / `plan.md` / `worklog.md` + cases 表。用户说「全量覆盖」会串联 init → plan → solve，但那是意图，不是 T=D 默认模式。根本改动见 [tg-rebuild.md](../development/tg-rebuild.md)。

### `/tg-init` — 绑定脚本列

```text
kb_ready  [D]  校验 .uo          ──gate: uo_ready
    │
    ▼
scan      [D]  扫描测试仓（含 xls）
    │
    ▼
bind      [S tg-analyst] → promote [D]  写出 init.yaml
    │
    ▼
validate  [D]  mapping 空则失败
    │
    ▼
confirm   [H]  进入规划            ──gate: init_confirmed
```

### `/tg-plan` — 融合义务

```text
gate     [D]  强制 init.yaml      ──gate: tg_init_confirmed
    │
    ▼
fuse     [S tg-analyst] → promote [D]  一份 plan.md
    │
    ▼
validate [D]  列 root 闸门
    │
    ▼
approve  [H]  开始求解            ──gate: plan_approved
```

### `/tg-solve` — 构造、Replay、worklog

```text
gate      [D]  已批准 + harness 落地
    │
    ▼
construct [S] → promote [D]  cases 表
    │
    ▼
replay    [D]  Host tiling（无 NPU）
    │
    ▼
analyze   [S] → promote [D]  worklog 四段
    │
    ├── open 非空 ──► construct
    ▼
certify   [D]  open: []           ──gate: worklog_closed
```

`Replay reject ≠ E`。TG 永不改算子仓；缺列走 CE apply 测试脚本仓。

---

## CE

`/ce-plan` 问清需求并写出 `{slug}_plan.md`；`/ce-apply` 只按未完成 todo 改码；`/ce-review` 只审已有 diff，不落盘；验证走 `/tg-plan`。

### `/ce-plan` — 自己有需求

```text
kb_ready  [D]  校验 .uo            ──gate: kb_ready
    │
    ▼
grill     [S ce-analyst] + [D] grill_promote + [H] 确认问清
    │
    ▼
draft     [S ce-analyst]  写出 ce/plan/{slug}_plan.md
    │
    ▼
confirm   [H]  去 /ce-apply 或继续改计划
```

### `/ce-apply` — 按计划 todo 改码

```text
gate      [D]  当前计划有未完成 - [ ]
    │
    ▼
patch     [S ce-applier]  一次一条 todo
    │
    ▼
guard     [D]  改动 ⊆ 计划声明的文件
    │
    ▼
refresh   [D]  嵌套 uo-update（禁止 LLM 写 .uo）
    │
    ▼
report    [H]  建议审查 / 建议测试 / 回计划 / 交接
```

### `/ce-review` — 已有 diff，只读检视

```text
scope     [D]  内存 git/PR diff；无 diff 则停
    │
    ▼
review    [S ce-reviewer ×2]  Spec ∥ Standards
                          ──gate: kb_ready, context_pack
    │
    ▼
summary   [H]  建议修改或建议测试（不落盘）
```

### `/handoff` — 会话交接

```text
session   [S ce-analyst]  写 session_handoff.md（只引用路径，下一步 slash）
```

---

## 实现锚点

| 权威 | 位置 |
| --- | --- |
| 阶段 / Action / gate | `pilot/ascendc_pilot/workflows/specs.py`、CE：`ce_specs.py` |
| 启动与 architecture | Host `pilot_run`、`pilot_cli` `scan-architectures` |
| Host 传输环 | `pilot_run` →（内部）`run-action auto` → `dispatch-result` |
| 精确表 | [workflows.generated.md](../reference/workflows.generated.md) |
