# TilingKey 全覆盖闭环：可执行 SOP

把任意算子的声明 TilingKey 集合判定完毕：每个 Key 要么有真实 Host witness，要么有源码引理证明不可达。  
FAG arch35 一次校准结果见 [`../fag/tilingkey-closure-report.md`](../fag/tilingkey-closure-report.md)（附录）。

**冷启动口径**：`R = 0`、`E = 0`。不采信任何既有账本或预置 `proof_rules`。历史运行记录可当**输入数据**复用，结论必须重算。

---

## 0. 形式化

- **D** = 内核声明的 TilingKey 集合（从 `*_template_tiling_key.h` 展开）
- **R** = 真实 Host 运行产生过的 Key（witness）
- **E** = 有源码证明不可达的 Key（certificate）

闭合目标：

```text
D = (R ∩ D) ∪ E     且     R ∩ E = ∅
```

**单边原则**：近似模型（拟合 / 统计）**只能生成与排序候选，永远不能排除 Key**。排除只能由源码证明给出。

---

## 1. 前置条件

| 资产 | 路径 | 说明 |
| --- | --- | --- |
| 算子包（冷启动最小集） | `operators/<op>/<arch>/` | 仅 `operator.yaml` + `log_protocol.yaml` + `input_semantics.py` |
| UO KB | `<op>/.ascendc-pilot/<arch>/uo/` | 先跑 `/uo-init`；adapter pack 由 `export_adapter_pack` 从 KB 导出 |
| Closure 状态 | `<op>/.ascendc-pilot/<arch>/tg/closure/` | `R.txt` / `excluded.txt` / `open.txt` / `lemmas/` |
| Replay 缓存 | manifest 的 `artifacts.cache` | 宽表 `*key_cases*.csv`、`*_log.txt` |

环境：能跑 Host tiling 的机器（WSL + CANN）；Python 包 `testcase_agent[ml]` 已安装。

全局 CLI：

```bash
python -m testcase_agent.closure.cli --root <op_src> <subcommand> [args...]
# 或安装后的入口：tg-closure <subcommand>
```

Pilot 编排：`acp start tg-solve` → 反复 `acp next` / `acp run-action`（mode=`tilingkey_full_coverage`）。

---

## 2. 阶段与命令

### 阶段 0：Oracle 自检

**目标**：输入 → 真实 Host → Key + 维度 + 中间状态 + 拒绝原因；且结果可信。

```bash
# Pilot：oracle_probe action；或直接跑一轮小批量 replay
python -m testcase_agent.closure.cli --root <op_src> replay -n 10 --tag oracle_probe
```

**硬判据**（任一失败 → 置 `oracle_suspect`，禁止继续排除）：

1. 送入用例数与 `###DONE` 行数一致（防批次截断记成“拒绝”）
2. 宽表每行列数 = 表头列数（防 CSV 分隔符错位）
3. driver `compileInfo` 等关键字段非空（防整类分支从未触达）
4. 非法用例能拿到拒绝原因；合法用例能拿到 Key 与维度

### 阶段 1：建立账本（R）

```bash
python -m testcase_agent.closure.cli --root <op_src> cold-start   # 清 R/E/lemmas，写起始指纹
python -m testcase_agent.closure.cli --root <op_src> rebuild      # 从 logs/宽表/results 重算 R
python -m testcase_agent.closure.cli --root <op_src> state        # 打印 declared/R/E/gap
```

**判据**：`rebuild` 成功；若 `R ∩ E ≠ ∅` 则拒绝写入并报错。

### 阶段 2：静态骨架

来自 UO：`host_derivation` / adapter pack（`feature_bindings`、`bridge_spec`…）。  
节点分级：`exact_static` / `observed_exact` / `empirical` / `set_valued`。  
`set_valued` 只多生成候选，不用于排除。

```bash
# UO 侧（Pilot）
acp run-action export_adapter_pack   # 或 uo-init 流水线中的等价步骤
python -m testcase_agent.closure.cli --root <op_src> assess
python -m testcase_agent.closure.cli --root <op_src> fit
```

**判据**：每个 Key 维度有父节点与级别；`assess` 报出多数类 / 静态父节点 / 全旋钮三数。

### 阶段 3–4：定向搜索（推 R）

```bash
python -m testcase_agent.closure.cli --root <op_src> route
# SEARCH_PROGRESS →
python -m testcase_agent.closure.cli --root <op_src> search-round --budget 64
# 或拆步：generate → replay → commit
python -m testcase_agent.closure.cli --root <op_src> generate -n 32
python -m testcase_agent.closure.cli --root <op_src> commit --csv <judged_wide.csv>
python -m testcase_agent.closure.cli --root <op_src> rebuild
```

候选优先从已接受 witness 变异（`mutate_share≈0.65`），保留探索臂。  
只把**真正被裁决**的结果回流（区分 `HOST_CRASHED` / `NOT_RUN` 与真实拒绝）。

### 阶段 5：构造 → 回放 → 分类

```bash
python -m testcase_agent.closure.cli --root <op_src> residual --rows all
python -m testcase_agent.closure.cli --root <op_src> route
# CONSTRUCT_TARGETS / SEARCH_PROGRESS →
python -m testcase_agent.closure.cli --root <op_src> construct --limit 32
python -m testcase_agent.closure.cli --root <op_src> search-round --budget 64   # 含 construct+replay
python -m testcase_agent.closure.cli --root <op_src> explain --open-limit 32
```

对每个 open target：**必须 best-effort 构造并回放**。结果分类：

| 结果 | 动作 |
| --- | --- |
| HIT | 进 R |
| REWRITE（要的→给的） | 记观测，供引理 |
| REFUSE（非 crash） | 记观测，供引理 |
| CRASH / NOT_RUN | `oracle_suspect`，禁止写 E |

`construct_reasons` 只是改写风险假设，**不得**因此跳过构造，**不得**单独进 E。

**判据**：剩余 Key 要么进入 R，要么留下稳定的拒绝/改写观测供引理追查。

### 阶段 6：引理封口（推 E）

引理只解释「构造并回放后为何未命中」，不是「构造器不愿尝试」。

```bash
python -m testcase_agent.closure.cli --root <op_src> mine          # 辅助排序；lead 须绑定观测
python -m testcase_agent.closure.cli --root <op_src> lemma-evidence --combo Dim=Val[,Dim=Val...]
# Agent：对照 case + 源码填空证明 → review YAML →
# Pilot：lemma_review / lemma_apply；或：
python -m testcase_agent.closure.cli --root <op_src> apply-rules
python -m testcase_agent.closure.cli --root <op_src> rebuild
```

引理生命周期：`construct→replay→classify → lead → candidate → source_supported → counterexample_checked → reviewed → active`。  
晋升条件（代码强制）：`grade ∈ SOUND_GRADES`、certificate、证明五检查均为真：

- `entry_branches_checked`
- `early_returns_checked`
- `all_writers_checked`
- `execution_order_checked`
- `exception_branches_checked`

**禁止**：把“从未观测到 / 构造器先验拒采 / 统计共现 / LLM 猜测”写入 E。

### 终止

```bash
python -m testcase_agent.closure.cli --root <op_src> route     # GAP_ZERO
python -m testcase_agent.closure.cli --root <op_src> report
# Pilot：closure_audit → closure_certify（gate: closure_soundness）
```

`certify` 须校验：每条 E 规则的 provenance 指向**本次 cold-start 之后**生成的 active rules。

---

## 3. 确定性路由

`route` 决策顺序（`search_round.route`）：

| reason | 条件 | 下一步 |
| --- | --- | --- |
| `GAP_ZERO` | gap=0 且 violation=0 | audit / certify |
| `ORACLE_SUSPECT` | 存在 `oracle_suspect` 标志 | escalate，禁排除 |
| `SEARCH_STALLED` | ≥2 轮零增益且距离分布不变，且非 mostly_distance_1 | escalate / 查 harness |
| `CONSTRUCT_TARGETS` | ≥2 轮零增益且 ≥80% open 为 distance-1 | construct + explain |
| `NEED_LEMMA` | ≥2 轮零增益 | mine + lemma-evidence |
| `SEARCH_PROGRESS` | 仍有 open | search-round |

模型**不负责**调度；只负责在 `NEED_LEMMA` 时读证据包、写证明。

---

## 4. 工具对照

| 工具意图 | CLI |
| --- | --- |
| 真机裁决 | `replay` / `search-round`（`scripts/replay/runner.py`） |
| 重算 R | `rebuild` |
| 状态 | `state` |
| 拟合 / 评估 | `fit` / `assess` |
| 候选生成 | `generate` / `construct` |
| 残差 | `residual` |
| 引理线索 | `mine` |
| 证据包 | `lemma-evidence` |
| 反例 / 应用 E | `apply-rules`（内部 verify + revoke） |
| 分歧解释 | `explain` |
| 闭合报告 | `report` |
| 路由 | `route` |

---

## 5. 不变量（每步后）

1. `R ∩ E = ∅`
2. R 只因真实 witness 增长
3. E 只因带源码引用的 sound 引理增长
4. 每条引理通过全量反例检验
5. soft grade（`human` / `llm` / `candidate` / `heuristic`）不得单独支撑 E
6. 冷启动 provenance：E 不引用 run 之前预置的规则文件

---

## 6. Escalate

| 现象 | 动作 |
| --- | --- |
| 构造用例全被拒绝 | 读拒绝原因，补 `input_semantics` 一致性 |
| 接受但某维恒被替换 | 走引理路径 C（反例定位） |
| 某取值永不出现 | 查 harness / compileInfo，勿直接证不可达 |
| driver 崩溃 | 最小化复现，出缺陷单；勿当负样本训练 |

---

## 附录 A：FAG arch35 校准摘要

一次成功闭合的数量级（**校准值，非通用常量**）：

| 项 | 值 |
| --- | ---: |
| \|D\| | 8705 |
| \|R∩D\| | 4169 |
| \|E\| | 4536 |
| \|R\|（含未声明） | 4226 |
| 定向相对同池随机 | ~11× 单位产出 |
| witness 变异后接受率 | ~10% → 80–88% |

详情与引理正文见 [`../fag/tilingkey-closure-report.md`](../fag/tilingkey-closure-report.md)。

---

## 附录 B：迁移到新算子

1. 提供可跑 driver + `log_protocol` + `input_semantics`
2. `/uo-init` 建 KB → `export_adapter_pack`
3. `tg-closure cold-start` → 按第 2 节循环至 `GAP_ZERO`
4. 引擎侧 `scripts/replay/` 与 `testcase_agent.closure` 一般不需改
