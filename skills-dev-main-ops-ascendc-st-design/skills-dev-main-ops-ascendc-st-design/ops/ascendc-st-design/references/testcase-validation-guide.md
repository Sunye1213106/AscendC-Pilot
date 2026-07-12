# 用例自检、约束诊断与统一修复路径

本文档为步骤 4 全流程（阶段 A 约束校验 + 阶段 B 用例生成自检 + 阶段 C 自动校验 + 阶段 D 保存评审报告）的诊断、修复和输出格式提供完整参考。

三层自检通过后，还需执行 `qa_verify_oracle.py` 自动校验（SKILL.md 阶段 C），覆盖三层自检无法检查的交叉产物一致性（产品支持、值域分析、tensor组数一致性、YAML域值与文档一致性、参数值域文档一致性、ET/BD/EX场景校验等）。阶段 C 失败时按 §4.3 诊断修复。三者共享 3 轮修复预算。阶段 C 通过后按 §5 格式保存评审报告。

---

## 1. 三层自检机制

`generate_test_cases.py` 在保存用例前自动执行三层自检（L2 仅第一层），按顺序为：

| 层次 | 校验内容 | 失败处理 |
|------|---------|---------|
| 1. 格式合法性 | tensor 列 nan/None 禁止值、shapes/dtypes/formats 长度一致性 | 自动丢弃 + 重新生成修复（最多 3 轮） |
| 2. 约束正确性 | `validate_constraints(case)` 校验 R{n} 约束 | 违规用例过滤 + 统计报告 |
| 3. 域覆盖率 | YAML 离散因子枚举值是否在用例中出现 | 输出修复报告（退出码 2），回退步骤 3 |

---

## 2. 约束正确性校验

`04_constraints.py` **必须定义** `validate_constraints(case: dict) -> list[str]`（返回违规约束 ID 列表，空列表表示全部通过）。`generate_test_cases.py` 在用例生成后自动调用此函数校验每条 L0/L1 用例。编写规范见 [constraint-writing-guide.md §4.6](constraint-writing-guide.md)。

**适用场景**：所有算子。

**数据独立性原则**：各 `_validate_r{n}` 函数应从 `01_parameter_description.md` 的 R{n} 约束原样转录判断逻辑，与 `@solves` 实现保持数据独立，避免同源错误。当 `@solves` 和 `validate_constraints` 使用不同的辅助函数时，即使其中一方有 bug，另一方仍能正确捕获。

> **约束守恒原则**（适用于所有修复路径）：`validate_constraints` 中的 R{n} 检查项只能增加，不能删除。若需修改某条 R{n} 的判定逻辑，必须追溯至 `01_parameter_description.md` 中的原始约束描述，并确保修改后的判定逻辑仍忠实反映原始约束语义。详见 [constraint-writing-guide.md §4.6](constraint-writing-guide.md)。

### 2.1 校验诊断流程

当第 2 层校验输出违规报告时，按以下流程定位修复点：

**步骤 1：解析违规统计**

输出格式 `[WARN] 约束正确性校验: N/M 条用例违规 ({R{n}:count, ...})`，记录每个违规 R{n} 及其次数。

**步骤 2：追溯 R{n} 定位**

打开 `04_constraints.py` 追溯表，查找每个违规 R{n} 的实现策略与对应函数。对照下表判定根因：

| 场景 | 判定条件 | 根因 | 修复动作 |
|------|---------|------|---------|
| 函数逻辑偏差 | 追溯表有 `@solves(func)` 且 `func` 已定义，但 `validate_constraints` 中同一 R{n} 的判定逻辑与 `func` 返回值不一致 | `@solves` 函数实现与 `validate_constraints` 对同一约束的判定口径不同 | 对齐 `func` 返回值与 `validate_constraints` 中该 R{n} 分支，确保覆盖相同条件空间。**注意**：当判定口径不一致时，以 `validate_constraints`（源自 01_parameter_description.md）为正确标准，修复 `@solves` 而非反过来 |
| 函数未实现 | 追溯表标注 `@solves(func)` 或 `[条件过滤]`，但 `04_constraints.py` 中不存在 `func` 函数定义 | 追溯表声明了函数但未实际编写 | 按 `[条件过滤]` 策略嵌入已有 `@solves` 函数，或新增 `@solves` 函数覆盖目标因子 |
| 条件过滤遗漏 | 追溯表标注 `[条件过滤]` 且函数存在，但条件分支未覆盖 `validate_constraints` 检测到的违规场景 | `@solves` 函数缺少对特定条件组合的处理分支 | 在对应 `@solves` 函数中补充 assert 或条件分支 |
| 非约束校验误报 | 追溯表标注 `validate-only` 且约束描述的是运行时报错行为（如空 tensor 组合），但 `validate_constraints` 中校验逻辑过于严格 | 该 R{n} 仅需丢弃违规用例，不应阻断生成 | 放宽 `validate_constraints` 中该 R{n} 的校验条件 |

> **修复唯一方向原则**：当 `validate_constraints` 报告 R{n} 违规时，正确做法是**修复 `@solves` 的实现**使其不再生成违规用例。**绝对不能**为了消除违规而删除或弱化 `validate_constraints` 中的 R{n} 检查。这确保了规范（validate）始终是最终的裁判，而实现（@solves）可以被不断修正。

**步骤 3：修复后重跑**

在 `04_constraints.py` 中完成修复后，重新执行阶段 B 用例生成命令（见 SKILL.md §4.2），检查违规是否消除。未消除则重复步骤 1-3（最多 3 轮，与统一修复路径总轮次共享）。

---

## 3. 域覆盖率校验

检查 YAML 中每个离散因子（`.dtype`、枚举型 `.value`、`.format`）的每个枚举值是否至少在一条 L0/L1 用例中出现，涵盖 solved factor（有 `@solves` 约束的因子）和 anchor factor。

未覆盖项分两类：

| 分类 | 含义 | 修复位置 |
|------|------|---------|
| primary | 约束函数自身不返回该值，或锚点因子值未被 L0 策略命中 | 步骤 3（`04_constraints.py`）或步骤 2（`02_test_factors.yaml`） |
| dependent | 依赖链上另一个因子有覆盖问题，导致该值不可达 | 修复对应的 primary 项即可，无需单独处理 |

校验失败时脚本以退出码 2 退出，stdout 输出 `[DOMAIN-COVERAGE-REPORT]` 结构化报告，包含每个未覆盖项的因子名、值、分类（primary/dependent）、sources 和 `repair_target` 字段。Agent 根据报告中的 `repair_target` 和 `sources` 定位并修复约束函数或 YAML 域定义。

---

## 4. 统一修复路径

以下修复路径覆盖步骤 4 全流程（阶段 A 约束校验 + 阶段 B 用例生成自检 + 阶段 C 自动校验），统一 3 轮修复预算。

### 4.1 阶段 A 校验失败

| 失败类型 | 判定条件 | 修复路径 |
|---------|---------|---------|
| 约束文件缺失 | `04_constraints.py` 不存在或为空 | 回退步骤 3 创建约束文件 |
| 追溯表缺失 | 追溯表标记（`# ===== 约束追溯表 =====`）不存在 | 回退步骤 3 §3.2 生成追溯表 |
| validate_constraints 缺失 | `validate_constraints(case)` 函数未定义 | 回退步骤 3 §3.3.1 补充函数定义 |
| 追溯完整性失败 | 存在 R{n} 未在 `04_constraints.py` 追溯表中登记 | 回退步骤 3 §3.2 补充追溯表 + 实现对应逻辑 |
| **约束守恒违反** | **[CONSTRAINT-CONSERVATION] 告警：01_parameter_description.md 中存在 R{n} 但 validate_constraints 中无对应校验** | **按修复唯一方向原则补充 `_validate_r{n}` 校验函数（docstring 必须包含 R{n} 原始描述）。禁止删除 01 中的 R{n} 或弱化 validate** |
| 约束逻辑失败 | 出现 `[CONTRACT]` 告警，或 NaN 丢弃率 > 10%，或约束满足率 < 95% | 从日志定位因子名 → 找对应 `@solves` 函数 → 常见问题：SKIP 误用、广播不兼容、缺少 else 分支 |
| dtype 等值替换 | `[DTYPE-EQUALITY-SUSPECT]` 告警 | 检查对应 @solves 函数是否使用正确的工具函数（`can_convert_dtype` / `infer_two_dtypes` / `can_convert_to_tensor`，而非 `return source`） |
| dtype 歧义约束 | `[AMBIGUOUS-DTYPE]` 告警 | 人工确认约束语义后更新 `01_parameter_description.md` 约束关系 |
| 排列型因子缺失 | `[SOURCE-MISSING]` 告警 | 按 §4.5 SOURCE-MISSING 修复流程 |

### 4.2 阶段 B 自检失败

| 失败类型 | 触发条件 | 修复路径 |
|---------|---------|---------|
| 格式合法性失败 | 丢弃率 > 5% | 脚本自动修复（重新生成），无需人工干预 |
| 约束正确性失败 | 丢弃率 > 5% | 按 §2.1 校验诊断流程定位违规 R{n} 对应的 `@solves` 函数并修复 |
| 域覆盖校验失败 | 有 YAML 枚举值未出现 | 根据 `[DOMAIN-COVERAGE-REPORT]` 中 `repair_target` 回退步骤 3 或步骤 2 |

### 4.3 阶段 C 自动校验失败

`qa_verify_oracle.py` 退出码非 0 时，从 `qa_auto_report.md` 中定位所有 FAIL 项，按下表确定根因和修复路径：

| 失败检查项 | 根因定位 | 修复路径 |
|-----------|---------|---------|
| Q1_产品支持场景 | aclnn 文档产品支持章节检测 | 信息性检查，不影响通过判定 |
| Q2_值域分析 | 参数退化（unique=1）且非 YAML 单值或枚举定义 | 步骤 3：修复 @solves 使其返回 Candidates() 多值 |
| Q3_tensor组数一致性 | shapes/dtypes/formats 元组长度不一致 | 步骤 3：检查 @solves 返回的 tensor 数量一致性 |
| Q4_YAML域值一致性 | YAML dtype 域值与 01 文档 dtype 列不一致 | 步骤 2：对齐 YAML 域值与文档描述 |
| Q5_存在性约束 | exist=[False] 的参数在 CSV 中有非 None 值 | 步骤 3：修复 @solves 中 exist=False 时返回 NOT_APPLICABLE |
| Q6_参数值域文档一致性 | CSV attributes 值违反 01 文档取值范围约束 | 步骤 3：修复 @solves value_range 约束函数 |

#### ET/BD/EX 场景校验修复（Q7~Q12）

Q7~Q12 针对 `03_scenario_enumeration.md` 中 ET/BD/EX 增强子场景的语义正确性进行检查，失败时按下表修复：

| 失败检查项 | 根因定位 | 修复路径 |
|-----------|---------|---------|
| Q7_ET完备性 | intermediate 变量 `value_range` 下界 ≤ 0 但无对应 ET-S{n} | 步骤 3：补充遗漏的 ET-S{n}，完成自由维度分析；或步骤 2：对不支持空tensor的参数设置 `support_empty_tensor: false` |
| Q8_ET变量存在性 | ET-S{n} "locked因子"列中的因子名在 `02_test_factors.yaml` 中不存在 | 步骤 3：修正因子名（须使用 `param.shape` 等引擎因子名）；或步骤 2：补充 YAML 因子定义 |
| Q9_BD边界值 | BD-S{n} "locked因子"列中的边界值不在 `01_parameter_description.md` 约束范围内 | 步骤 3：修正 BD-S{n} 的 locked因子为 01 约束的真实边界 |
| Q10_EX有效性 | EX-S{n} "locked因子"列缺少具体的违反值构造（如 `key.dimensions=5`） | 步骤 3：补充具体的违反因子名和违反值 |
| Q11_EX预期错误码 | EX-S{n} "预期错误码"列缺少 `ACL_ERROR_xxx` | 步骤 3：补充"预期错误码"列 |
| Q12_场景ID格式 | ET/BD/EX 子场景 ID 格式错误或编号不连续 | 步骤 3：修正为 `ET-S{n}`/`BD-S{n}`/`EX-S{n}` 格式并确保编号从 1 连续递增 |

#### ET/BD/EX 场景用例覆盖修复（Q13~Q15）

Q13~Q15 检查声明的 ET/BD/EX 场景是否在用例 CSV 中出现，失败时按下表修复：

| 失败检查项 | 根因定位 | 修复路径 |
|-----------|---------|---------|
| Q13_ET场景用例覆盖 | @solves 未正确处理 shape 含 0 的情况，或 engine 求解失败 | 步骤 3：修复 @solves 约束函数，确保 shape 维度可为 0；检查 `solver/contracts.py` 是否允许零维形状 |
| Q14_BD场景用例覆盖 | @solves 过度限制边界值可达性（如 assert 排除了边界组合） | 步骤 3：放宽 @solves 中的 assert 或扩展 Candidates，确保边界值能到达目标因子 |
| Q15_EX场景用例覆盖 | EX-S{n} 的 locked 值与 `_build_exception_base` 默认值冲突，或被 `_deduplicate` 过滤 | 步骤 3：调整 EX-S{n} 违反值，确保与默认值组合后唯一且有效；检查 `_expected_error` 和 `_exception_type` 是否正确设置 |

**关键原则**：Q7~Q15 的修复**全部回退步骤 3**（`03_scenario_enumeration.md` 或 `04_constraints.py`），仅 Q8 可能涉及步骤 2。

### 4.4 修复循环规则

- 修复-重跑循环最多 **3 轮**（阶段 A、阶段 B 和阶段 C 共享同一预算）
- 每轮修复后重新执行对应的阶段命令（`--validate` 或 `generate_test_cases.py` 或 `qa_verify_oracle.py`）
- 3 轮后仍失败则汇总日志告知用户（问题可能超出约束函数能修复的范围，如原始文档矛盾）

### 4.5 SOURCE-MISSING 修复流程

告警格式：

```
[SOURCE-MISSING] {target} 消费 {shape_source}，
  后者受排列型因子 {perm_factor} 影响，
  但 {target} 的 sources 中不包含 {perm_factor}
  → 建议: sources=[...]
```

修复步骤：

**步骤 1**：在 `04_constraints.py` 中定位 `@solves('{target}')` 函数。

**步骤 2**：修改 `@solves` 装饰器，将 `{perm_factor}` 追加到 `sources` 列表末尾。

**步骤 3**：修改函数签名，追加 `{perm_factor}` 对应的参数名。参数名规则：取 `{perm_factor}` 最后一段，将 `.` 替换为 `_`，保持 snake_case。例如 `transposeX2.value` → `transpose_x2`。

**步骤 4**：修改函数体。找到从 `{shape_source}` 中按固定索引提取维度值的代码行，改为 `if/else` 分支：

```python
if {perm_factor_param}:
    dim = {shape_source}[{transposed_idx}]
else:
    dim = {shape_source}[{non_transposed_idx}]
```

分支索引的确定方法：阅读 `{shape_source}` 的生产者 `@solves` 函数体，找到 `if {perm_factor_param}` 各分支中 `result = [...]` 的列表，确定目标维度在两个分支中的索引位置。

**步骤 5**：定位追溯表中该 R{n} 对应的 `_validate_r{n}` 函数。

**步骤 6**：修改 `_validate_r{n}`：

- 新增 `{perm_factor_param} = case.get('{perm_factor}')`
- 将维度提取改为同样的 `if/else` 分支

**步骤 7**：重新执行 `--validate` 校验，确认 `[SOURCE-MISSING]` 告警消除。

---

## 5. 评审报告输出格式

阶段 C 通过后，将评审结果写入 `DESIGN_DIR/06_review_report.md`（禁止仅在对话中输出）。

```markdown
# {算子名} 测试设计评审报告

## 1. 评审概述

- 算子名称：{aclnn_name}
- 目标产品：{product}
- L0 用例数：{l0_count}
- L1 用例数：{l1_count}
- 评审轮次：{round}

## 2. 自动校验结果

> 引用 qa_auto_report.md，禁止改写。

## 3. 修复历史

| 轮次 | 修复问题 | 回退步骤 | 修复动作 |
|------|---------|---------|---------|
| 1 | ... | ... | ... |

## 4. 总结

- 最终状态：全部通过 / 存在残留问题
- 残留问题（如有）：...
```
