# 约束编写指南

本文档为编写 `04_constraints.py` 约束模块提供完整参考：先通过**场景枚举**（§0）确保每条约束的语义空间被完整覆盖，再按 `@solves` 规范（§1~§4）实现约束函数。

---

## 0. 场景枚举（@solves 前置步骤）

约束关系被正确识别 ≠ 约束被正确实现。最常见的缺陷是**语义折叠**：@solves 只实现了最简子场景（如将"广播"实现为"完全相同 shape"），覆盖率报告不会报警。场景枚举在写 @solves 之前显式列出每条约束的所有合法子场景，作为实现的设计依据。

### 0.1 识别需要枚举的约束

从 `01_parameter_description.md` 提取参数间约束关系。
**优先从 `## 约束关系` 章节读取**（若有）；若无此章节，从"补充说明"列提取。
按以下规则判定是否需要枚举：

**1. 模式速查**（约束描述匹配以下关键词时，直接判定）：

> **解析顺序规则**：约束文本按速查表从上到下进行匹配，**第一个命中的行即为最终分类**。
> "推导规则/互推导"行排在"一致/相同/等于"之前，确保"推导之后的...一致"模式优先命中推导规则而非相等规则。
> **多子句约束处理**：若一条约束描述含分号（`；`/`;`）分隔的多个独立子句，**必须先按分号拆分为独立子约束**，再对每条子约束分别匹配速查表。

| 关键词 | 子场景数 | 说明 |
|--------|---------|------|
| 广播 / broadcast | ≥ 3 | 含：完全相同、含 size=1 维、ndim 不同 |
| 可转换 / convertible / 兼容 | ≥ 2 | 含：exact match、兼容但不同 |
| 推导规则 / 互推导 / 满足推导 | ≥ 2 | PromoteType 运算有效即可，参数间 dtype 可以不同（详见 parameter-cleaning-guide.md §2.4）。含"推导之后的...一致"模式 |
| 映射表 / 转换路径 | ≥ 2 | 查找表映射 |
| ConvertToTensor / 接口7（链接指向 ConvertToTensor.md） | ≥ 2 | 全连接矩阵（23 种类型），含 exact match 和跨类型转换 |
| 或 / 或者（"A或广播后满足B"） | ≥ 2 | 两种路径各自独立 |
| 若 A 则 X 否则 Y | ≥ 2 | 两分支 |
| 满足公式 / 满足以下公式 | ≥ 2 | 公式中各变量的边界组合 |
| 一致 / 相同 / 等于 | 1 | 不需要枚举（单一场景） |
| 匹配 / 必须等于 | 1 | 不需要枚举 |
| 长度一致 / 个数相同 | 1 | 不需要枚举 |
| 可选 / 不存在时 / 忽略 | 1 | SKIP / NA（见 §1）；若该可选项在某场景/控制态下必须非空，见 §4.4 情况 E4 及"反模式：选择器参数 .exist 解耦" |
| 仅...时支持 / 特定...下限制 / 产品特定...限制 | ≥ 2 | 条件化域值过滤：含条件满足时的完整域、条件不满足时的受限域（见 §4 模式 8 子类型 B） |
| 每个元素值 > X / ≥ X / 元素取值范围 [...] | 1 | 元素级值域约束，不需要枚举，但需 @solves 或 validate 覆盖（见 §4 模式 15） |

**2. 单值测试法**（约束描述不匹配任何关键词时，执行通用判定）：

固定 sources 为一组典型值，检查 target 有几种合法输出：
- 只有 1 种 → 单值 return（不需要枚举）
- 有 ≥2 种 → Candidates（必须枚举）
- 不确定 → 默认 Candidates（多值优先原则）

验证方法：固定 sources 的典型值，代入约束公式，检查 target 的输出空间。

### 0.2 预设场景库

以下为常见约束关键词的标准子场景清单，直接取用：

**关键词：广播 / broadcast**

| 子场景 | 描述 | shape_list 示例（2 个 tensor） |
|--------|------|-------------------------------|
| S1 | 完全相同 shape | `[[2,3], [2,3]]` |
| S2 | 含 size=1 维度的可广播 shape | `[[1,3], [2,3]]` 或 `[[2,1], [2,3]]` |
| S3 | ndim 不同的可广播 shape | `[[3], [2,3]]` |

当 `dimensions` 因子包含 0 时，增加 S4：0D 标量参与广播 `[[], [2,3]]`。

**关键词：可转换 / convertible**

| 子场景 | 描述 | dtype 对 |
|--------|------|---------|
| S1 | 完全相同 dtype | `(float32, float32)` |
| S2 | 不同但可转换的 dtype 对 | `(float16, float32)` |

**关键词：推导规则 / 互推导**

| 子场景 | 描述 | dtype 对示例 |
|--------|------|-------------|
| S1 | 两个参数 dtype 完全相同 | `(float16, float16)` → PromoteType = float16 |
| S2 | 两个参数 dtype 不同但可推导 | `(float16, float32)` → PromoteType = float32 |
| S3 | 两个参数 dtype 不可推导（应被过滤，不计入合法子场景数） | `(bfloat16, float16)` → PromoteType = None（视查找表而定） |

**关键词：若 A 则 X 否则 Y**

| 子场景 | 描述 |
|--------|------|
| S1 | 条件 A=true 时，返回 X 分支的值 |
| S2 | 条件 A=false 时，返回 Y 分支的值 |

**关键词：满足公式**

对公式中每个变量取边界值和典型值组合：

| 子场景 | 变量取值 |
|--------|---------|
| S1 | 全部变量取最小值（各变量 = 下界） |
| S2 | 全部变量取最大值（各变量 = 上界） |
| S3 | 典型中间值 |
| S4 | 变量间的边界组合（部分上界 + 部分下界） |

当预设场景库不适用时，对约束关系的语义空间做正交分解：识别自由度 → 列举合法取值 → 取笛卡尔积。

### 0.3 输出格式与验证

将枚举结果保存至 `ops/{operator_name}/tests/st/design/03_scenario_enumeration.md`，格式如下：

```markdown
# {算子名} 场景枚举

## 约束关系清单

| ID | 约束描述 | 涉及参数 | 关键词 | 需要枚举 | @solves target |
|----|---------|---------|--------|---------|---------------|
| C1 | ... | ... | 广播 | 是 | indices.shape_list |
| C2 | ... | ... | 一致 | 否 | values.dtype |

## 子场景枚举

### C1: {约束描述}

| 子场景 ID | 描述 | @solves 应生成的值示例 |
|----------|------|---------------------|
| C1-S1 | ... | ... |

## 场景覆盖验证

（步骤 4 阶段A 执行后回填）

| 子场景 ID | 是否出现 | 出现次数 | 备注 |
|----------|---------|---------|------|
```

**子场景 ID 与 tag() 的关联**：每个子场景 ID（如 C1-S1）必须在至少一个 `@solves` 函数中有对应的 `tag()` 调用（如 `tag('scenario', 'C1-S1')`），否则 L0 场景覆盖验证会失败。`tag()` 的第一个参数为标记名称（任意字符串），第二个参数为子场景 ID 或包含子场景 ID 的字符串。详细用法见 [SKILL.md §3.3.2](../SKILL.md)。

**生成后验证**：步骤 4 阶段A（约束校验）完成后，回填枚举表的"场景覆盖验证"节，确认每个子场景至少出现一次。若某子场景未出现，定位对应 @solves 函数修复。

### 0.6 增强场景枚举（空tensor/边界值/异常）

所有增强子场景统一写在 `03_scenario_enumeration.md` 中，分三个章节。
三类场景使用**统一的 4 列表格格式**：

| 列 | 内容 | 说明 |
|----|------|------|
| 子场景 ID | `ET-S{n}` / `BD-S{n}` / `EX-S{n}` | 编号从 1 连续递增 |
| locked因子 | `key=value` 逗号分隔 | **key 必须是引擎因子名**（如 `self.shape`，非 `self`） |
| 元数据 | ET=预期输出 / BD=约束来源 / EX=预期错误码 | 列名因类型而异 |
| 测试重点 | 一句话描述 | 简述测试意图 |

#### locked因子列书写规范

**基本规则**：

| 因子类型 | 格式 | 示例 |
|---------|------|------|
| Tensor shape | `param.shape=[...]` | `self.shape=[0,3]` |
| TensorList shape | `param.shape_list=[[...],[...]]` | `tensors.shape_list=[[0,3],[2,3]]` |
| 维度数 | `param.dimensions=N` | `self.dimensions=2` |
| TensorList 个数 | `param.length=N` | `tensors.length=2` |
| 标量值 | `param.value=V` | `dim.value=0` |
| 数组值 | `param.value=[v1,v2,...]` | `dims.value=[0,1]` |
| 中间因子 | `_name.value=V` | `_b.value=0` |
| 存在性 | `param.exist=True/False` | `bias.exist=false` |
| 格式 | `param.format=FMT` | `self.format=NCHW` |
| 数据类型 | `param.dtype=dt` | `self.dtype=float32` |

多个因子用 `, ` 分隔。

**一致性约束**（同时锁定多个关联因子时必须满足）：

| 约束 | 规则 | 正确示例 | 错误示例 |
|------|------|---------|---------|
| shape↔dimensions | `len(shape) == dimensions` | `self.shape=[0,3], self.dimensions=2` | `self.shape=[0,3], self.dimensions=3` |
| shape_list↔length | `len(shape_list) == length` | `tensors.shape_list=[[0,3],[2,3]], tensors.length=2` | `tensors.shape_list=[[0,3],[2,3]], tensors.length=3` |
| shape_list[i]↔dimensions | `len(shape_list[i]) == dimensions` | `tensors.shape_list=[[0,3],[2,3]], tensors.dimensions=2` | `tensors.shape_list=[[0,3],[2,3]], tensors.dimensions=3` |
| value(Array)↔length | `len(value) == length` | `dims.value=[0,1], dims.length=2` | `dims.value=[0,1], dims.length=3` |
| format↔dimensions | 固定格式须匹配维度数 | `self.format=NCHW, self.dimensions=4` | `self.format=NCHW, self.dimensions=3` |
| exist↔其他 | `exist=false` 时不锁定同参数其他因子 | `bias.exist=false` | `bias.exist=false, bias.shape=[3]` |

**最小锁定原则**：只锁定测试意图必需的因子，其余由引擎拓扑自动推导。
例：ET场景只需 `self.shape=[0,3], self.dimensions=2`，`out.shape` 由 @solves 自动计算，无需锁定。

**派生因子锁定禁令**：03 场景的 locked 列**禁止**锁定 `@solves` 的 target（派生因子），只能锁定**锚点因子**（未被任何 `@solves` 声明为 target 的因子）。

| 禁止 | 正确替代 | 原因 |
|------|---------|------|
| `vec1.shape=[0]`（若 shape 是 `@solves` target，派生自 `_vec1_len.value`） | `_vec1_len.value=0` | 锁定派生因子不会同步更新中间体，导致下游派生（如 `out.shape`）取值不一致 |
| `out.shape=[3,4]`（若 shape 是 `@solves` target，由 broadcast 计算） | 锁定输入参数的锚点 shape | 输出 shape 应由引擎从输入自动推导 |

**检测方法**：若因子名出现在 `04_constraints.py` 的 `@solves(target, ...)` 的 target 位置，则该因子为派生因子，不应在 03 locked 列出现。步骤 4B 引擎会自动检测并打印 `[WARN]` 提示。

#### 空tensor维度场景

```markdown
## 空tensor维度场景

| 子场景 ID | locked因子 | 预期输出 | 测试重点 |
|----------|-----------|---------|---------|
| ET-S1 | _m.value=0, A.shape=[0,k], A.dimensions=2, B.shape=[k,n], B.dimensions=2 | C.shape=[0,n] | 空→空 |
| ET-S2 | _k.value=0, A.shape=[m,0], A.dimensions=2, B.shape=[0,n], B.dimensions=2 | C.shape=[m,n] | 空→非空 |
| ET-S3 | _n.value=0, A.shape=[m,k], A.dimensions=2, B.shape=[k,0], B.dimensions=2 | C.shape=[m,0] | 空→空 |
```

#### 边界值场景

```markdown
## 边界值场景

| 子场景 ID | locked因子 | 约束来源 | 测试重点 |
|----------|-----------|---------|---------|
| BD-S1 | self.shape=[1,1], self.dimensions=2 | 默认兜底 | 下边界 |
| BD-S2 | self.shape=[1,2147483648], self.dimensions=2, _k.value=1 | 默认兜底 | 上边界 |
| BD-S3 | minlength.value=0 | 01取值范围"≥0" | 值域下界 |
```

#### 异常场景

```markdown
## 异常场景

| 子场景 ID | locked因子 | 预期错误码 | 测试重点 |
|----------|-----------|-----------|---------|
| EX-S1 | key.dimensions=5 | ACL_ERROR_INVALID_DIMENSION | 维度超出 |
| EX-S2 | dtype.value=1 | ACL_ERROR_INVALID_PARAM | 枚举外 |
| EX-S3 | self.dimensions=3, dim.value=3 | ACL_ERROR_INVALID_PARAM | dim值越界 |
| EX-S4 | slotMapping.value=[3,3] | ACL_ERROR_INVALID_PARAM | 值重复 |
```

#### 上边界场景定义规范

> **核心规则**：上边界 shape（某轴为 `INT32_MAX = 2147483648`）必须在 03 的 BD 场景中定义，且**必须同步锁定相关中间变量为 1**。
>
> **原因**：若仅锁定单个参数的 shape 为极大值（如 `batch1.shape=[1,1,2147483648]`），依赖该 shape 的其他参数（如 `batch2.shape=[b,2147483648,n]`）在求解时，`validate_shape` 会检查 product = `b * 2147483648 * n`。由于中间变量 `_b.value`、`n` 在 value_range 中随机取值，product 大概率超过 `INT32_MAX`，导致求解失败。
>
> **正确做法**：在 locked因子 列中同时设置 shape 和相关中间变量为 1：
> ```markdown
> | BD-S6 | batch1.shape=[1,1,2147483648], batch1.dimensions=3, _b.value=1, _n.value=1 | 默认兜底 | 上边界 |
> ```
> 此时 `batch2.shape = [1, 2147483648, 1]`，product = 2147483648 ≤ INT32_MAX，100% 求解成功。
>
> **禁止**：仅锁定 shape 而不控制中间变量。

#### 异常类型映射

| 异常类型（表格中填写） | `_exception_type` | `_expected_error` 建议值 |
|----------------------|-------------------|------------------------|
| shape_boundary | `shape_boundary_exceed` | `ACL_ERROR_INVALID_DIMENSION` |
| enum_range | `enum_out_of_range` | `ACL_ERROR_INVALID_PARAM` |
| constraint | `constraint_violation` | `ACL_ERROR_INVALID_PARAM` |
| index_out_of_range | `index_out_of_range` | `ACL_ERROR_INVALID_PARAM` |
| dim_value_out_of_range | `dim_value_out_of_range` | `ACL_ERROR_INVALID_PARAM` |
| value_duplicate_array | `value_duplicate_array` | `ACL_ERROR_INVALID_PARAM` |
| value_duplicate_tensor | `value_duplicate_tensor` | `ACL_ERROR_INVALID_PARAM` |

#### 场景定义自检Checklist

LLM完成03场景文件后，必须逐项自检：

- [ ] **格式**: 所有场景使用统一4列格式（子场景 ID / locked因子 / 元数据 / 测试重点）
- [ ] **因子名**: locked因子列中所有key均为引擎因子名（含`.`后缀，如`self.shape`），无裸参数名
- [ ] **一致性**: 同时锁定的关联因子满足一致性约束（shape↔dimensions、shape_list↔length等）
- [ ] **空tensor**: 每个中间变量（value_range下界≤0）都有对应的ET-S{n}
- [ ] **空tensor**: ET-S{n}的locked因子中的变量名在02_test_factors.yaml中存在
- [ ] **空tensor**: ET-S{n}的"预期输出"经过约束函数计算验证（手动代入确认）
- [ ] **一致性**: 每个ET-S{n}的locked因子代入`validate_constraints`后应返回**空列表**（合法场景不得违反任何约束）；若返回非空，说明该场景与约束矛盾，应移至EX异常场景
- [ ] **异常覆盖**: 每个R{n}约束的每种违反方式都应有对应的EX-S{n}覆盖（检查是否存在"约束有但场景无"的缺口，如C9空tensor一致性要求"同时为空"，则"部分为空"必须有EX场景）
- [ ] **边界值**: BD-S{n}的locked因子与01_parameter_description.md中的约束描述一致
- [ ] **边界值**: 无明确约束的参数，默认兜底已覆盖min/mid/max维度
- [ ] **异常**: EX-S{n}的locked因子中的变量名在02_test_factors.yaml中存在
- [ ] **异常**: EX-S{n}构造的异常用例代入约束函数后，validate_constraints应返回非空列表
- [ ] **异常**: 每个EX-S{n}的"预期错误码"列都有明确的`ACL_ERROR_*`值
- [ ] **命名**: 所有子场景ID格式正确（ET-S{n}/BD-S{n}/EX-S{n}，n从1递增）
- [ ] **正交**: ET/BD/EX三类场景之间无重复锁定变量（如同一参数同一属性不在ET和BD中同时锁定）
- [ ] **派生因子**: locked因子列中无 `@solves` target 因子（派生因子），只锁定锚点因子（检查方法：因子名不出现在 `04_constraints.py` 的 `@solves(target, ...)` 的 target 位置）

#### 空tensor与约束一致性原则

> **核心规则**：定义 ET 空tensor场景前，必须先检查该场景是否违反已有约束（如 C9 空tensor一致性）。
>
> 若约束要求"所有相关 tensor 同时为空"，则 ET 场景中必须**同时**将所有相关 tensor 设为空，不能只设其中一个为空而其他非空。此类"部分为空"的情况应定义为 **EX 异常场景**，而非 ET 合法场景。
>
> **示例**（aclnnAddbmm）：
> - C9 要求 batch1/batch2/self 同时为空或非空。
> - ❌ 错误：ET-S1 定义 `batch1.shape=[0,m,k], batch2.shape=[0,k,n], self.shape=[m,n]`（batch 为空但 self 非空，违反 C9）。
> - ✅ 正确：ET 场景应同时设 batch1/batch2/self 为空；`batch1.shape=[0,m,k], self.shape=[m,n]` 应定义为 EX-S7（约束违反）。

---

## 1. `@solves` 装饰器规范

```python
from solver import solves, Candidates, SKIP, NOT_APPLICABLE
from solver.tags import tag

@solves(target, sources)
def solve_xxx(source_1_value, source_2_value, ...):
    ...
```

| 参数 | 说明 |
|------|------|
| `target` | `str`，目标因子名，如 `'out.shape'` |
| `sources` | `list[str]`，依赖的源因子列表，顺序与函数参数一一对应 |

**`sources=[]` 语义**：无依赖，值由函数逻辑确定。拓扑排序中归入 Level 0。典型场景：固定维度数（`return 3`）。

### 1.1 装饰器语法

见上方代码模板。

### 1.2 返回值语义

| 返回值 | 引擎行为 | 适用场景 |
|--------|---------|---------|
| 单个值（`3`、`"FLOAT16"`） | 直接赋值 | 固定推导 |
| 单个列表（`[1,2,3]`） | 直接赋值（shape 等） | shape 计算 |
| `Candidates([v1, v2, ...])` | 扩展 BC 组合，每个值生成独立用例 | convertible、broadcast |
| 空列表 `[]` | 设为空值 | dim 为空 |
| `SKIP` | 因子值不由当前约束决定，引擎从 L0 域采样 | 中间因子条件不满足；参数因子无约束且不参与 pairwise |
| `NOT_APPLICABLE` | 标记因子不适用 | 可选参数不存在 |

**`Candidates`** 是 `list` 的子类，仅用于标记"多候选值"，消除普通列表（shape）与候选列表的歧义。建议单次返回不超过 128 个候选值。

**`SKIP`**：`@solves` 函数在"当前约束对 target 无限制"时返回 `SKIP`，引擎从 L0 域采样。
- **中间因子**：条件不满足时返回 `SKIP`（推荐）
- **参数因子**：仅在 target 无需参与 pairwise 组合时使用 `SKIP`。若 target 是离散因子（`.exist`、`.dtype`、`.format`）且需参与 L1 pairwise 覆盖，必须使用 `Candidates()` 显式枚举所有合法值。`SKIP` 在 `_compute_solved_domain` 中被映射为空值列表，会导致因子被排除出 pairwise 组合。

**`NOT_APPLICABLE`**：用于可选参数不存在时。引擎将 target 标记为不适用，后续依赖此因子的函数将收到 `None`。

**函数内 assert**：可使用 `assert` 表达约束校验。失败时引擎跳过当前组合，不影响其他组合。

**离散因子强制规则**：
1. 离散因子（dtype、format、exist等有限值域）的组合覆盖禁止使用 `random.choice()`，
   必须使用 `Candidates()` 枚举所有合法值
2. 约束语义非"等于/一致"时，返回 `Candidates()` 而非单值
3. 含"若...则...否则"条件时，函数必须有 if/else 完整覆盖所有分支

---

## 2. 方向选择规则

`@solves` 是单向声明。当参数间存在双向约束关系时，需显式选择一个方向。选择方向 = 决定谁是锚点 = 决定**不写** `@solves` 的那个因子。

### 优先级规则

| 条件 | 锚点（不写 @solves） | 推导（写 @solves 的 target） |
|------|---------------------|---------------------------|
| A 是 input，B 是 output | A | B |
| A 是 Tensor，B 是 Scalar | A | B |
| A 在函数原型中先于 B | A | B |
| A 是主参数（如 self），B 是辅参数 | A | B |

### 示例：多参数推导链

```
函数原型: addbmm(self, batch1, batch2, beta, alpha, out)

类型约束链:
  batch1.dtype → 锚点（matmul 主输入）
  batch2.dtype ← 从 batch1.dtype 推导
  self.dtype   ← 从 batch1 + batch2 联合推导
  out.dtype    ← 等于 self.dtype（output ← input）
```

```python
# R{n}="推导规则" → 模式 1.5：类型推导（PromoteType）
@solves('batch2.dtype', sources=['batch1.dtype'])
def solve_batch2_dtype(batch1_dtype):
    from utils import infer_two_dtypes
    valid = [d for d in TENSOR_DTYPE_DOMAIN
             if infer_two_dtypes(batch1_dtype, d) is not None]
    return Candidates(valid)

# R{n}="推导+转换" → 模式 1.5 + 模式 2 复合：self 可转换为 PromoteType(batch1, batch2)
@solves('self.dtype', sources=['batch1.dtype', 'batch2.dtype'])
def solve_self_dtype(batch1_dtype, batch2_dtype):
    from utils import infer_two_dtypes, can_convert_dtype
    promote_result = infer_two_dtypes(batch1_dtype, batch2_dtype)
    if promote_result is None:
        return Candidates([])
    valid = [d for d in TENSOR_DTYPE_DOMAIN
             if can_convert_dtype(d, promote_result)]
    return Candidates(valid)

@solves('out.dtype', sources=['self.dtype'])
def solve_out_dtype(self_dtype):
    return self_dtype
```

---

## 3. 中间因子

### 3.1 定义与类型

部分算子存在共享语义变量（如 `batch`、`dim`），它们驱动多个参数的 shape/value，但本身不是算子参数。在 `02_test_factors.yaml` 中新增 `intermediate` 区段定义：

**值域随机采样**（推荐，适用于连续值域）：

```yaml
intermediate:
  _batch:
    type: int64_t
    factors:
      _batch.value_range: [[0, 2147483648]]
```

引擎为每个 combo 从 `[0, 2147483648]` 随机取一个值赋给 `_batch.value`。不参与锚点笛卡尔积，不导致组合爆炸。

**约束推导**（值域有额外约束时，value_range + `@solves` 约束函数）：

```yaml
intermediate:
  _dim:
    type: int64_t
    factors:
      _dim.value_range: [[128, 16384]]
```

```python
# 04_constraints.py
@solves('_dim.value', sources=['_dim.value_range'])
def solve_dim_value(value_range):
    import random
    lo, hi = value_range
    candidates = []
    for _ in range(20):
        v = random.randint(lo, hi)
        if v % 128 == 0:
            candidates.append(v)
    if not candidates:
        raise AssertionError(f"no valid value in [{lo}, {hi}] divisible by 128")
    return random.choice(candidates)
```

**显式枚举**（枚举值直接列出）：

```yaml
intermediate:
  _scenario: # 场景变量
    type: int64_t
    factors:
      _scenario.value: [0, 1, 2]
```

中间因子分两类：

| 行为 | 纯锚点中间因子（◆） | 推导中间因子（◇） |
|------|-------------------|-----------------|
| 识别条件 | 无 `@solves` 将其声明为 target | 有 `@solves` 将其声明为 target |
| 域定义 | **必须**在 YAML 中定义 | 可省略（值由 `@solves` 计算） |
| 求解方式 | Level 0 从域采样 | 按 `@solves` 拓扑排序后求解 |
| CSV 输出 | 排除 | 排除 |

### 3.2 识别与判定

**识别信号**：扫描 `01_parameter_description.md` 的以下信号：

| 信号 | 文本模式 | 含义 |
|------|---------|------|
| S1 | shape 公式中出现非参数名的变量 | `batch`、`dim` 是语义变量 |
| S2 | 变量有明确的值域约束 | 可提取中间因子的域 |
| S3 | 多个参数的 shape 依赖同一变量 | 该变量是共享维度 |
| S4 | 同一属性值下存在多个子场景 | 需要 `_scenario` 因子 |
| S5 | shape 描述含算术关系（如 `K-1+m`） | `m` 独立于参数 |

**必要性判定**：

| 规则 | 条件 | 判定 |
|------|------|------|
| R1 | 该变量同时驱动 ≥ 2 个参数的 shape/value？ | 是 → 倾向需要 |
| R2 | 该变量不在任何单个参数的 shape 中可直接获取？ | 是 → 需要 |
| R3 | 该变量有独立的值域约束？ | 是 → 倾向需要 |
| R4 | 是否存在多个场景导致同一参数的 shape 结构不同？ | 是 → 需要 `_scenario` |
| R5 | 该变量在所有场景下均可从某个参数的 shape 中提取？ | 是 → **不需要**（排除规则，优先级最高） |

满足 ≥ 2 条（R5 除外）即需要中间因子。

### 3.3 域值生成与溯源

| 模式 | YAML 定义 | 生成方式 | 适用场景 |
|------|----------|---------|---------|
| 值域随机 | `_name.value_range: [[min, max]]` | 每个 combo 随机取一个值 | batch、seq_len 等连续值域 |
| 约束推导 | `_name.value_range` + `@solves` 约束函数 | 约束函数按条件生成合法值 | "128的倍数"、"偶数"等受限值域 |
| 显式枚举 | `_name.value: [v1, v2, ...]` | 直接使用 | 场景选择、枚举值（≤10 个） |

**约束推导要点**：

1. 在 YAML 中定义 `_name.value_range` 声明值域范围
2. 在 `04_constraints.py` 中写 `@solves('_name.value', sources=['_name.value_range'])` 约束函数
3. 函数内按约束条件（如 `v % 128 == 0`）从范围中筛选合法值
4. 无合法值时 `raise AssertionError()` 让引擎丢弃该组合

**模式选择决策树**（强制）：对每个中间因子，**必须**按以下流程选择域值生成模式：

```
该变量的值域是否有文档明确约束？
├─ 是：约束是否将值域限制为有限离散集合？
│   ├─ 是：集合大小 ≤ 10？
│   │   ├─ 是 → 显式枚举（_name.value: [v1, v2, ...]）
│   │   └─ 否 → 约束推导（value_range + @solves）
│   └─ 否（约束为倍数、奇偶等无限集合）→ 约束推导（value_range + @solves）
└─ 否：变量是否为场景选择器（_scenario）或天然离散变量（如硬件枚举类型、有限布局选项）？
    ├─ 是 → 显式枚举（溯源标注：场景枚举表 / 硬件规格 / 接口定义）
    └─ 否 → 值域随机（_name.value_range: [[min, max]]）
```

**关键判断标准**：

- "文档明确约束"：指 `01_parameter_description.md` 的约束说明、取值范围列或补充说明列中有明确文本
- "天然离散变量"：指变量语义上只取有限个值（如硬件支持的布局类型有且仅有 3 种），需在溯源注释中注明依据
- 场景选择器（`_scenario`）是最常见的天然离散例外：无文档约束但使用显式枚举，因其语义是枚举场景编号
- 文档未约束的连续变量使用 `value_range`，禁止使用 `.value` 离散枚举

**文档溯源**（强制）：每个中间因子的域值定义**必须**在 YAML 注释中标注来源，格式为 `# 来源: {文档位置}`。

**示例**：

```yaml
intermediate:
  _scenario:
    type: int64_t
    factors:
      _scenario.value: [0, 1, 2, 3]
      # 来源: 03_scenario_enumeration.md C1 子场景 C1-S1~C1-S4

  _block_size:
    type: int64_t
    factors:
      _block_size.value_range: [[0, 1024]]
      # 来源: aclnn接口文档约束说明 "block_size取值为16的倍数，最大支持1024"

  _batch:
    type: int64_t
    factors:
      _batch.value_range: [[0, 2147483648]]
      # 来源: 文档未约束B的取值范围，shape轴默认值域；如果支持空tensor，定义为[[0, 2147483648]]；不支持空tensor，定义为[[1, 2147483648]]
```

**溯源标注规则**：

| 模式 | 溯源要求 |
|------|---------|
| 显式枚举 | 标注每个枚举值的文档来源（如"场景枚举表 C1-S1~S4"、"文档取值范围列"） |
| 约束推导 | 标注约束条件的文档来源（如"约束说明：block_size 为 16 的倍数"） |
| 值域随机 | 标注"文档未约束"，上界/下界需注明确定依据（如"测试资源预算"、"硬件限制"） |

**自检规则**：若溯源标注为"文档未约束"，则**禁止**使用 `.value` 离散枚举，必须使用 `value_range`。

### 3.3.1 场景相关值域中间因子

当中间因子的文档值域因算子场景不同而变化时（如 prefill 场景 `cu_seq_len ∈ [batch, 1024*1024]`，decode 场景 `cu_seq_len ∈ [batch, batch*8]`），采用以下模式：

1. **YAML `value_range`** = 所有场景文档范围的**并集**（最大范围），按 [test-factor-mapping-rules.md §6.3](test-factor-mapping-rules.md) S1 分段规则覆盖
2. **`@solves` 按场景收窄**：声明 `_scenario.value` 等场景因子为 source，在函数内按场景分支收窄到该场景的文档范围
3. 每个分支的 docstring/注释必须引用对应的文档约束原文

> 核心原则：YAML 声明的是**值域定义**（覆盖文档最宽范围），`@solves` 负责**场景收窄**（按场景取子集）。两者职责分离，禁止将场景收窄逻辑前置到 YAML 域定义中。
>
> 简短示例参见 [test-factor-mapping-rules.md §6.3.1 反模式示例](test-factor-mapping-rules.md)（`_cu_seq_len` 的 YAML + @solves 完整写法）。

### 3.3.2 多维度Product约束的预算分配模式

当多个中间因子（或shape维度）的乘积受上限约束（如 `product(shape) ≤ 2G`）时，**禁止**将这些维度定义为独立采样的锚点中间因子——独立采样几乎必然违反product约束，导致assert拒绝率接近100%。

**正确模式A**：单@solves控制整个shape
- @solves函数内部调用 `generate_random_shape(dimensions, dtype=dtype)` 从 utils 模块分配预算
- 不定义 `_batch`、`_num_blocks` 等独立维度中间因子，或仅定义但不作为锚点采样
- 适用于shape维度无跨参数共享的场景

```python
@solves('key.shape', sources=['key.dimensions', '_scenario.value', 'key.dtype'])
def solve_key_shape(dimensions, scenario, dtype):
    from utils import generate_random_shape
    shape = generate_random_shape(dimensions, dtype=dtype)
    # Apply scenario-specific adjustments
    ...
    return shape
```

**正确模式B**：预算感知的共享维度中间因子
- 定义中间因子但将其设为@solves target（非锚点），使用预算分配逻辑生成值
- 适用于多个tensor共享同一维度的场景（如 key 和 value 共享 batch）

```python
@solves('_batch.value', sources=['_scenario.value', '_num_head.value', '_seq_len.value', '_k_head_size.value', 'key.dtype'])
def solve_batch_value(scenario, num_head, seq_len, k_head_size, dtype):
    # Calculate remaining budget after other dimensions are determined
    dtype_bytes = get_dtype_bytes(dtype)
    remaining_budget = MAX_SHAPE_PRODUCT // (num_head * seq_len * k_head_size * dtype_bytes)
    # Sample batch within remaining budget
    import random
    return random.randint(1, min(remaining_budget, 2147483648))
```

**反模式**：为受product约束的维度分别定义value_range锚点中间因子并独立采样
```yaml
# ❌ 错误：独立采样的中间因子会导致product远超2G
_batch.value_range: [[1, 2147483648]]  # 独立采样可能取到1G
_num_blocks.value_range: [[1, 2147483648]]  # 独立采样可能取到1G
# product ≈ (1G)^2 >> 2G，assert全部失败
```

**`generate_random_shape` 函数说明**（来自 utils.py）：
- 输入：`dimensions`（维度数）、`dtype`（数据类型）、可选 `max_product`（默认 2147483648）
- 使用 5 种分配规则：avg（均分）、shuffle（随机分配）、max（某维度最大）、split_dim（分裂某维度）、min（某维度最小）
- 所有规则保证 `product(shape) ≤ max_product`
- 返回满足约束的 shape list[int]

### 3.4 跨层级联合约束

**问题**：当中间因子 X 同时被多个 `@solves` 函数消费时，若其中一个函数的 sources 包含另一个不含的因子 Y（如 dtype、format），且 Y 影响 X 在该函数中的有效值，则会产生跨函数不一致——不知道 Y 的函数使用 X 的原值，知道 Y 的函数使用 X 的调整值。

**检查流程**（步骤 3 完成后执行）：

1. 列出所有被 ≥2 个 `@solves` 消费的中间因子 X
2. 对每个 X，比较所有消费者的 sources，找出差集 Y = sources(C) \ sources(B)
3. 对每个差集因子 Y，检查含 Y 的函数 C 中 Y 是否影响 X 的有效值
4. 若影响，将 Y 加入不含 Y 的消费者的 sources

**识别信号**（满足任一条即需检查是否影响有效值）：

| 信号 | 表现 |
|------|------|
| S1：参数赋值变异 | C 的函数体内对 X 对应的参数做了赋值修改（如 `x = aligned_value`） |
| S2：Y 衍生常量除法 | X 在公式中被从 Y 衍生的常量除或取模（如 `X // last_dim`，其中 `last_dim = f(Y)`） |

**示例**：

```
# 中间因子 _k_head_size 被两个函数消费:
@solves('key.shape', sources=[..., '_k_head_size.value'])
def solve_key_shape(..., k_head_size):          # ← B: 不知道 key.dtype
    return [bs, num_head, k_head_size]           #    使用原值

@solves('keyCacheRef.shape', sources=[..., '_k_head_size.value', 'key.dtype', ...])
def solve_key_cache_shape(..., k_head_size, key_dtype, ...):  # ← C: 知道 key.dtype
    alignment = 32 / _DTYPE_BYTES[key_dtype]     # S1: k_head_size 被赋值修改
    k_head_size = aligned_value                   #    X 的有效值被 Y 改变
    ...
```

差集 Y = {key.dtype}，信号 S1 命中 → 将 `key.dtype` 加入 `solve_key_shape` 的 sources。

### 3.5 命名约定与迭代

- 以 `_` 前缀命名，与算子参数区分（如 `_batch`、`_dim`、`_scenario`）
- 因子名格式：`{name}.value`、`{name}.length` 等
- 约 70% 的算子无需中间因子

中间因子的定义在步骤②，但必要性可能在步骤③编写 `@solves` 时才完全显现。此时回退步骤②补充 `intermediate` 区段。最大迭代 3 次。

**迭代触发信号**：编写 `@solves` 时，`sources` 列表中的因子名在 `02_test_factors.yaml` 中无对应定义。

---

## 4. 约束翻译模式

> **约束描述与翻译模式对应**：从 `01_parameter_description.md` R{n} 的约束描述中，
> 通过 §0.1 的模式速查或单值测试法确定是否需要枚举，再选择对应的翻译模式——
> - 不需要枚举（单值） → 模式1（类型等值）、模式3（shape公式）、模式5（维度匹配）、模式9（长度耦合）等
> - 需要枚举（多值） → 模式1.5（类型推导）、模式2（类型可转换）、模式4（广播）、模式11（多场景）、模式13（查找表映射）等
> - SKIP / NOT_APPLICABLE → 模式7（存在性依赖）
>
> **通用判定原则**：见 §0.1 单值测试法。离散因子应使用 `Candidates()` 枚举而非 `random.choice()`，详见 §1.2 离散因子强制规则。

### 4.0 模式速查表

从 `01_parameter_description.md` R{n} 约束描述匹配关键词，确定翻译模式、返回类型和工具函数。

| 约束关键词 | 模式 | 返回类型 | 工具函数 | 分组 |
|-----------|------|---------|---------|------|
| 一致/相同/等于 | 1 类型等值 | 单值 | 无需 | 4.1 |
| 推导规则/互推导 | 1.5 类型推导 | Candidates | TT:`infer_two_dtypes`; TS:`infer_tensor_scalar_dtypes` | 4.1 |
| 推导后一致 | 1.5 (推导后一致) | 单值(infer结果) | 同1.5 | 4.1 |
| 推导后转换 | 1.5+2 复合 | Candidates | infer + can_convert | 4.1 |
| 可转换/兼容 | 2 类型可转换 | Candidates | TT:`can_convert_dtype`系列; TS:`can_convert_to_tensor`系列 | 4.1 |
| ConvertToTensor/接口7 | 2 (CTT) | Candidates | `can_convert_to_tensor` | 4.1 |
| shape公式 | 3 Shape计算 | 单值(列表) | 无需 | 4.2 |
| 广播/broadcast | 4 广播 | Candidates | `broadcast_shapes()` | 4.2 |
| 必须等于/匹配 | 5 维度匹配 | 单值 | 无需 | 4.2 |
| 取值范围+唯一性 | 6 Array值 | 单值/列表 | 无需 | 4.3 |
| 长度一致/个数相同 | 9 长度耦合 | 单值 | 无需 | 4.3 |
| ≤ / 长度上界 | 10 长度上界 | [[min,max]] | 无需 | 4.3 |
| 可选/不存在时 | 7 存在性 | NOT_APPLICABLE | 无需 | 4.4 |
| 当...时/若...则 | 8 条件化 | 条件分支 | 无需 | 4.4 |
| 场景/多场景 | 11 多场景 | 条件分支 | 无需 | 4.5 |
| 值级跨参数 | 12 值级耦合 | 单值/列表 | 无需 | 4.5 |
| 映射表/转换路径 | 13 查找表 | Candidates | `expand_lookup()` | 4.5 |
| 列表内部互推导(TensorList) | 14 离散枚举 | Candidates | `infer_two_dtypes` | 4.5 |
| 每个元素>/>=/</值域 | 15 元素值域 | SKIP+validate | 无需 | 4.5 |

### 4.1 类型约束

#### 模式1：类型等值

**识别关键词**：`一致`、`等于`、`相同`

```python
@solves('out.dtype', sources=['dtype.value'])
def solve_out_dtype(dtype_value):
    return dtype_value
```

#### 模式1.5：类型推导（PromoteType）

**识别关键词**：`推导规则`、`互推导`、`满足推导`、`推导之后的...一致`

**适用场景**：两个参数的 dtype 不要求相同，只要 PromoteType 运算有效即可。典型场景：matmul 类算子的两个输入矩阵、addbmm 的 batch1 和 batch2。

**语义说明**：当 `01_parameter_description.md` 的 R{n} 约束描述为"满足数据类型推导规则"或"互推导关系"时，表示两个参数的 dtype 可以不同，只要 `PromoteType(A, B)` 产生有效结果。这与"可转换"（Cast）不同——推导是两个 dtype 作为输入产生结果 dtype，转换是一个 dtype 变为另一个 dtype。详见 parameter-cleaning-guide.md §2.4。

**强制规则**：约束语义为推导时，必须使用工具函数过滤候选值，返回 `Candidates(valid)`。
禁止使用 `return source` / `Candidates([source])` / `d == source` 等直接使用锚点值的写法。

**例外**：当 YAML 中 source 和 target 的 dtype 域仅含 1 个相同 dtype 时，单值返回正确。

**操作数类型与工具函数选择**：

| 涉及参数类型 | 工具函数 | 查找表 |
|------------|---------|--------|
| Tensor + Tensor | `infer_two_dtypes` | 互推导关系.md |
| Tensor + Scalar | `infer_tensor_scalar_dtypes` | TensorScalar互推导关系.md |

判定方法：检查 sources/target 参数在 02_test_factors.yaml 中的 type 字段，若为 aclScalar 则使用 TS 工具函数。

**工具函数**：
- `infer_two_dtypes(dtype1, dtype2)` → 返回 TT 推导结果 dtype，`None` 表示不可推导
- `infer_tensor_scalar_dtypes(scalar_dtype, tensor_dtype)` → 返回 TS 推导结果 dtype，`None` 表示不可推导
- `get_inferable_dtype_combinations([domain1, domain2])` → 返回所有 TT 合法推导组合
- `get_inferable_tensor_scalar_combinations(scalar_dtypes, tensor_dtypes)` → 返回所有 TS 合法推导组合

**示例 1：互推导（两个参数间）**

```python
# batch2.dtype 从 batch1.dtype 推导（允许不同 dtype）
@solves('batch2.dtype', sources=['batch1.dtype'])
def solve_batch2_dtype(batch1_dtype):
    from utils import infer_two_dtypes
    TENSOR_DTYPE_DOMAIN = ['bfloat16', 'float16', 'float32']  # ← 替换为 YAML 中 batch2.dtype 的实际域
    valid = [d for d in TENSOR_DTYPE_DOMAIN
             if infer_two_dtypes(batch1_dtype, d) is not None]
    return Candidates(valid)
```

**示例 2：推导后转换（推导+转换复合）**

```python
# 追溯表:
# R{n} (self.dtype可转换为推导结果) → @solves(solve_self_dtype)  [模式1.5+模式2复合]
#   涉及: batch1.dtype, batch2.dtype → self.dtype
#   方向: self.dtype → promote_result  (self可转换为推导结果)

# self.dtype 需可转换为 PromoteType(batch1, batch2) 的结果
# 约束语义：self → promote_result，self 是 source，promote_result 是 target
# 使用 get_convertible_source_dtypes(target, domain)：已知 target=promote_result，求哪些 source 能转为它
@solves('self.dtype', sources=['batch1.dtype', 'batch2.dtype'])
def solve_self_dtype(batch1_dtype, batch2_dtype):
    from utils import infer_two_dtypes, get_convertible_source_dtypes
    promote_result = infer_two_dtypes(batch1_dtype, batch2_dtype)
    if promote_result is None:
        return Candidates([])
    TENSOR_DTYPE_DOMAIN = ['bfloat16', 'float16', 'float32']
    return Candidates(get_convertible_source_dtypes(promote_result, TENSOR_DTYPE_DOMAIN))
```

**示例 2b：推导后转换（反向——推导结果可转换为输出）**

```python
# 追溯表:
# R{n} (out.dtype可转换约束) → @solves(solve_out_dtype)  [模式1.5+模式2复合]
#   涉及: tensors.dtype_list → out.dtype
#   方向: promote_result → out.dtype  (推导结果可转换为输出)
#   证据: 错误码"推导出的数据类型无法转换为指定输出out的类型"

# out.dtype 需是推导结果可转换到的目标类型
# 约束语义：promote_result → out，promote_result 是 source，out 是 target
# 使用 get_convertible_target_dtypes(source, domain)：已知 source=promote_result，求它能转到哪些 target
@solves('out.dtype', sources=['tensors.dtype_list'])
def solve_out_dtype(dtype_list):
    if not dtype_list:
        return NOT_APPLICABLE
    from utils import infer_dtypes, get_convertible_target_dtypes
    promote_result = infer_dtypes(dtype_list)
    if promote_result is None:
        if len(set(dtype_list)) == 1:
            promote_result = dtype_list[0]
        else:
            return Candidates([])
    return Candidates(get_convertible_target_dtypes(promote_result, OUT_DTYPE_DOMAIN))
```

> **⚠️ 计算类型 vs 约束类型**：当算子文档同时包含以下两类规则时，必须明确区分它们的使用场景：
>
> | 规则类型 | 含义 | 使用场景 |
> |---------|------|---------|
> | **计算精度规则** | 如"整数输入转 FLOAT 计算"——影响运行时行为 | 仅用于解释算子行为，不改变约束语义 |
> | **约束类型规则** | 如"out 必须是推导后可转换的类型"——用于约束求解 | 用于 `@solves` 和 `validate_constraints` 的类型过滤 |
>
> **关键原则**：`can_convert_dtype` 和 `infer_*` 工具函数应使用**原始推导类型**（`infer_two_dtypes` / `infer_tensor_scalar_dtypes` 的直接返回值），而非经过计算精度规则转换后的"有效类型"。
>
> **错误示例**（DivMods 算子教训）：
> ```python
> # 950PR 产品规则："整数推导结果转FLOAT计算"
> # 错误做法：将 can_convert_dtype 的输入从 raw_inferred 替换为 effective_type
> effective = 'float32'  # 因为 int8 推导 → 整数 → 转FLOAT
> can_convert_dtype(effective, 'uint8')  # False → 错误地排除了 uint8
>
> # 正确做法：使用原始推导类型
> raw_inferred = 'int8'  # infer_tensor_scalar_dtypes 的直接返回值
> can_convert_dtype(raw_inferred, 'uint8')  # True → 正确保留了 uint8
> ```
>
> 根本原因：计算精度规则描述的是运行时的隐式类型提升（implementation detail），而 `can_convert_dtype` 描述的是数据类型的静态转换关系（interface contract）。两者属于不同层面，不应混淆。

**示例 3：Tensor-Scalar 推导**

```python
# addr: betaOptional(aclScalar) + self(aclTensor) 推导
# betaOptional.dtype 从 self.dtype 按 TensorScalar 规则推导
@solves('betaOptional.dtype', sources=['self.dtype'])
def solve_beta_dtype(self_dtype):
    from utils import infer_tensor_scalar_dtypes
    SCALAR_DTYPE_DOMAIN = ['float32', 'float16', 'bfloat16']
    valid = [d for d in SCALAR_DTYPE_DOMAIN
             if infer_tensor_scalar_dtypes(d, self_dtype) is not None]
    return Candidates(valid)
```

> 对涉及 aclScalar 的推导必须使用 `infer_tensor_scalar_dtypes` 而非 `infer_two_dtypes`，TS 查找表与 TT 有 13 处结果差异（如 f16 Scalar + int8 Tensor → TT 得 f16，TS 应得 f32）。
>
> **与模式 1/模式 2 的区别**：
> - 模式 1（等值）：`return source` — 参数间 dtype 必须相同
> - 模式 1.5（推导）：`Candidates(inferable_list)` — 参数间 dtype 可以不同，只要 PromoteType 有效
> - 模式 2（可转换）：`Candidates(convertible_list)` — 一个 dtype 可以 Cast 到另一个

#### 模式2：类型可转换

**识别关键词**：`可转换`、`兼容`、`满足转换关系`

**强制规则**：约束语义为转换时，必须使用工具函数过滤候选值，返回 `Candidates(valid)`。
禁止使用 `return source` / `Candidates([source])` / `d == source`。

**工具函数选择**：根据涉及参数的"类型"列选择：

| 涉及参数类型 | 工具函数 | 转换规则 |
|------------|---------|---------|
| Tensor + Tensor | `can_convert_dtype` / `get_convertible_source_dtypes` / `get_convertible_target_dtypes` | 互转换关系.md，15 种类型，有方向限制 |
| Tensor + Scalar | `can_convert_to_tensor` / `get_convert_to_tensor_source_dtypes` | ConvertToTensor.md 接口7，23 种类型，全连接矩阵 |

```python
# 追溯表:
# R{n} (self.dtype可转换为out.dtype) → @solves(solve_self_dtype)  [模式2:类型可转换]
#   涉及: out.dtype → self.dtype
#   方向: self.dtype → out.dtype  (self可转换为out)

@solves('self.dtype', sources=['out.dtype'])
def solve_self_dtype(out_dtype):
    from utils import get_convertible_source_dtypes
    return Candidates(get_convertible_source_dtypes(out_dtype, DTYPE_DOMAIN))
```

> **⚠️ 方向性规则**：上例是"从 output.dtype **反向**推导 input.dtype"——已知目标 dtype，求能转换到它的源 dtype。
> 若需求是"从 input.dtype **正向**推导 output.dtype"——已知源 dtype，求它能转换到的目标 dtype——根据 `01_parameter_description.md` R{n} 的约束语义选择工具函数：
>
> | R{n} 约束语义 | 正向推导（已知 source，求 target） | 反向推导（已知 target，求 source） | 典型算子 |
> |--------------|-----------------------------------|-----------------------------------|---------|
> | "可转换"/"兼容"/"满足转换关系" | `get_convertible_target_dtypes(source, domain)` | `get_convertible_source_dtypes(target, domain)` | add、matmul、reduce |
> | "任意类型间可转换"/"显式类型转换"/文档未约束 dtype 转换 | 直接从目标域列表推导（不过滤） | 直接从源域列表推导（不过滤） | cast |
> | ConvertToTensor 接口7（链接指向 ConvertToTensor.md） | `can_convert_to_tensor(source, d)` + 列表推导 | `get_convert_to_tensor_source_dtypes(target, domain)` | aclnnConstantPadNd |
>
> **方向选择原则**：约束文本中"A 可转换为 B"中，A 是 source、B 是 target。在 @solves 函数中，promote_result 或锚点因子是已知值（source 或 target 由约束语义决定），遍历候选值是另一个角色。使用命名化的 wrapper 函数（函数名含 `source` 或 `target`）可直接从函数名确定方向，避免 `can_convert_dtype(A, B)` 参数顺序混淆。
>
> 文档未约束 dtype 转换时，target 域不受限制。
>
> 正向推导示例（R{n}="可转换"）：
>
> ```python
> # 追溯表:
> # R{n} (out.dtype可转换约束) → @solves(solve_out_dtype)  [模式2:类型可转换]
> #   涉及: self.dtype → out.dtype
> #   方向: self.dtype → out.dtype  (self可转换为out)
>
> @solves('out.dtype', sources=['self.dtype'])
> def solve_out_dtype(self_dtype):
>     from utils import get_convertible_target_dtypes
>     return Candidates(get_convertible_target_dtypes(self_dtype, DTYPE_DOMAIN))
> ```
>
> **常见错误**：对正向推导场景误用 `get_convertible_source_dtypes`，其返回"能转为首个参数的类型"（反向），
> 导致 out.dtype 为非法转换目标。判断方法（多数场景适用）：target 是推导结果（如 output）→ 用正向（`get_convertible_target_dtypes`）；target 是输入参数 → 用反向（`get_convertible_source_dtypes`）。注意 input→input 场景需根据约束语义判断方向。
>
> 方向选择的一般规则（锚点优先级）见 §2。

**ConvertToTensor 接口7 转换示例**（链接指向 ConvertToTensor.md 时）：

```python
# R{n} 链接指向 ConvertToTensor.md → 使用 can_convert_to_tensor 系列
# 追溯表标记：[模式2:类型可转换(ConvertToTensor)]
#   方向: value.dtype → self.dtype  (value可转换为tensor)

@solves('value.dtype', sources=['self.dtype'])
def solve_value_dtype(self_dtype):
    from utils import get_convert_to_tensor_source_dtypes
    valid = get_convert_to_tensor_source_dtypes(self_dtype, VALUE_DTYPE_DOMAIN)
    assert len(valid) >= 1, f"no convertible dtypes for self.dtype={self_dtype}"
    return Candidates(valid)
```

验证函数示例：

```python
def _validate_r2(case):
    """R2: value 可转换为 self 的数据类型"""
    violations = []
    self_dtype = case.get('self.dtype')
    value_dtype = case.get('value.dtype')
    if self_dtype is not None and value_dtype is not None:
        # 方向: can_convert_to_tensor(value, self) — value → self
        from utils import can_convert_to_tensor
        if not can_convert_to_tensor(value_dtype, self_dtype):
            violations.append('R2')
    return violations
```

### 4.2 Shape约束

#### 模式3：Shape公式计算

**识别关键词**：`shape 计算规则`、`shape为`、`shape等于`

```python
@solves('out.shape', sources=['self.shape', 'dim.value', 'keepDim.value'])
def solve_out_shape(self_shape, dim_value, keepDim_value):
    ndim = len(self_shape)
    if not dim_value:
        return [1] * ndim if keepDim_value else []
    norm_dims = set(d + ndim if d < 0 else d for d in dim_value)
    if keepDim_value:
        return [1 if i in norm_dims else s for i, s in enumerate(self_shape)]
    return [s for i, s in enumerate(self_shape) if i not in norm_dims]
```

**要点**：将文字描述的 shape 计算规则直接编码为 Python 逻辑。注意处理边界情况（空 dim、负索引、keepDim 分支）。可使用 `solver.shapes` 中的工具函数简化实现。

#### 模式4：广播关系

**识别关键词**：`广播`、`broadcast`

广播兼容性约束（生成多候选 shape）：

```python
@solves('other.shape', sources=['self.shape'])
def solve_other_shape(self_shape):
    from solver.shapes import broadcast_shapes
    return Candidates(broadcast_shapes(self_shape))
```

广播结果计算：

```python
@solves('out.shape', sources=['self.shape', 'other.shape'])
def solve_out_shape(self_shape, other_shape):
    from utils import get_broadcast_result
    result = get_broadcast_result([self_shape, other_shape])
    if result is None:
        raise ValueError(f"不可广播: {self_shape}, {other_shape}")
    return result
```

**强制规则**：使用 `broadcast_shapes()` 计算广播结果，禁止取 `shape_list[0]` 作为广播结果。

#### 模式5：维度匹配

**识别关键词**：`必须等于`、`匹配`、`相同且`

```python
@solves('batch2.shape', sources=['batch1.shape'])
def solve_batch2_shape(batch1_shape):
    import random
    k = batch1_shape[2]  # batch1[2] == batch2[1]
    b = batch1_shape[0]
    n = random.randint(1, 100)
    return [b, k, n]
```

### 4.3 Array约束

#### 模式6：Array值约束（取值范围 + 唯一性）

**识别关键词**：`取值范围`、`不允许重复`、`不重复`、`唯一`

```python
@solves('dim.value', sources=['self.dimensions', 'dim.length'])
def solve_dim_value(self_dimensions, dim_length):
    if dim_length == 0:
        return []
    actual = min(dim_length, self_dimensions)
    import random
    positive = sorted(random.sample(range(0, self_dimensions), actual))
    result = []
    for v in positive:
        if v > 0 and random.random() < 0.5:
            result.append(v - self_dimensions)
        else:
            result.append(v)
    return result
```

**要点**：注意负索引等价（`-i` 等价于 `ndim - i`）；唯一性需考虑归一化后的唯一值数量；长度上界 = 有效唯一值数。

#### 模式9：长度耦合

**识别关键词**：`长度一致`、`长度相同`、`个数相同`

```python
@solves('starts.length', sources=['axes.length'])
def solve_starts_length(axes_length):
    return axes_length

@solves('ends.length', sources=['axes.length'])
def solve_ends_length(axes_length):
    return axes_length

@solves('steps.length', sources=['axes.length'])
def solve_steps_length(axes_length):
    return axes_length
```

#### 模式10：长度上界推导

**识别关键词**：`（推断自：`、`长度上界`、`≤`

```python
@solves('dim.length_ranges', sources=['self.dimensions'])
def solve_dim_length_ranges(self_dimensions):
    return [[0, self_dimensions]]
```

### 4.4 条件约束

#### 模式7：存在性依赖

**识别关键词**：`可选`、`不存在时`、`忽略`、`控制是否输出`、`为True时有意义`、`为True时必须`、`为空时无效`、`仅当...时生效`

**情况 A**：可选参数的 dtype 推导

```python
@solves('bias.dtype', sources=['bias.exist', 'self.dtype'])
def solve_bias_dtype(bias_exist, self_dtype):
    if not bias_exist:
        return NOT_APPLICABLE
    return self_dtype  # 存在时由等值约束推导；若无其他约束且需 pairwise 覆盖则用 Candidates()
```

**注意**：可选参数存在时，其因子值通常由其他约束确定（如类型等值、shape 等值）。若该因子无其他约束驱动且需参与 L1 pairwise 覆盖，应返回 `Candidates()` 枚举所有合法值，而非 `SKIP`（`SKIP` 在 pairwise 域计算中被映射为空值，会导致因子被排除出组合覆盖）。

**情况 B**：可选参数的 shape 推导（aclTensor 类型可选参数）

```python
@solves('bias.shape', sources=['bias.exist', 'self.shape'])
def solve_bias_shape(bias_exist, self_shape):
    if not bias_exist:
        return NOT_APPLICABLE
    return list(self_shape)
```

**情况 C**：依赖可选参数的其他因子

```python
@solves('out.shape', sources=['self.shape', 'bias.exist', 'bias.shape'])
def solve_out_shape(self_shape, bias_exist, bias_shape):
    if not bias_exist:
        return list(self_shape)
    return _get_broadcast_result([self_shape, bias_shape])
```

**情况 D**：可选 Scalar 参数（如 addr 的 betaOptional/alphaOptional）

```python
@solves('betaOptional.dtype', sources=['betaOptional.exist', 'self.dtype'])
def solve_beta_dtype(betaOptional_exist, self_dtype):
    if not betaOptional_exist:
        return NOT_APPLICABLE
    if _is_float_dtype(self_dtype):
        return Candidates(['float', 'float16', 'double', 'bfloat16'])
    elif self_dtype == 'bool':
        return 'bool'
    else:
        return Candidates(['int32', 'int64'])
```

**可选参数处理要点**：
1. 可选参数的每个 `@solves` 函数**必须**以 `if not exist: return NOT_APPLICABLE` 开头
2. 依赖可选参数的下游因子也必须处理 `exist=False` 的情况
3. `NOT_APPLICABLE` 表示引擎跳过该因子，不参与组合
4. 预留参数（必须为 nullptr）只需 exist=[false]，所有 @solves 返回 NOT_APPLICABLE

**情况 E**：exist 由另一个参数的值/状态推导（条件化属性传递）

当文档描述中参数 P 的存在性（null vs non-null）由另一个参数 Q 的值或状态决定时，P 的 exist 因子不在 YAML 中静态定义，而是通过 @solves 从 Q 推导。此原则也适用于 shape、dtype、value 等其他属性的传递。

**控制源类型与实现模板**：

**E1：BoolArray 元素控制**

适用算子：LayerNormBackward、GroupNormBackward、BatchNormBackward 等

```python
# outputMask.value = [bool, bool, bool]
@solves('gradInputOut.exist', sources=['outputMask.value'])
def solve_gradInputOut_exist(outputMask_value):
    if not outputMask_value or len(outputMask_value) < 1:
        return False
    return outputMask_value[0]
```

**E2：bool 标量控制**

适用算子：UniqueConsecutive、Unique、CrossEntropyLoss

```python
# returnInverse.value = True / False
@solves('inverseOut.exist', sources=['returnInverse.value'])
def solve_inverseOut_exist(returnInverse_value):
    return returnInverse_value
```

**E3：另一个参数的 null 状态控制**

适用算子：AddRmsNormQuantV2、AddRmsNormDynamicQuantV2

```python
# scales2Optional.exist = True / False
@solves('y2.exist', sources=['scales2Optional.exist'])
def solve_y2_exist(scales2_exist):
    return scales2_exist
```

**E4：enum 值控制**

适用算子：FusedMatmul

```python
# fusedOpType.value = 'add' / 'mul' / 'gelu_erf' / ...
@solves('x3.exist', sources=['fusedOpType.value'])
def solve_x3_exist(fusedOpType_value):
    return fusedOpType_value in ['add', 'mul']
```

> **两点扩展**：(1) 控制源 Q 也可以是合成场景因子 `_scenario.value`（不必是真实参数）；(2) 被控对象可以是**选择器参数自身**——即该参数的 `.value` 随 Q 分叉取值、且某些 Q 取值下必须非空。这种情况见下文"反模式：选择器参数 .exist 解耦"。

**E5：bool 标量控制（可选参数）**

适用算子：ApplyAdamW、RmsNormDynamicMxQuant

```python
# amsgrad.value = True / False
# maxGradNormOptional 仅在 amsgrad=True 时需要
@solves('maxGradNormOptional.exist', sources=['amsgrad.value'])
def solve_maxGradNormOptional_exist(amsgrad_value):
    return amsgrad_value
```

**识别信号速查表**（适用于 E1~E5，同时用于 [parameter-cleaning-guide.md](parameter-cleaning-guide.md) §2.6 模式#7 和 §2.7 可选参数识别的信号识别）：

| 文档措辞 | 错误码措辞 | 控制源类型 | 实现 |
|---------|-----------|-----------|------|
| "由XX[N]控制是否输出" | "XX[N]为True且P为空指针" | BoolArray 元素 | E1 |
| "当XX为True时有意义" / "当XX为True时有效" | — | bool 标量 | E2 |
| "当XX为空时无效/不处理" | — | null 状态 | E3 |
| "仅当XX为某值时需要" | "XX为某值时P为空指针" | enum 值 | E4 |
| "当XX为True时必须非空" | "XX为True且P为空指针" | bool 标量 | E5 |

**关键约束**：
1. YAML 中**不定义**被控参数的 exist 因子，由 @solves 独占推导
2. 被控参数的其他因子（dtype、shape 等）仍需正常定义，约束函数中必须以 `if not exist: return NOT_APPLICABLE` 开头
3. 控制参数自身的 exist 始终正常定义（它本身不是被控的）
4. 当控制源是 BoolArray 的 .value 因子时，需通过索引取对应元素
5. **耦合规则（选择器参数）**：若 `@solves('X.value')` 的 sources 同时含 `X.exist` 与外部控制因子 Q（含合成 `_scenario.value`）且按 Q 分叉取值，则**必须**配套 `@solves('X.exist', sources⊇[Q])`，且 `X.exist` 不得作为 YAML 自由锚点 `[true,false]`。否则 `exist=False` 时 `.value` 被 SKIP 退化为 null，与"该场景必须取特定值"矛盾。

**反模式：选择器参数 .exist 解耦**

当 char*/enum 选择器参数（如 `cacheModeOptional`/`scatterModeOptional`/`reduceModeOptional`，或 enum 型 `aclScalar*`）的 `.value` 随场景因子（`_scenario.value` 或某 enum 参数）分叉取值时，常见错误是只 `@solves('.value')` 而把 `.exist` 留在 YAML 作 `[true,false]` 自由锚点。`exist=False` 时 `.value` 被 SKIP 退化为 null（常 ≡ 某默认值），与"该场景必须取非默认值"冲突，生成自相矛盾的组合。注：`string`/`bool` 参数框架不注册 builtin（无脚手架提醒），尤需人工套用本规则。

❌ 反模式（`scatter_pa_kv_cache` 实例，致 586 条正向用例被算子拒绝）：

```python
# 02_test_factors.yaml
# scatterModeOptional:
#   factors:
#     scatterModeOptional.exist: [true, false]   # ← 错：自由锚点
#     scatterModeOptional.value: ['None','Nct','Alibi','Rope','Omni']

# 04_constraints.py —— 只 solve .value，漏 solve .exist
@solves('scatterModeOptional.value', sources=['scatterModeOptional.exist', '_scenario.value'])
def solve_scatter_mode_value(exist, scenario):
    if not exist:
        return SKIP                               # → null(≡None)
    ...                                            # scenario=3 本应给 'Alibi'，但 exist=False 时拿不到
# 后果：组合 (scenario=3, exist=False) → scatterMode 缺省 None，但 cache 形态/key 维度
#       仍按 scenario=3 生成 → 算子按 None 路由到 NORMAL 模板，shape 校验失败
```

✅ 正确：

```python
# 02_test_factors.yaml —— 不定义 scatterModeOptional.exist
# scatterModeOptional:
#   factors:
#     scatterModeOptional.value: ['None','Nct','Alibi','Rope','Omni']

@solves('scatterModeOptional.exist', sources=['_scenario.value'])
def solve_scatter_mode_exist(scenario):
    return scenario in (3, 4)                     # 场景四/五必须显式给出

@solves('scatterModeOptional.value', sources=['scatterModeOptional.exist', '_scenario.value'])
def solve_scatter_mode_value(exist, scenario):
    if not exist:
        return SKIP
    ...                                            # 按 scenario 返回具体值
```

**自检**：若某 `@solves('X.value')` 的 sources 同时含 `X.exist` 与外部控制因子 Q，且函数体按 Q 分叉（含 `tag()` 或条件分支），则必须存在 `@solves('X.exist', sources⊇[Q])`。

#### 模式8：条件化约束

**识别关键词**：`当...时`、`若...则`、`否则`、`条件`、`仅...时支持`、`特定...下限制`、`产品特定...限制`

**子类型 A：条件值选择**

根据条件选择不同的输出值：

```python
@solves('out.shape', sources=['shape_param.value', 'perm.value', 'transposeFirst.value'])
def solve_out_shape(shape_param, perm, transpose_first):
    from solver.shapes import transpose_shape
    if transpose_first:
        return transpose_shape(list(shape_param), perm)
    else:
        return list(shape_param)
```

**子类型 B：条件化候选过滤**

**适用场景**：约束 R{n} 描述的是"当因子 A 满足条件时，因子 B 的候选值域受限"，但因子 B 已有其他约束驱动的 @solves 函数。此时**不新建独立 @solves**，而是在已有函数中：
1. 将条件因子加入 sources（引擎自动调整拓扑排序）
2. 在候选集计算后，根据条件过滤不合法的候选值

**扩展适用**：产品特定限制（"仅XX场景支持YY类型"）也属于此模式——条件因子为场景变量或枚举参数，被约束因子为 dtype 等离散因子的合法值域。

**方案选择**：

| 方案 | 做法 | 适用场景 |
|------|------|---------|
| A. 扩展 sources | 将条件因子加入已有 @solves 函数的 sources 列表，在函数内添加条件过滤分支 | B 已有 @solves，且条件过滤逻辑简单 |
| B. 独立函数 | 新建 @solves 函数，target 为需要过滤的因子，sources 包含条件因子 | B 无已有 @solves，或条件过滤需要改变返回值类型 |

**方案 A 示例**：

```python
# 追溯表:
# R3 (INT4尾轴偶数约束) → @solves(solve_dtype_value)  [条件过滤]
#   被约束参数: dtype.value
#   条件因子: self.shape
#   条件分支: self.shape[-1]为奇数时排除int4

# 修改前: sources=['self.dtype']
# 修改后: sources=['self.dtype', 'self.shape']
@solves('dtype.value', sources=['self.dtype', 'self.shape'])
def solve_dtype_value(self_dtype, self_shape):
    allowed = _get_allowed_out_dtypes(self_dtype)

    if self_shape and self_shape[-1] % 2 != 0:
        allowed = [d for d in allowed if d != 'int4']

    assert len(allowed) > 0, f"no allowed out dtypes for self.dtype={self_dtype}, shape={self_shape}"
    return Candidates(allowed)
```

**判断何时使用子类型 B（方案 A）**：

1. 约束涉及两个因子 A 和 B
2. B 已有 @solves 函数（被其他约束驱动）
3. 约束语义是"当 A 满足条件时，B 不能取某些值"（而非"A 的值决定 B 的值"）
4. 满足以上条件 → 使用条件过滤，将 A 加入 B 的 sources

**要点**：
1. 追溯表中标注 `[条件过滤]`，格式见 §5.1
2. 过滤后必须 `assert len(allowed) > 0`，防止候选集被完全清空
3. 条件化候选过滤**不得**标注为 `factor-domain`（见检查清单 #19）
4. 不得嵌入 sources 不含条件因子的函数（函数内无法获取条件值）
5. 不得使用等值返回（`return source`）替代条件过滤，否则导致域坍缩

### 4.5 高级模式

#### 模式11：多场景 + 共享维度变量

**识别关键词**：`支持以下场景`、`场景一/二/三`、`prefill`、`decode`、`batch`、`dim 范围`

```yaml
# 02_test_factors.yaml
intermediate:
  _batch:
    type: int64_t
    factors:
      _batch.value_range: [[1, 8092]]
  _dim:
    type: int64_t
    factors:
      _dim.value_range: [[128, 16384]]
  _scenario:
    type: int64_t
    factors:
      _scenario.value: [0, 1, 2]
```

```python
@solves('x.shape', sources=['_batch.value', '_dim.value', 'runMode.value', '_scenario.value'])
def solve_x_shape(batch, dim, runMode, scenario):
    if runMode == 0:
        cu_seq_len = random.randint(batch, 65536)
        return [cu_seq_len, dim]
    elif scenario == 1:
        return [batch, random.randint(1, 6), dim]
    else:
        cu_seq_len = random.randint(batch, batch * 6)
        return [cu_seq_len, dim]
```

**要点**：当参数无法完全区分子场景时，引入 `_scenario` 中间因子；共享维度变量作为中间因子由多个 `@solves` 共同引用。

#### 模式12：值级跨参数耦合

**识别关键词**：`每个元素取值不超过`、`当前 batch 的`

```python
@solves('numAcceptedTokens.value', sources=['numAcceptedTokens.exist', 'queryStartLoc.value'])
def solve_numAcceptedTokens_value(exist, queryStartLoc_value):
    if not exist:
        return NOT_APPLICABLE
    batch = len(queryStartLoc_value) - 1
    token_counts = [queryStartLoc_value[i+1] - queryStartLoc_value[i] for i in range(batch)]
    return [random.randint(1, tc) for tc in token_counts]
```

**要点**：sources 引用提供数据的参数的 `.value` 因子；拓扑排序保证源值先于目标值求解；函数从源值中提取所需信息。

#### 模式13：查找表映射

**适用场景**：约束关系章节包含参数间映射表（如 dtype 转换路径、格式支持矩阵），
Target 值由 Source 值通过查找表确定。适用于任何属性域（dtype/format/shape 等）。

**实现模板**：

```python
# 来源: 01_parameter_description.md 约束关系 R{n}

# 步骤1：逐行抄写原始映射表。每行的 source 和 target 均为列表。
# 文档中的 "/" 分隔值直接转为列表元素，禁止手工展开。
_RAW_LOOKUP_ROWS = [
    (['source_a'], ['target_1', 'target_2']),       # 行1: source_a | target_1/target_2
    (['source_b', 'source_c'], ['target_3']),        # 行2: source_b/source_c | target_3
    # ... 每行与原始表格一一对应
]

# 步骤2：使用标准工具函数自动展开笛卡尔积并校验
from solver.lookup import expand_lookup
_LOOKUP = expand_lookup(
    _RAW_LOOKUP_ROWS,
    expected_row_count=2,    # 原始映射表的行数，用于检测抄写遗漏
    source_domain={'source_a', 'source_b', 'source_c'},
    target_domain={'target_1', 'target_2', 'target_3'},
)
_FULL_DOMAIN = [...]  # Target 的完整合法域

# 步骤3：使用展开后的查找表
@solves('target_param.attr', sources=['source_param.attr'])
def solve_target_from_lookup(source_value):
    allowed = _LOOKUP.get(source_value, _FULL_DOMAIN)
    assert len(allowed) > 0, f"no allowed values for {source_value}"
    return Candidates(allowed)
```

**要点**：
1. 步骤1 中每行直接从原始映射表抄写，`/` 分隔的值转为列表元素，**禁止手工展开多值单元格**
2. 步骤2 中 `expand_lookup()` 自动完成笛卡尔积展开，并校验行数和域值合法性（模块加载时自动执行）
3. 不在映射表中的源值使用 `_FULL_DOMAIN` 作为 fallback
4. 使用 `Candidates()` 返回多候选值，引擎为每个候选值生成独立用例

**format → dimensions 特例**：当查找表的 target 是 `{name}.dimensions`、source 是 `{name}.format` 时，无需使用 `expand_lookup()`，直接参照 [format-constraints.md](format-constraints.md) §4.1 的简化写法。

#### 模式14：离散因子枚举（Candidates 展开）

**识别关键词**：因子值为有限离散集合、因子间存在推导关系、需覆盖多种组合

**适用条件**：
1. target 值为离散值域（如 dtype 枚举）的列表
2. 列表元素之间存在推导约束（如 `infer_dtypes(list)` 必须合法）
3. 列表长度由连续值域（如 `length_ranges`）控制——引擎随机采样具体长度，对每个长度值调用约束函数

**实现模板**：

```python
@solves('param.dtype_list', sources=['param.dtype', 'param.length', '_scenario.value'])
def solve_dtype_list(anchor_dtype, length, scenario):
    if scenario == 0 or length <= 1:
        return [anchor_dtype] * length
    if scenario == 1:
        return Candidates(_enumerate_valid_dtype_lists(anchor_dtype, length))
    return [anchor_dtype] * length


def _enumerate_valid_dtype_lists(anchor, length):
    result = []
    for d in DTYPE_DOMAIN:
        if d != anchor and infer_two_dtypes(anchor, d) is not None:
            result.append([anchor] + [d] + [anchor] * (length - 2))
    return result if result else [[anchor] * length]
```

**要点**：
1. 每个tensor独立生成shape（禁止 `[list(shape)] * N` 复制传播）
2. `length_ranges` 是连续值域，引擎随机采样具体 length 后传入约束函数；dtype 是离散值域，对每个 length 枚举有效组合
3. 枚举策略：前两个元素构成有效推导对，其余元素统一用 anchor dtype，确保每个有效 `(anchor, d)` 有序对均被覆盖

**判定依据**：对 TensorList 内部 dtype 约束应用 §0.1 单值测试法——固定 anchor dtype 后，列表内部的 dtype 分配有 ≥2 种合法输出（同 dtype / 不同但可推导 dtype），满足 Candidates 枚举标准。因此该约束**不能**归类为 `factor-domain`（单值覆盖），而**必须**使用 `@solves` 生成多候选值。

**追溯表标记规范**：对于 TensorList 内部 dtype 约束，追溯表应标记为：

```
# R{n} (tensors内部dtype互推导) → solve_tensors_dtype_list
#   [TensorList内部互推导约束，需枚举合法dtype组合，返回Candidates]
```

**禁止标记为** `factor-domain`，理由"同一 dtype 自动满足互推导"虽然逻辑为真，但仅覆盖约束空间的一个真子集。

**`_scenario.value` 的适用场景**：仅当列表内部 dtype 推导存在多种合法分布策略时（如部分元素用 dtype A、部分用 dtype B，且需区分"S1: 全部同 dtype"和"S2: 混合 dtype"等子场景），才需要引入 `_scenario` 中间因子作为 source。对于大多数算子，`dtype_list` 的 solve 可直接基于 `tensors.dtype`（anchor）+ `tensors.length` 生成变体，无需 scenario 分支。

**下游 `out.dtype` 的 source 变更**：当 TensorList 参数存在 `dtype_list` 因子时，下游依赖 TensorList dtype 推导结果的 `@solves`（如 `solve_out_dtype`）应将 source 从 `tensors.dtype`（标量）改为 `tensors.dtype_list`（列表），函数体内使用 `infer_dtypes(dtype_list)` 计算列表整体的 promote 结果，再基于该结果过滤可转换的 dtype。`utils.py` 中的 `infer_dtypes(dtype_list: List[str])` 函数已支持列表输入。

**触发条件（重要）**：

当 `01_parameter_description.md` 中满足以下**全部条件**时，**必须**使用本模式为对应参数生成 `dtype_list` solve：

1. 参数类型为 `aclTensorList`
2. 该参数的"补充说明"列包含"列表内部...推导规则"或"互推导"措辞
3. `02_test_factors.yaml` 中该参数存在 `dtype_list` 因子（空列表占位）

#### 模式15：Array/Scalar 元素级值域约束

**识别信号**：01_parameter_description.md "取值范围"列含以下模式：
- `每个元素值 > X` / `每个元素值 ≥ X` / `每个元素值 < X`
- `元素取值范围为 [lo, hi]`

**适用条件**：
- 参数类型为 aclIntArray / aclFloatArray / aclScalar
- "取值范围"列含明确的不等式约束（非由其他参数决定的动态约束）
- 约束仅限制元素值本身，不涉及参数间关系

**实现方式**（二选一）：

| 方式 | 做法 | 适用场景 |
|------|------|---------|
| A. YAML value_range | 在 02_test_factors.yaml 中定义 `param.value_range_{dtype}` | 值域为有限区间且有明确上下界 |
| B. @solves + validate | 新增 R{n}，实现 @solves 和 _validate_r{n} | 值域为单侧开放约束（如 `> 0`），YAML value_range 不适合表达 |

**方式 B 的实现模板**：

```python
@solves('param.value', sources=['param.exist'])
def solve_param_value(exist):
    if not exist:
        return NOT_APPLICABLE
    return SKIP  # IMPL-ARRAY-VALUE 默认按 dtype 全量范围，由 validate 校验

def _validate_r{n}(case):
    violations = []
    val = case.get('param.value')
    if val is not None:
        for v in val:
            if v <= 0:  # 根据具体约束调整
                violations.append('R{n}_value_out_of_range')
                break
    return violations
```

> 以上模式为常见约束的实现参考，非穷举。遇到未匹配任何模式的约束时，基于 §1
> 通用规范自行实现：识别 target 和 sources，用 Python 表达约束逻辑，返回符合
> 返回值语义（单值 / Candidates / SKIP / NOT_APPLICABLE）的结果。

### 4.6 约束正确性校验函数（validate_constraints）

`04_constraints.py` **必须定义** `validate_constraints(case: dict) -> list[str]`（返回违规约束 ID 列表，空列表表示全部通过）。`generate_test_cases.py` 在用例生成后自动调用此函数校验每条 L0/L1 用例。

> **约束守恒原则**（不可违反）：
> 1. `validate_constraints` 是 `01_parameter_description.md` 中 R{n} 约束的**规范镜像**
> 2. **每个 R{n} 都必须在 `validate_constraints` 中有独立校验**——无论 `@solves` 是否已覆盖该约束
> 3. **修复唯一方向**：当校验失败时，修复 `@solves` 的实现，**永远不能削弱 `validate_constraints`** 的检查
> 4. `validate_constraints` 中的判定逻辑必须从 `01_parameter_description.md` R{n} 原始描述**独立转录**，不引用 `@solves` 函数（避免同源错误）
> 5. `--validate` 会自动执行 **[CONSTRAINT-CONSERVATION]** 检查，发现缺失时会阻断流程

**编写流程**：

1. 从 `01_parameter_description.md` 的 `## 约束关系` 章节提取所有 `### R{n}` 约束
2. **子约束拆分**：若 R{n} 包含多个可独立判定的子句（分号/句号分隔），拆分为 R{n}a、R{n}b…分别实现
3. 对每个 R{n}（或子约束），创建独立的 `_validate_r{n}(case)` 辅助函数：
   - 函数 docstring 中**必须**复制 R{n} 的原始约束描述
   - 判定逻辑从 `01_parameter_description.md` **原样转录**，不引用 `@solves` 辅助函数
4. `validate_constraints` 汇总所有辅助函数的违规项
5. **扫描场景描述中的隐式联合约束**：除编号 R{n} 外，检查场景描述的 shape 公式中是否包含 `sizeof(dtype)`、format 分块因子等隐式联合约束（如 `(X * sizeof(dtype)) % N == 0`）。这些约束可能未被编号为 R{n}，但需要在 validate_constraints 中添加跨因子一致性校验

**与 @solves 的关系**：

| 维度 | @solves | validate_constraints |
|------|---------|---------------------|
| 角色 | 正向约束（生成合法值） | 反向校验（检查用例是否合法） |
| 数据来源 | 引擎传递 sources 值 | 从 case dict 直接读取 |
| 错误检测 | assert 失败 → 丢弃组合 | 返回违规 ID → 丢弃用例 |
| 独立性 | 引擎求解阶段执行 | 用例生成后独立执行 |
| 同源错误 | @solves 自身 bug 无法自检 | 独立转录可捕获 @solves bug |

**函数签名和结构化模板**：

```python
def validate_constraints(case):
    violations = []
    violations.extend(_validate_r1(case))
    violations.extend(_validate_r2(case))
    # ... 每个 R{n} 一个调用，从 01_parameter_description.md 逐一转录
    return violations


def _validate_r1(case):
    """R1: {从01_parameter_description.md复制的原始约束描述}"""
    violations = []
    key_dtype = case.get('key.dtype')
    cache_dtype = case.get('keyCacheRef.dtype')
    if key_dtype is not None and cache_dtype is not None and key_dtype != cache_dtype:
        violations.append('R1_dtype_mismatch')
    return violations


def _validate_r2(case):
    """R2: {从01_parameter_description.md复制的原始约束描述}"""
    violations = []
    # 判定逻辑从 01_parameter_description.md R2 原始描述转录
    # 禁止调用 @solves 函数中的辅助函数
    return violations
```

> **关键规则**：
> 1. `_validate_r{n}` 函数的 docstring 必须包含 R{n} 的原始约束描述。这样做的目的是：
>    - 使约束丢失非常显眼（空 docstring 或缺失函数容易被 review 发现）
>    - 为 `--validate` 的 [CONSTRAINT-CONSERVATION] 检查提供审计线索
>    - 防止在修复校验失败时错误删除约束检查
> 2. **转换约束方向注释**：涉及 `can_convert_dtype` / `can_convert_to_tensor` 调用的 `_validate_r{n}`，必须在 `can_convert_dtype` 调用上方添加方向注释，与追溯表方向标注一致：
>
> ```python
> def _validate_r2(case):
>     """R2: promote_result 可转换为 out.dtype"""
>     violations = []
>     dtype_list = case.get('tensors.dtype_list')
>     out_dtype = case.get('out.dtype')
>     if not dtype_list or out_dtype is None:
>         return violations
>     from utils import infer_dtypes, can_convert_dtype
>     promote_result = infer_dtypes(dtype_list)
>     if promote_result is None:
>         if len(set(dtype_list)) == 1:
>             promote_result = dtype_list[0]
>         else:
>             return violations
>     if out_dtype == promote_result:
>         return violations
>     # 方向: can_convert_dtype(promote_result, out) — 推导结果→输出
>     if not can_convert_dtype(promote_result, out_dtype):
>         violations.append('R2_out_dtype_not_convertible')
>     return violations
> ```
>
> 方向注释格式：`# 方向: can_convert_dtype({source}, {target}) — {自然语言}`
> 参数名必须与追溯表方向标注行的 source/target 角色一一对应。

**常见模式速查表**：

| 约束类型 | validate_constraints 写法 |
|---------|--------------------------|
| dtype 等值 | `if a_dtype != b_dtype: violations.append(...)` |
| shape 匹配 | `if a_shape[:n] != b_shape[:n]: violations.append(...)` |
| 值域范围 | `if val < lo or val > hi: violations.append(...)` |
| 存在性依赖 | `if not exist_a and exist_b: violations.append(...)` |
| 枚举映射 | `if (mode, actual) not in allowed_pairs: violations.append(...)` |
| 推导后转换 | `# 方向: can_convert_dtype(inferred, out)\nif not can_convert_dtype(inferred, out): violations.append(...)` |
| 类型可转换 | `# 方向: can_convert_dtype(source, target)\nif not can_convert_dtype(source, target): violations.append(...)` |

---

## 5. 检查清单

| # | 检查项 | 方法 |
|---|--------|------|
| 1 | 每个 @solves 的 target 对应一个有约束关系的因子 | 对照补充说明列 |
| 2 | sources 因子层级正确 + 条件因子 ⊆ sources | 查看拓扑文件 + 对照文档约束 |
| 3 | 函数覆盖所有分支 | 若有"若...则...否则"，需有 if/else |
| 4 | 返回值类型正确 | 单值 vs Candidates vs SKIP vs NOT_APPLICABLE |
| 5 | 无遗漏约束 | 逐行扫描补充说明列 |
| 6 | 边界条件处理 | dim 为空、value 为 0、dimensions 为 1 |
| 7 | 需要中间因子时已定义 | 多参数共享 batch/dim 等语义变量 |
| 8 | 中间因子以 `_` 前缀开头 | 避免与算子参数冲突 |
| 9 | 值级耦合的 sources 引用 `.value` 因子 | 如 numAcceptedTokens.value 依赖 queryStartLoc.value |
| 10 | 场景枚举子场景有对应 tag() 调用 | 枚举表中每个子场景 ID 在 @solves 中有对应 |
| 11 | 函数 return 前 assert 核心不变量 | 参照 assert 模板速查表 |
| 12 | 中间因子域值模式符合决策树 | 对照 §3.3 决策树逐因子检查 |
| 13 | dtype 工具函数与操作数类型一致 | TT推导→`infer_two_dtypes`; TS推导→`infer_tensor_scalar_dtypes`; TT转换→`can_convert_dtype`系列; TS转换→`can_convert_to_tensor`系列 |
| 14 | 离散因子用 Candidates 枚举 | 禁止 `random.choice()`；连续值域由引擎采样 |
| 15 | R{n} 返回类型判定正确 | 单值测试法：1种→单值; ≥2种→Candidates |
| 16 | 查找表用 `expand_lookup()` 展开 | 禁止手动展开多值单元格 |
| 17 | 01 中每个 R{n} 在 04 追溯表中出现 | `--validate` 自动校验 |
| 18 | 追溯表函数名与 04 实际函数定义对应 | 差集检查 |
| 19 | 条件化约束不使用 factor-domain 策略 | 条件因子非"无"时禁止 factor-domain |
| 20 | validate_constraints 已定义且覆盖所有 R{n}，每个 `_validate_r{n}` 有 docstring | 对照 01_parameter_description.md 逐条检查，`--validate` [CONSTRAINT-CONSERVATION] 自动校验 |
| 21 | 转换约束（模式2/1.5+2）有方向标注，@solves 工具函数与方向一致 | 对照追溯表方向标注行，检查 `get_convertible_*_dtypes` 函数名与方向是否匹配 |

### 5.1 [条件过滤] 追溯表格式规范

使用 `[条件过滤]` 策略时，追溯表条目必须包含以下字段：

```python
# R{n} ({描述}) → @solves({宿主函数名})  [条件过滤]
#   被约束参数: {target因子}
#   条件因子: {因子1}, {因子2}, ...
#   条件分支: {判断逻辑摘要}
```

**示例**：

```python
# R14 (产品特定dtype限制) → @solves(solve_key_dtype)  [条件过滤]
#   被约束参数: key.dtype
#   条件因子: _scenario.value, scatterModeOptional.value
#   条件分支: scenario==0 或 (scenario==1 且 scatter_mode=='None') 时允许 float4，否则排除
```

**规则**：有条件因子的约束不得使用 `factor-domain` 策略（见检查清单 #19）。

### 5.2 转换约束方向标注规范

使用模式 1.5+2（推导后转换）或模式 2（类型可转换）时，追溯表条目**必须**包含方向标注行：

```python
# R{n} ({描述}) → @solves({函数名})  [模式1.5+模式2复合]
#   涉及: {source因子} → {target因子}
#   方向: {source角色} → {target角色}  ({自然语言说明})
```

**方向标注字段**：

| 字段 | 格式 | 说明 |
|------|------|------|
| source角色 | 具体参数名（如 `promote_result`, `self.dtype`, `out.dtype`） | `can_convert_dtype` 的第一个参数（source） |
| target角色 | 具体参数名 | `can_convert_dtype` 的第二个参数（target） |
| 自然语言说明 | 括号内的简短描述 | 用自然语言重述转换方向，与箭头互相验证 |
| 证据（可选但推荐） | 另起一行 `#   证据: {错误码/源码/语义推理}` | 方向消歧的证据来源 |

**示例**：

```python
# R2 (out.dtype可转换约束) → @solves(solve_out_dtype)  [模式1.5+模式2复合]
#   涉及: tensors.dtype_list → out.dtype
#   方向: promote_result → out.dtype  (推导结果可转换为输出)
#   证据: 错误码"推导出的数据类型无法转换为指定输出out的类型"
```

```python
# R3 (self.dtype可转换为推导结果) → @solves(solve_self_dtype)  [模式1.5+模式2复合]
#   涉及: batch1.dtype, batch2.dtype → self.dtype
#   方向: self.dtype → promote_result  (self可转换为推导结果)
```

**规则**：
1. source/target 角色必须是**具体参数名或推导结果变量名**，不能是抽象描述（如"输入"/"输出"）
2. 箭头方向与 `can_convert_dtype(source, target)` 的参数顺序**严格一致**
3. `@solves` 中使用的工具函数必须与方向标注一致：
   - 标注 `A → B`，A 是已知锚点 → 使用 `get_convertible_target_dtypes(A, domain)`（正向）
   - 标注 `A → B`，B 是已知锚点 → 使用 `get_convertible_source_dtypes(B, domain)`（反向）
4. `_validate_r{n}` 中 `can_convert_dtype` 的参数顺序必须与方向标注一致

**方向判定流程**（必须在写追溯表之前完成）：

1. 从 `01_parameter_description.md` R{n} 原文提取转换关系的两个角色
2. 按 [parameter-cleaning-guide.md §2.4.1 转换方向消歧规则](parameter-cleaning-guide.md)确定 source 和 target
3. 当文本存在主宾歧义时，**必须优先使用错误码措辞确认方向**
4. 将确定的方向写入追溯表的方向标注行

---

## 6. 约束关系对照表

| 约束类型 | 表达方式 | 工具函数 |
|----------|---------|---------|
| 等值（dtype 完全相同） | `return sources[0]` | 无需 |
| 类型推导（PromoteType） | `Candidates(inferable_list)` | `infer_two_dtypes` / `infer_tensor_scalar_dtypes` / `get_inferable_dtype_combinations` / `get_inferable_tensor_scalar_combinations` |
| 公式计算 | 直接 Python 计算 | 无需 |
| 类型可转换（反向：求 source） | `Candidates(兼容类型列表)` | 按模式2方向性规则中 R{n} 语义表选择 |
| 类型可转换（正向：求 target） | `Candidates(兼容类型列表)` | 按模式2方向性规则中 R{n} 语义表选择 |
| 广播 shape | `Candidates(广播兼容 shape 列表)` | `solver.shapes.broadcast_shapes()` |
| 维度匹配 | 生成 target shape 时嵌入匹配逻辑 | 自行实现 |
| 存在性依赖 | 条件返回 `NOT_APPLICABLE`/`SKIP` | 自行实现 |
| 条件化属性传递（exist 推导） | `@solves('{P}.exist', sources=['{Q}.{attr}'])` 从控制参数推导 | 按模式 7 情况 E1~E5 选择模板 |
| 条件化 | if/else 分支 | 无需 |
| 条件化候选过滤（[条件过滤]） | 扩展 sources + 过滤 Candidates | 按模式 8 子类型 B |
| 元素级值域约束 | YAML value_range 或 @solves + validate | 按模式 15 |
| 长度耦合 | 等值返回 source 长度 | 无需 |
| 长度上界 | 返回 `[[min, max]]` | 无需 |

---

## 附录 A：场景枚举完整示例（aclnnIndexPutImpl）

### A.1 约束关系清单

| ID | 约束描述 | 涉及参数 | 关键词 | 需枚举 | @solves target |
|----|---------|---------|--------|-------|---------------|
| C1 | values 数据类型必须与 selfRef 一致 | selfRef, values | 一致 | 否 | values.dtype |
| C2 | indices 中 Tensor 个数不能超过 selfRef 的维度 | indices, selfRef | 上界 | 否 | indices.length_ranges |
| C3 | indices 中的 Tensor 会广播成相同 shape | indices 内各 tensor | 广播 | **是** | indices.shape_list |
| C4 | values.ndim = indices[i].ndim + (selfRef.ndim - indices.size()) | indices, selfRef, values | 满足公式 | **是** | values.dimensions, values.shape |
| C5 | values 的前半维度与 indices 广播后 shape 相同 | indices, values | 广播后 | **是** | values.shape |

### A.2 子场景枚举

**C3: indices 中的 Tensor 会广播成相同 shape**

| 子场景 ID | 描述 | shape_list 示例 |
|----------|------|---------------|
| C3-S1 | 完全相同 shape | `[[2,3], [2,3], [2,3]]` |
| C3-S2 | 含 size=1 维度的可广播 shape | `[[1,3], [2,1], [2,3]]` |
| C3-S3 | ndim 不同的可广播 shape | `[[3], [2,3]]` |

**C4: values.ndim 公式**

| 子场景 ID | 描述 | 公式变量取值 | values.ndim |
|----------|------|------------|------------|
| C4-S1 | 全部维度被标量索引 | idx_ndim=0, N=selfRef.ndim | 0 |
| C4-S2 | 部分维度被多维索引 | idx_ndim=2, N=2, selfRef.ndim=5 | 5 |
| C4-S3 | 只索引第一个维度 | idx_ndim=0, N=1, selfRef.ndim=3 | 2 |

**C5: values 前半维度与 indices 广播后 shape 相同**

| 子场景 ID | 描述 | indices.shape_list | 广播结果 | values.shape[:idx_ndim] |
|----------|------|-------------------|---------|----------------------|
| C5-S1 | indices 全部相同 → 广播结果 = 某个 indices shape | `[[2,3], [2,3]]` | `[2,3]` | `[2,3]` |
| C5-S2 | indices 含广播 → 广播结果 ≠ 任一 indices shape | `[[1,3], [2,1]]` | `[2,3]` | `[2,3]` |

### A.3 对照枚举表的 @solves 实现

C3 的 @solves 需能生成 S1/S2/S3 三种子场景：

```python
@solves('indices.shape_list', sources=['selfRef.shape', 'indices.dimensions', 'indices.length'])
def solve_indices_shape_list(selfRef_shape, indices_dimensions, indices_length):
    if indices_length == 0:
        return []
    target_shape = [random.randint(1, 4) for _ in range(indices_dimensions)]
    shapes = []
    for i in range(indices_length):
        shape = list(target_shape)
        for j in range(len(shape)):
            if random.random() < 0.3:
                shape[j] = 1
        shapes.append(shape)
    return shapes
```

C5 的 @solves 需用广播结果（而非 `indices_shape_list[0]`）：

```python
@solves('values.shape', sources=['selfRef.shape', 'indices.shape_list', 'indices.length'])
def solve_values_shape(selfRef_shape, indices_shape_list, indices_length):
    if not indices_shape_list:
        broadcast_shape = []
    else:
        broadcast_shape = list(indices_shape_list[0])
        for s in indices_shape_list[1:]:
            padded_s = [1] * (len(broadcast_shape) - len(s)) + list(s)
            padded_b = [1] * (len(s) - len(broadcast_shape)) + list(broadcast_shape)
            broadcast_shape = [max(a, b) for a, b in zip(padded_b, padded_s)]
    remaining_shape = list(selfRef_shape[indices_length:])
    return broadcast_shape + remaining_shape
```
