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

`/uo-query` **不是** Host Session Driver 工作流：主控在当前会话做可见 LLM 路由（自查或派几个 `uo-query` 子代理），**禁止** `pilot_run` / `acp start uo-query`。其余 slash（建库、TG、CE、investigate）走下面的 start 链。

```text
用户意图（自然语言或 /slash）
        │
        ├── /uo-query 或只读提问
        │         │
        │         ▼
        │   主控对人说出路由（短问自查 / 1 路 / N 路并行）
        │         │
        │         ├── 自查：当前会话 `acp uo-query --mode`
        │         └── 深问：同一轮 Task(agent=uo-query) × N → 主控综合
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
        ├── 同产物族已有未完成写 run / 残留 .uo
        │         │
        │         ▼
        │   AskQuestion：同工作流 → 继续上次 | 删除重开
        │               同族换工作流（如 uo-init ↔ uo-update）→ 开始 {请求} | 删除重开
        │
        └── 参数齐（含不同族并行：uo 写与 tg-* / ce-* 可同时跑）
                  │
                  ▼
            acp start  ──►  acp run-action auto
                  │
                  ├── host_step = dispatch_subagent  → Task(stub 原样) → dispatch-result
                  │     （`host_step.tasks` ≥2：同一轮并行多个 Task，Primary 综合后再 dispatch-result）
                  ├── host_step = ask_human          → 可点选框 → answer
                  ├── host_step = done               → 结束并释放本产物族锁
                  └── host_step = failed             → inspect-failure；不要翻 Pilot 源码
```

控制面围着 **同一份 `.uo`（算子 + arch + digest）**，不是全局执行槽。只读提问不占锁（主控路由，不 start）。`uo-investigate` / `ce-review` 是 shared：不占锁、不写 exclusive `active_run`。写工作流按 `occupancy_group`（`uo` / `tg` / `ce-impact` / `ce-intent` / `ce-verify`）互斥；不同族并行。

`complete` / `host_step.done` 之后 **释放本族锁**：`state/slots/{family}/workflow.yaml`（或 shared 的 `runs/{run_id}/live_state.yaml`）清掉，run 快照落到 `runs/{run_id}/final_state.yaml`。`uo-init` / `uo-update` 还会发布新 `canonical_graph_digest`，把钉在旧 digest 上的 session 标 STALE。正式产物（`.uo` / tg / ce）保留。`control/active_run.yaml` 只是最近一次 exclusive 指针，不是互斥权威。

第一次启动**不要**传 `force_new`。那是删除重开，会按 workflow 策略 wipe 产物。处女项目上 `--force-new` 是 no-op。

同族换工作流时（例如活动是 uo-init、请求 uo-update）：「开始 uo-update」= 释放该族锁并 start 请求的工作流（不删 `.uo`）；「删除重开」才按新工作流策略清理。只读提问不与写工作流互抢。

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

### `/uo-query` — 只读提问（可见 LLM 路由）

查询**没有** Host 传输环。分类是主控的推理，必须写在对用户的消息里（不能只藏在思考里），再动手。不要为空转「问题路由」开子代理。

```text
用户问题
  └── 主控可见路由（当前会话说出来）
        ├── 短问：一名字 / 一 mode / 一两跳
        │         → 主控自己 acp uo-query --mode，stdout 对人说
        ├── 深问单域：一个独立证据空间、要沿图走
        │         → 一个 Task(agent=uo-query)，点卡片看思考
        └── 深问多域：多个独立证据空间 / 多个结案条件
                  → 若 host_step.tasks ≥2：原样并行派发（编译器权威）
                  → 否则主控按独立证据空间启发式拆；相关不等于单域
                  → 每个 Task 写 FIRST_QUERY（本片唯一先查 mode）
                  → 主控按各子代全文综合，禁止发明没引用的事实
                  → 未闭合再开一轮 Task；禁止把深问改成主控自查
```

`host_step.tasks` ≥2 时 Host fanout 为权威。不写 `answer.yaml`，不 `finalize` kb_lookup。`authorize` 把 `uo-query` 当作非 Host 驱动 actor：即使刚跑完 `uo-init`（阶段 leftover 不含 `uo-query`），主控仍可 `Task(agent=uo-query)`。不要为此 `acp start uo-query`。子代没有 session `prompt.md`：直接用插件 `acp` 工具（`command=uo-query --project …`），不要 bash。

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
