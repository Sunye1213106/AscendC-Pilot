# 工作流流程图

阶段与 Action 的精确表见 [Workflow Reference](../reference/workflows.generated.md)。本页只画**人能跟着走的主路径**：谁先跑、哪里要人点、产物交给谁。

执行方标记：`[D]` 确定性 Engine，`[S]` 子代理，`[H]` 主控人话确认。

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
        ├── /ce-review                              只读检视
        ├── /ce-intent                              无 diff：定位改点
        └── /ce-impact ──► /ce-verify               有 diff：影响 + 证书
```

`uo-init` / `uo-update` 必须同时有 `--project` 与 `--architecture`（来自仓内 `arch*`）。其余 workflow 以已有 `.uo` 为准，不再另扫 `arch*`。

---

## 启动（所有 workflow 共用）

`/uo-query` 例外：短问主控直接 `acp uo-query --mode`，不走下面的 start 链；只有深问才 start。

```text
用户意图（自然语言或 /slash）
        │
        ▼
  Host 工具 pilot_run(workflow, project, architecture?)
        │
        ├── 缺 project / architecture
        │         │
        │         ▼
        │   acp scan-architectures（仅 uo-init/update）
        │         │
        │         ▼
        │   AskQuestion（选项原样）──► 再 start 一次
        │
        ├── 已有未完成 run / 残留 .uo
        │         │
        │         ▼
        │   AskQuestion：同工作流 → 继续上次 | 删除重开
        │               跨工作流 → 开始 {请求} | 删除重开
        │
        └── 参数齐
                  │
                  ▼
            acp start  ──►  acp run-action auto
                  │
                  ├── host_step = dispatch_subagent  → Task(stub 原样) → dispatch-result
                  ├── host_step = ask_human          → 可点选框 → answer
                  ├── host_step = done               → 结束并释放执行槽（下一工作流可直接 start）
                  └── host_step = failed             → inspect-failure；不要翻 Pilot 源码
```

`complete` / `host_step.done` 之后 **释放执行槽**：live `workflow.yaml` 与 `control/active_run.yaml` 清掉，run 快照落到 `runs/{run_id}/final_state.yaml`。正式产物（`.uo` / tg / ce）保留。下一工作流直接 `acp start`，不再占着 uo-init。跨工作流冲突时，「开始 {请求的工作流}」结束当前执行槽并 start 新工作流，不是继续旧的 uo-init。

第一次启动**不要**传 `force_new`。那是删除重开，会按 workflow 策略 wipe 产物。处女项目上 `--force-new` 是 no-op。

跨工作流时（例如活动是 uo-init、请求 uo-query）：「开始 uo-query」= 释放当前槽并 start 请求的工作流（不删 `.uo`）；「删除重开」才按新工作流策略清理。

---

## UO

### `/uo-init` — 建立 CodeMap

全部 `[D]`。闭合标准：verify pass，写出 `<op>.<arch>.uo`。

```text
prepare [D]  准备范围 / BuildVariant / Clang 探针
    │
    ▼
extract [D]  Clang 抽 CompilerFacts
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
done        Primary 读 quality.yaml，对人总结节点/关系/未闭合及原因
```

Rework（失败才走，不画进主链）：extract→prepare；analyze→extract；commit→analyze；verify→analyze / commit / prepare。

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
done        Primary 读 quality.yaml，对人总结刷新后的节点/关系/未闭合
```

`intent=diff_only` 可 detect → diff，跳过中间更新链。

### `/uo-query` — 只读提问

主控用 skill 判断查什么。短问自己 `acp uo-query`；深问再开子代理。工作流只有一阶段「查询」。

```text
answer
  └── 短问：主控直接 acp uo-query
  └── 深问：kb_lookup [S uo-query]  → kb-answer-v1
    │
    ▼
done        把答案说给人听
```

### `/uo-investigate` — 查 unresolved

```text
investigate [S uo-gap-investigator]  →  report
```

不修改正式 `.uo`。

---

## TG

消费已有 CodeMap。产品目标「全量 / 全覆盖 tilingkey case」会按 init → plan → solve 串联。

### `/tg-init` — 建立覆盖合同

```text
intent    [D]  记录全覆盖模式
    │
    ▼
kb_ready  [D]  校验 .uo          ──gate: uo_ready
    │
    ▼
contract  [D]  覆盖合同骨架
    │
    ▼
bind      [D]  Host 视图绑定      ──gate: tilingkey_binding_ready
    │
    ▼
gate      [D] 完整性 + [S tg-init-audit]
    │                              ──gate: audit_pass
    ▼
confirm   [H]  人话确认是否进入规划  ──gate: init_confirmed
```

### `/tg-plan` — 规划测试义务

```text
intent   [D]  记录规划目标
    │         overlay scenario_targeted 才有 [H] scenario_plan
    ▼
scope    [D]  规划范围
    │
    ▼
gate     [D]  前置检查            ──gate: tg_init_confirmed
    │
    ▼
build / filter / review  [D]  同一 Action `plan_build`
    │
    ▼
approve  [H]  批准开始求解        ──gate: plan_approved
```

### `/tg-solve` — 构造、Replay、闭环

```text
gate     [D]  求解前置            ──gate: plan_approved
    │
    ▼
oracle   [D]  Oracle 探测
    │
    ▼
ledger   [D]  重建覆盖账本
    │
    ▼
search   [D]  构造候选 + Host Replay
    │
    ▼
residual [D]  本轮分析
    │
    ├── 还有进展 ──────────────► search
    ├── 需要定向再构造 ────────► construct [D] ──► residual
    ├── 需要引理 ──────────────► lemma
    │                              lemma_leads / evidence [D]
    │                              lemma_mine [S tg-lemma-producer]
    │                              lemma_verify [D]
    │                              lemma_review [S tg-closure-referee]
    │                              lemma_apply / loop [D]
    │                              └── 回到 ledger
    └── 进入审查
            │
            ▼
         audit [S tg-closure-referee]
            │
            ├── 要补引理 ──► lemma
            ▼
         certify [D]  签发证书     ──gate: closure_soundness
```

义务关闭只有两种：Replay confirmed，或经审查的 exclusion proof。

---

## CE

intent / impact / verify 走变更闭环；`/ce-review` 只读，不签发证书。

### `/ce-review` — 只读检视

```text
scope / review / summary  [S ce-reviewer]  同一 Action `code_review`
                          判定 quick / file / PR；假设检验；证据要 path:line
                          ──gate: kb_ready, context_pack
```

### `/ce-intent` — 无 diff，定位改哪里

```text
intent    [D]  捕获变更意图
    │
    ▼
kb_ready  [D]  校验 .uo            ──gate: kb_ready
    │
    ▼
decompose [S ce-analyst]  特性分解
    │
    ▼
review    [S ce-change-referee] + [D] feature_promote
    │
    ▼
locate    [D]  锚点 + 场景推断
    │
    ▼
confirm   [H]  人工确认
```

### `/ce-impact` — 有 diff，影响切片

```text
capture     [D]  捕获变更
    │
    ▼
freshness   [D]  CodeMap 新鲜度     ──gate: kb_ready
    │
    ▼
slice       [D]  影响切片
    │
    ▼
classify    [D]  风险分类
    │
    ▼
scenarios   [D] 推断场景骨架（默认只跑 `scenario_infer`）
            overlay `scenario_targeted` 才走
            [S ce-analyst] knobs → [D] apply → [H] 确认
    ▼
obligations [D]  验证义务           ──gate: obligations_classified
    │
    ▼
audit       [S ce-change-referee]  ──gate: impact_ledger_ready
```

### `/ce-verify` — 验证并签发证书

```text
gate     [D]  校验影响账本          ──gate: impact_ledger_ready
    │
    ▼
review   [S ce-reviewer]  义务驱动审查
    │
    ▼
coverage [D]  桥接 TG 覆盖证据
    │
    ▼
residual [D]  剩余义务
    │
    ▼
external [D]  harness 证据
    │         [S ce-reviewer] 检查
    │         [D] 外部摄取
    │         [S ce-change-referee] 排除审查
    ▼
certify  [D]  CE 证书              ──gate: ce_certificate_sound
```

账本恒等式：`Open = O - V - X`。`V` 只收可审计收据；`X` 只收 referee 的 Tier A 排除证明。

---

## 实现锚点

| 权威 | 位置 |
| --- | --- |
| 阶段 / Action / gate | `pilot/ascendc_pilot/workflows/specs.py` |
| 启动与 architecture | `acp start`、`acp scan-architectures` |
| Host 传输环 | `pilot_run` → `acp run-action auto` → `dispatch-result` |
| 精确表 | [workflows.generated.md](../reference/workflows.generated.md) |
