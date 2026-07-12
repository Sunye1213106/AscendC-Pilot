---
name: ascendc-st-design
description: Ascend C 算子系统测试（ST）设计技能。基于 aclnn、REG_OP 或 torchapi 接口文档，完成算子参数定义、测试因子提取、约束关系分析、测试用例生成（L0/L1/L2）的完整流程。支持 aclnn 模式（ACLNN格式CSV）、kernel 模式（Kernel格式CSV）和 torchapi 模式（复用ACLNN格式CSV）。当需要以下任务时使用此技能：设计算子测试用例、生成ST用例。
---

# Ascend C 算子测试设计

本技能提供 Ascend C 算子测试设计的完整工作流程：从原始接口文档（aclnn 接口文档、REG_OP proto 文件或 torchapi 接口文档）出发，经过参数清洗、因子提取、约束建模，最终输出结构化的 L0/L1 测试用例 CSV，支撑算子功能和精度验证。

**支持的接口类型**：
- **aclnn**：ACLNN 接口文档（`aclnn{Op}.md`），输出 ACLNN 模式 CSV
- **REG_OP**：`{op}_op_host/{op}_def.cpp`（NPU 支持 dtype/格式/默认值）+ `{op}_op_graph/{op}_proto.h`（参数结构/约束关系）+ `README.md`（功能说明/产品支持），输出 Kernel 模式 CSV
- **torchapi**：`torch_npu-npu_{Op}.md`（op-plugin 接口文档，Python/PyTorch 签名），输出 ACLNN 模式 CSV，`api_name` 为 `torch_npu.npu_{Op}` 全限定名

## 目录

- [目录结构与路径规范](#目录结构与路径规范)
- [步骤 1：输入文件校准与参数清洗](#步骤-1输入文件校准与参数清洗) — 产出 `01_parameter_description.md`
- [步骤 2：生成测试因子](#步骤-2生成测试因子) — 产出 `02_test_factors.yaml`
- [步骤 3：场景枚举与约束实现](#步骤-3场景枚举与约束实现) — 产出 `03_scenario_enumeration.md` + `04_constraints.py`（含 @solves 函数、validate_constraints、tag() 调用）
- [步骤 4：约束校验与用例生成](#步骤-4约束校验与用例生成) — 产出 L0/L1 CSV + `05_topology.md` + `06_review_report.md`
- [步骤 5：测试设计结果总结](#步骤-5测试设计结果总结)
- [参考文件索引](#参考文件索引)

---

## 目录结构与路径规范

所有测试设计结果统一存放到算子目录下：

```
operators/{operator_name}/tests/st/
├── design/
│   ├── 00_interface_type.yaml      # 可用接口清单 + 用户选择的生成类型
│   ├── 01_parameter_description.md
│   ├── 02_test_factors.yaml
│   ├── 03_scenario_enumeration.md
│   ├── 04_constraints.py
│   ├── 05_topology.md
│   └── 06_review_report.md
└── testcases/                      # 最终测试用例
    ├── {operator_name}_l0_functional.csv
    ├── {operator_name}_l1_functional.csv
    └── {operator_name}_l2_exception.csv
```

**路径变量**：
- `OPS_DIR`：算子目录，`operators/{operator_name}/`
- `DESIGN_DIR`：测试设计中间产物目录，`{OPS_DIR}/tests/st/design/`
- `TESTCASE_DIR`：最终测试用例目录，`{OPS_DIR}/tests/st/testcases/`
- `{operator_name}`：由 `00_interface_type.yaml` 的 `generate_for` 决定（aclnn→`aclnn{Op}`；reg_op→`{Op}`；torchapi→`torch_npu_npu_{Op}`）

**单模式工作流**：步骤 1 先全量扫描识别可用接口类型，清洗前由用户确认生成目标（仅一种），然后仅按所选接口的资料清洗。不支持同时生成多类接口用例。如需为另一接口生成，重新执行接口确认步骤切换 `generate_for`。

---

## 步骤 1：输入文件校准与参数清洗

**目的**：将分散在多个章节的参数信息综合归纳，补全隐含约束，生成一份清晰完备的参数说明文档，为后续因子提取和约束分析奠定基础。

**产出**：`01_parameter_description.md`

### 1.1 全量扫描获取输入文件

从以下文档获取算子接口信息：
- 需求文档：`operators/{operator_name}/docs/REQUIREMENTS.md`
- ACLNN 接口文档：`operators/{operator_name}/docs/aclnn{OperatorName}.md`
- REG_OP 接口文档：`operators/{operator_name}/op_graph/{op}_proto.h`、`operators/{operator_name}/op_graph/{op}_def.cpp`
- torchapi 接口文档：：`operators/{operator_name}/docs/torch_npu-npu_{Op}.md`

或者由用户指定文件路径。

扫描 `operators/{operator_name}` 下所有可用资料，不预设接口类型，扫描结果写入 `design/00_interface_type.yaml` 的 `available_interfaces` 字段。

**目标产品默认为 Ascend 950PR / Ascend 950DT**。若用户在指令中指定了目标产品型号，以用户指定的为准。获取文档后，必须读取"产品支持情况"章节，确认目标产品是否在支持列表中；若不支持，立即中断流程并告知用户确认目标产品型号。

### 1.2 接口类型确认（清洗前决策）

根据 `00_interface_type.yaml` 的 `available_interfaces`：

1. 若仅一种接口可用 → 直接选用，跳过用户确认
2. 若多种接口可用 → **反馈用户确认**生成目标：

   ```
   检测到以下接口资料可用：
     [1] aclnn    (aclnn{Op}.md)
     [2] reg_op   ({op}_proto.h + {op}_def.cpp)
     [3] torchapi (torch_npu-npu_{Op}.md)
   请确认生成哪一类接口的用例（输入编号）：
   ```

3. 用户选择写入 `00_interface_type.yaml` 的 `generate_for` 字段
4. **不支持同时生成多类接口用例**

由 `generate_for` 派生：
- `operator_name`：aclnn→`aclnn{Op}`；reg_op→`{Op}`；torchapi→`torch_npu_npu_{Op}`
- `csv_mode`：aclnn/torchapi→`aclnn`；reg_op→`kernel`

### 1.3 参数功能说明内容清洗（仅所选接口资料）

> **关键原则**：仅读取 `generate_for` 对应接口的必选+可选资料，执行该接口专属清洗步骤。其他接口的资料即使存在也不读取。

执行本步骤前须先完整读取 [parameter-cleaning-guide.md](references/parameter-cleaning-guide.md)。清洗流程（信息收集→综合分析→生成结果→矛盾处理）详见该文档 §2~§4。

按 `generate_for` 确定资料源和清洗步骤：
- **aclnn** → 读取 `aclnn{Op}.md` + 可选设计文档；执行 aclnn 专属步骤 A1-A3 + 共同步骤 S1-S3
- **reg_op** → 读取 `{op}_proto.h` + `{op}_def.cpp` + 可选设计文档；执行 reg_op 专属步骤 R1-R6 + 共同步骤 S1-S3
- **torchapi** → 读取 `torch_npu-npu_{Op}.md` + 可选设计文档；执行 torchapi 专属步骤 T1-T5 + 共同步骤 S1-S3。torchapi 清洗规则详见 [torchapi-cleaning-guide.md](references/torchapi-cleaning-guide.md)

torchapi 接口的核心挑战：无错误码表，需通过 torchapi-cleaning-guide §3 的替代策略挖掘隐含约束。中间因子统一小写命名（`_batch/_m/_k/_n`）。

**排除项**：workspaceSize、executor参数无需处理
- **产品型号 dtype/format 预过滤**（产品隔离原则）：
  产品型号相关的排除声明**仅适用于文档中 `<term>` 标签标注的产品**，不跨产品传播。
  - **目标产品的无条件排除**（如"950PR 不支持 FLOAT"）：在清洗时直接过滤，不生成 R{n}
  - **目标产品的条件排除**（如"仅场景1/2支持 FLOAT4"）：保留并生成 R{n}，由 @solves 按场景收窄候选
  - **其他产品的排除声明**（如"A2 不支持 FLOAT"且目标产品为 950PR）：**不影响目标产品**
  - **文档未为目标产品显式排除的 dtype**：默认支持

### 1.4 输出格式要点

**文件头部**：包含 `## 基本信息` 节（含算子名称、目标产品系列、功能说明），然后是 `## 参数列表` 节。所有参数合并为一张标准11列 Markdown 表格：

| 参数名 | 类型 | 输入/输出 | 必选/可选 | 维度/长度 | 数据格式 | 数据类型 | 取值范围 | 空tensor | 非连续 | 补充说明 |

各列填写规则、推断标注要求、格式禁忌详见 [parameter-cleaning-guide.md](references/parameter-cleaning-guide.md) §3。完整示例见该文档附录（aclnnReduceNansum）。

---

## 步骤 2：生成测试因子

**目的**：将参数说明文档转化为求解引擎可消费的结构化因子定义，每个参数对应一组可枚举或可采样的因子（如 dtype、shape、exist 等）。

**产出**：`02_test_factors.yaml`

读取 `01_parameter_description.md`，按照映射规则（参考 [test-factor-mapping-rules.md](references/test-factor-mapping-rules.md)），生成 `02_test_factors.yaml`。

**关键原则**：

- **operator_name 必填**：在 YAML 文件顶层添加 `operator_name` 字段，值由 `00_interface_type.yaml` 的 `generate_for` 决定。aclnn 接口使用 `aclnn{OperatorName}` 格式；REG_OP 接口使用算子名（如 `AddN`）；torchapi 接口使用 `torch_npu.npu_{Op}` 全限定名。引擎通过该字段生成 CSV 中的 `api_name` / `op_name` 列
- 每个参数包含 `io_type: input` 或 `io_type: output`，用于引擎区分输入输出
- **内存复用参数**：当参数"输入/输出"列为"输入/输出"时，设 `io_type: input` + `in_place: true`（详见 [test-factor-mapping-rules.md §2](references/test-factor-mapping-rules.md)）
- **value_range 判定**：对每个非 Tensor 标量参数，按 [test-factor-mapping-rules.md §3](references/test-factor-mapping-rules.md) Scalar 映射表的判定规则，确定使用 `.value` 还是 `value_range`。判定流程详见 [test-factor-mapping-rules.md §6.0-6.1](references/test-factor-mapping-rules.md)
- 输出参数不定义 `value_range` 和 `value`
- **`.value` vs `value_range` 判定**：满足以下条件使用 `.value`：bool 类型、文档明确列举所有合法值（≤10 离散值）、文档标注"不支持此字段"/"历史遗留"/"固定传N"。其余情况使用 `value_range`（含不等式约束、计数/索引语义、"默认值"+跨参数关联、哨兵值+连续范围）。⚠️"默认值N"不等于"固定值N"——详见 [test-factor-mapping-rules.md §3](references/test-factor-mapping-rules.md) 消歧规则
- **⚠️ 锚点数量不作为因子形式选择依据**：`.value` 与 `value_range` 的判定完全由上述映射规则决定。引擎通过随机采样处理组合空间，**禁止**以"锚点过多"、"组合爆炸"等理由将 `value_range` 参数改为 `.value` 单值。此行为会导致值域覆盖缺失、边界值未测试、关键代码路径（如 `@solves` 中的条件分支）永不执行
- **⚠️ 文档值域保真原则**：当因子值域在 `01_parameter_description.md` 中有明确文档约束时，YAML `value_range` 必须覆盖文档完整范围。**禁止**以"避免shape溢出"、"测试资源预算"等理由缩减 YAML 域上界。此行为会导致值域覆盖缺失、大 shape 边界未测试。场景相关值域采用 YAML 声明最宽范围 + `@solves` 按场景收窄的模式（详见 [test-factor-mapping-rules.md §6.3.1](references/test-factor-mapping-rules.md) 和 [constraint-writing-guide.md §3.3.1](references/constraint-writing-guide.md)）
- 无需定义workspaceSize和executor参数
- **域值溯源标注**：因子域值须在 YAML 中以 `# 来源:` 注释标注来源，详见 [test-factor-mapping-rules.md §7](references/test-factor-mapping-rules.md)
- **support_infnan 字段**：当算子文档明确声明输入不支持 inf/nan 时（如"算子输入不支持有±inf和nan的情况"），在 `02_test_factors.yaml` 中对相关 float 输入 tensor 参数设置 `support_infnan: false`（与 `type`/`io_type` 同级，不在 `factors` 下）。不设置时默认为 `true`，引擎按现有行为覆盖 inf/nan。详见 [test-factor-mapping-rules.md §3](references/test-factor-mapping-rules.md)
- **support_empty_tensor 字段**：当算子文档明确声明输入不支持空 tensor 时（01 参数表"空tensor"列为"不支持"），在 `02_test_factors.yaml` 中对相关 input tensor 参数设置 `support_empty_tensor: false`（与 `type`/`io_type` 同级，不在 `factors` 下）。不设置时默认为 `true`，QA 将检查空 tensor 轴覆盖完备性（Q7b），生成器将尝试生成 ET 场景用例。设置为 `false` 时，Q7b 跳过该参数检查，ET 目标跳过，转而在 L2 中生成空 tensor 异常用例。详见 [test-factor-mapping-rules.md §3](references/test-factor-mapping-rules.md)

**中间因子**：若算子存在共享语义变量（如 batch、dim 等），在 YAML 中添加 `intermediate` 区段。溯源规则见 [constraint-writing-guide.md §3.3](references/constraint-writing-guide.md)。

**参数类型与因子映射、详细规则和示例**：参考 [test-factor-mapping-rules.md](references/test-factor-mapping-rules.md)

---

## 步骤 3：场景枚举与约束实现

**目的**：将参数间的依赖关系编码为 Python 约束函数，引擎按拓扑顺序自动求解。先通过场景枚举确保每条约束的语义空间被完整覆盖，防止语义折叠。

**产出**：`03_scenario_enumeration.md` + `04_constraints.py`

**详细规范**：参考 [constraint-writing-guide.md](references/constraint-writing-guide.md)（§0 场景枚举 + §1~§4 @solves 规范、方向选择、中间因子、约束翻译模式（含验证函数））

### 3.1 场景枚举

约束关系被正确识别不等于被正确实现。最常见的缺陷是**语义折叠**：@solves 只实现了最简子场景（如将"广播"实现为"完全相同 shape"），覆盖率报告不会报警。场景枚举通过在写每个 @solves 函数之前显式列出该约束的所有合法子场景来防范此问题。

场景识别（模式速查表、单值测试法）、预设场景库、枚举表输出格式和反模式清单详见 [constraint-writing-guide.md §0](references/constraint-writing-guide.md)；增强子场景（ET/BD/EX）格式模板见 [constraint-writing-guide.md §0.6](references/constraint-writing-guide.md)。枚举结果保存至 `03_scenario_enumeration.md`，步骤 4 阶段B 通过 `--scenarios` 参数自动验证场景覆盖。

### 3.2 约束追溯表与策略决策树（@solves 实现前置）

实现任何 @solves 前，必须先在 `04_constraints.py` 头部生成追溯表，建立 01 的每个 R{n} 到实现的映射。

**04_constraints.py 强制骨架**（agent 填空，不从零编写）：

```python
from solver import solves, Candidates, SKIP, NOT_APPLICABLE, tag

# ===== 约束追溯表 =====
# R{n} ({描述})  条件因子: {从01原文复制}  → {策略} → {函数名}
# ===== 追溯表结束 =====

# ===== validate_constraints（循环 dispatch，杜绝漏调）=====
def validate_constraints(case):
    violations = []
    for r in ('R1', 'R2', 'R3', ..., 'R{n}'):
        violations.extend(globals()[f'_validate_{r.lower()}'](case))
    return violations
```

**追溯表条件因子列**：每行必须含"条件因子"列，**从 01 原文复制**（不得重新判断）。引擎 `--validate` 校验缺失或不一致即 ERROR。

**策略决策树**（读取 01 条件因子，机械执行）：

> **前置规则**：产品型号 dtype/format 排除遵循**产品隔离原则**（见 §1.3）。目标产品自身的排除在 Step 1/2 生效；其他产品的排除不影响。

| 条件因子 | 控制类型 | 生成器能否违规？ | 策略 | 正向强制 |
|---------|---------|---------------|------|---------|
| 无 | — | — | factor-domain 或 @solves | — |
| ≠无 | **A: 存在性**（条件因子→exist推导） | 否（exist=False不生成值） | factor-domain | exist @solves |
| ≠无 | **B: 值空间**（跨参数值关系/条件化候选） | **是** | **@solves [条件过滤]** | **assert 正向过滤** |

**⚠️ 值空间约束（控制类型 B）必须用 @solves+assert 正向强制**：否则生成器产生违规组合 → validate_constraints 反弹 → 自检崩溃。

> **设计原则**：每个 R{n} 通过 factor-domain 或 @solves 正向实现。`validate_constraints` 是反向安全网，不是策略。

子约束拆分、`[条件过滤]` 格式要求见 [constraint-writing-guide.md §5.1](references/constraint-writing-guide.md)。若某个 R{n} 无法归入决策树任一分支，**立即中断**并告知用户澄清。

`--validate` 会自动校验追溯表完整性（步骤 4 阶段 A），确保每个 R{n} 均已登记。

### 3.3 约束实现

> **约束守恒原则**（不可违反）：
> 1. `01_parameter_description.md` 中的 R{n} 约束是**不可变规范**
> 2. `validate_constraints` 必须检查**每一个 R{n}**——它是规范的镜像，不是实现的附属品
> 3. **修复唯一方向**：当 `validate_constraints` 校验失败时，永远修复 `@solves`，**永远不能削弱 `validate_constraints`**
> 4. 若需修改 `validate_constraints` 中的判定逻辑，必须先确认修改来源于 `01_parameter_description.md` 约束描述的变更或澄清
> 5. `--validate` 会自动执行 **[CONSTRAINT-CONSERVATION]** 检查，确保 `01_parameter_description.md` 中的每个 R{n} 都在 `validate_constraints` 中有对应校验

**核心机制**：使用 `@solves(target, sources)` 装饰器声明因子间的依赖关系和求解逻辑，引擎自动构建拓扑图并按顺序求解。返回值语义、方向选择规则、15种翻译模式详见 [constraint-writing-guide.md](references/constraint-writing-guide.md)。

```python
@solves('out.dtype', sources=['dtype.value'])
def solve_out_dtype(dtype_value):
    return dtype_value
```

**约束分析维度**（按优先级）：数据类型依赖 → 形状依赖 → 数值依赖 → 存在性依赖

### 3.3.1 validate_constraints 与 tag

`04_constraints.py` **必须定义** `validate_constraints(case: dict) -> list[str]`（返回违规约束 ID 列表）。编写规范和模板见 [constraint-writing-guide.md §4.6](references/constraint-writing-guide.md)。

当 `03_scenario_enumeration.md` 中定义了子场景 ID 时，`@solves` 函数**必须**调用 `tag(name, value)` 标记当前用例所属的子场景。详细用法见 [constraint-writing-guide.md §0.3](references/constraint-writing-guide.md)。

### 3.4 因子类型契约（引擎自动校验）

引擎自动校验 `@solves` 和内置推导的返回值是否符合类型契约，不合法的组合会被丢弃并打印 `[CONTRACT]` 告警。

| 因子后缀 | 合法返回 | 非法返回 | exist=False 时 |
|---------|---------|---------|---------------|
| `.shape` | `list[int]`，每个元素 ≥ 0 | `None`、`NaN`、含负数 | 返回 `NOT_APPLICABLE` |
| `.shape_list` | `list[list[int]]`，元素 ≥ 0 | 独立随机导致不兼容 | 返回 `NOT_APPLICABLE` |
| `.dtype` | 合法 dtype 字符串 | 数值、空字符串、未知类型 | 返回 `NOT_APPLICABLE` |
| `.dimensions` | `int`，0 ≤ n ≤ 8 | 负数、浮点数 | 返回 `NOT_APPLICABLE` |
| `.length` | `int` ≥ 0 | 负数、浮点数 | 返回 `NOT_APPLICABLE` |
| `.value_range` | `list`，每个元素为 `[min, max]` | 非列表 | 返回 `NOT_APPLICABLE` |

### 3.5 约束函数 assert（断言式自校验）

引擎自动拦截 `AssertionError`（跳过该组合并统计），因此在 `@solves` 函数的 `return` 前用 `assert` 表达核心约束不变量。模板速查表和示例见 [assert-templates.md](references/assert-templates.md)。

**值空间约束（控制类型 B）的 assert 正向强制**：当约束涉及跨参数值关系（如 `reduceSum(seqLens - compressLens) ≤ num_blocks * block_size`）时，必须在生成目标因子的 @solves 中用 assert 过滤违规组合。assert 仅作安全网，生成逻辑应主动倾向于满足约束（收窄上界），避免过滤率过高导致求解率为 0。

### 3.6 检查清单

完整的约束翻译检查清单（含 validate_constraints 和 tag() 要求）见 [constraint-writing-guide.md §5](references/constraint-writing-guide.md)。

**步骤 3 完成前的自检门禁**：进入步骤 4 前，确认以下产物完备性：

1. 追溯表中每个 R{n} 的策略按 §3.2 决策树判定（A/B 控制类型），条件因子列已从 01 复制
2. 追溯表中 `[条件过滤]` 条目含宿主函数名、条件因子列表、条件分支摘要（格式见 [constraint-writing-guide.md §5.1](references/constraint-writing-guide.md)）
3. `validate_constraints` 函数已定义且覆盖所有 R{n}（每个 R{n} 有独立的 `_validate_r{n}` 函数，docstring 包含原始约束描述）
4. 01_parameter_description.md 中每个 R{n} 的"条件因子"字段已填写，且已复制到追溯表
5. `validate_constraints` 中的判定逻辑从 01_parameter_description.md 独立转录，未引用 `@solves` 辅助函数

---

## 步骤 4：约束校验与用例生成

**目的**：验证约束模块的正确性（阶段A），然后生成 L0/L1 二级测试用例（阶段B），然后执行自动校验（阶段C），最后保存评审报告（阶段D）。

**⚠️ 强制要求**：步骤 4 **必须**按 A → B → C → D 顺序全部完成，**禁止**在任意阶段后提前终止。进入步骤 4 前须拆分为 4 个子步骤，每步验证产物通过后才可继续下一步。

**产出**：`05_topology.md` + L0/L1 CSV 文件 + `06_review_report.md`

| 阶段 | 内容 | 产物（门禁检查项） | 未通过处理 |
|------|------|-------------------|-----------|
| 4A 约束校验 | 完整性 → 溯源 → 求解校验 | `05_topology.md` 存在 + 日志无 ERROR | 修复约束后重跑 4A |
| 4B 用例生成 | L0（≤200）+ L1（≥500）+ L2（≤200异常）+ 自检 | L0/L1/L2 CSV 存在且用例数 > 0 | 修复后重跑 4B |
| 4C 自动校验 | qa_verify_oracle.py 自动校验 | qa_auto_report.md 存在 + 退出码=0 | 回退步骤3修复 |
| 4D 保存评审报告 | 写入 `06_review_report.md`（§4.5） | 文件存在且含必填章节 | 执行 4D 写入报告 |

### 4.1 阶段 A：约束校验

校验按以下顺序执行（低成本检查优先拦截），全部通过后方可进入阶段 B。校验失败的修复路径见 [testcase-validation-guide.md §4](references/testcase-validation-guide.md)。

#### 1 约束文件完整性校验

**毫秒级纯文本检查，最先拦截结构性缺失**。校验项和不通过处理路径见 [testcase-validation-guide.md §4.1](references/testcase-validation-guide.md)。

#### 2 中间因子溯源校验

在执行约束求解前，对 `02_test_factors.yaml` 的 `intermediate` 区段按 [constraint-writing-guide.md §3.3](references/constraint-writing-guide.md) 决策树和文档溯源规则执行校验：

| 校验项 | 不通过处理 |
|--------|-----------|
| 模式合规：无文档约束的变量使用 `value_range` 而非 `.value` | 回退步骤2修改 YAML |
| 溯源标注：每个中间因子有 `# 来源:` 注释 | 补充注释后继续 |
| assert 可追溯：`04_constraints.py` 中间因子相关 assert 的边界值在文档中有对应描述 | 移除无依据的 assert 或补充文档依据 |

#### 3 约束求解校验

使用 `generate_factor_values.py --validate` 模式进行约束正确性校验（少量样本试探性求解，输出约束满足率报告和告警）。

**校验命令**：

```bash
python skills/ascendc-st-design/scripts/generate_factor_values.py \
    operators/{operator_name}/tests/st/design/02_test_factors.yaml \
    --constraints operators/{operator_name}/tests/st/design/04_constraints.py \
    --param-desc operators/{operator_name}/tests/st/design/01_parameter_description.md \
    --validate \
    --topology-out operators/{operator_name}/tests/st/design/05_topology.md \
    --sample-size 100 \
    --seed 42
```

仅生成拓扑（不校验）：添加 `--topology-only` 参数（无需 `--validate`/`--sample-size`/`--param-desc`）。

**校验结果判定**：

`--validate` 执行后检查引擎日志告警前缀。完整告警前缀对照表（含 [CONTRACT]/[CONSTRAINT-CONSERVATION]/[TRACE-STRATEGY-MISMATCH]/[SOURCE-UNUSED] 等 18 项）及修复路径见 [testcase-validation-guide.md §4.2](references/testcase-validation-guide.md)。

**通过条件**：无 [CONTRACT]/[CONSTRAINT-CONSERVATION]/[TRACE-STRATEGY-MISMATCH]/[SOURCE-UNUSED] 告警，NaN 丢弃率 0%，约束满足率 100%，域可达率 100%。不满足时按 [testcase-validation-guide.md §4](references/testcase-validation-guide.md) 统一修复路径处理。

**工具参数**：`--validate`（校验模式）、`--topology-only`（仅拓扑）、`--sample-size N`、`--topology-out PATH`、`--seed N`。详细说明见 `python generate_factor_values.py --help`。

### 4.2 阶段 B：用例生成

使用 `generate_test_cases.py` 脚本。由于 L0 和 L1 算法复杂度较高，建议分两步执行，并设置 **5分钟超时**（在调用 Bash 工具时设置 `timeout=300000`）。

**生成命令（单一 design/ 目录）**：

```bash
python skills/ascendc-st-design/scripts/generate_test_cases.py \
    operators/{operator_name}/tests/st/design/02_test_factors.yaml \
    operators/{operator_name}/tests/st/testcases/ \
    --constraints operators/{operator_name}/tests/st/design/04_constraints.py \
    --level L0 L1 L2 \
    --csv-mode {aclnn|kernel|torchapi} \
    --verbose
```

`--csv-mode` 由 `00_interface_type.yaml` 的 `generate_for` 决定（aclnn/torchapi→`aclnn`；reg_op→`kernel`）。如需为另一接口生成，重新执行步骤 1.2 切换 `generate_for`。

**用例级别概要**：
- L0（≤200，单因子覆盖）
- L1（≥500，两两组合覆盖）
- L2（≤200，异常场景覆盖：维度异常、dtype异常、场景枚举EX异常）

详细覆盖策略见 [standards.md](references/standards.md)。工具参数见 `python generate_test_cases.py --help`。

**输出文件**：

| 级别 | 文件名 | 说明 |
|------|-------|------|
| L0 | `{operator_name}_l0_functional.csv` | 功能用例（单因子覆盖） |
| L1 | `{operator_name}_l1_functional.csv` | 功能用例（两两组合覆盖） |
| L2 | `{operator_name}_l2_exception.csv` | 异常用例（场景驱动 + 引擎自动生成） |

**用例保存规则**：
- ET（空tensor）和 BD（边界值）为合法场景/边界用例，保存至 **L0/L1 CSV**
- EX（异常）为异常用例，保存至 **L2 CSV**

其中 `{operator_name}` 取自 `02_test_factors.yaml` 顶层的 `operator_name` 字段。aclnn 模式下为 `aclnn{Op}`，kernel 模式下为算子名（如 `AddN`）。

### 4.3 用例自检与修复

`generate_test_cases.py` 自动执行三层自检（格式合法性 → 约束正确性 → 域覆盖率）。修复-重跑循环最多 3 轮（阶段 A 和 B 共享预算），详见 [testcase-validation-guide.md](references/testcase-validation-guide.md)。

### 4.4 阶段 C：自动校验（必选）

阶段 B 完成后，**必须立即**执行本阶段。使用 `qa_verify_oracle.py` 自动执行校验，作为不可跳过的脚本门禁。

**校验命令**：

```bash
# 单一 design/ 目录校验（csv-mode 由 00_interface_type.yaml 决定）
python skills/ascendc-st-design/scripts/qa_verify_oracle.py \
    --csv-l0 operators/{operator_name}/tests/st/testcases/{operator_name}_l0_functional.csv \
    --csv-l1 operators/{operator_name}/tests/st/testcases/{operator_name}_l1_functional.csv \
    --factors operators/{operator_name}/tests/st/design/02_test_factors.yaml \
    --constraints operators/{operator_name}/tests/st/design/04_constraints.py \
    --param-desc operators/{operator_name}/tests/st/design/01_parameter_description.md \
    --scenarios operators/{operator_name}/tests/st/design/03_scenario_enumeration.md \
    --csv-mode {aclnn|kernel|torchapi} \
    --output operators/{operator_name}/tests/st/design/qa_auto_report.md
```

**通过条件**：退出码 = 0。

**不通过处理**：退出码非 0 → 根据报告定位问题 → 回退修复 → 最多 3 轮。

**覆盖的检查项**：产品支持、值域分析、tensor组数一致性、YAML域值一致性、存在性约束、参数值域文档一致性，以及 ET场景完备性、ET场景变量存在性、BD边界值与01一致性、EX异常有效性、EX预期错误码完整性、场景ID格式正确性（Q7~Q12）、ET/BD/EX场景用例覆盖（Q13~Q15）。完整映射和修复路径见 [testcase-validation-guide.md §4.3](references/testcase-validation-guide.md)。

### 4.5 阶段 D：保存评审报告（必选，必须写入文件）

阶段 C 通过后，**必须**将评审结果写入 `DESIGN_DIR/06_review_report.md`（禁止仅在对话中输出）。报告格式和必填章节详见 [testcase-validation-guide.md §5](references/testcase-validation-guide.md)。

---

## 步骤 5：测试设计结果总结

**前置条件**：步骤 4 全部阶段完成，`05_topology.md`、L0/L1 CSV、`06_review_report.md` 均存在，否则回退步骤 4。

在 `operators/{operator_name}/tests/st/` 目录总结算子测试设计过程与结果：

- 参数功能说明内容清洗
- 从参数说明直接生成测试因子（含 intermediate 区段）
- 编写约束模块（场景枚举 + 约束追溯表 + @solves 函数实现）
- 约束校验与测试用例生成（引擎自动拓扑排序 + 隐式推导 + L0/L1/L2 用例）

---

## 参考文件索引

### 技能文档

- **[parameter-cleaning-guide.md](references/parameter-cleaning-guide.md)** — 参数功能说明内容清洗指南（含已知问题、清洗流程、输出格式模板和完整示例）
- **[torchapi-cleaning-guide.md](references/torchapi-cleaning-guide.md)** — torchapi 参数清洗指南（Python 签名解析、bullet-list 提取、无错误码的约束挖掘策略、中间因子命名约定）
- **[test-factor-mapping-rules.md](references/test-factor-mapping-rules.md)** — 01_parameter_description.md 到 02_test_factors.yaml 映射规则
- **[standards.md](references/standards.md)** — 算子验收标准和用例级别规范
- **[constraint-writing-guide.md](references/constraint-writing-guide.md)** — 场景枚举（§0）+ 约束编写指南（§1~§2 规范、§3 中间因子、§4 约束翻译模式、§4.6 验证函数）
- **[testcase-validation-guide.md](references/testcase-validation-guide.md)** — 用例自检机制、约束诊断流程、阶段 C 失败诊断、统一修复路径和评审报告格式
- **[assert-templates.md](references/assert-templates.md)** — 约束函数 assert 模板速查表、工具函数和示例
- **[format-constraints.md](references/format-constraints.md)** — Format 维度约束参考（固定维度格式表、可变维度格式表、C0 计算规则、format→dimensions 约束编写指导）

### 自动化工具

- **[scripts/generate_factor_values.py](scripts/generate_factor_values.py)** — 约束校验与拓扑可视化工具（`--validate` 校验模式、`--topology-only` 拓扑生成）
- **[scripts/generate_test_cases.py](scripts/generate_test_cases.py)** — 测试用例生成脚本（支持L0/L1/L2）
- **[scripts/qa_verify_oracle.py](scripts/qa_verify_oracle.py)** — QA 自动校验引擎（自动执行交叉产物一致性检查）
- **[scripts/solver/](scripts/solver/)** — 求解引擎核心模块（@solves 装饰器、拓扑排序、内置推导、引擎主体、共享工具函数）
