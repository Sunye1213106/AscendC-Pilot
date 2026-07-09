# 01_parameter_description.md -> 02_test_factors.yaml 映射规则

## 1. 参数类型分类

| 01_parameter_description.md "类型"列 | 02_test_factors.yaml type | 类别 |
|---|---|---|
| aclTensor | aclTensor | Tensor |
| aclTensorList | aclTensorList | Tensor |
| aclIntArray | aclIntArray | Array |
| aclFloatArray | aclFloatArray | Array |
| aclBoolArray | aclBoolArray | Array |
| aclScalarList | aclScalarList | Array |
| aclScalar | aclScalar | Scalar |
| char* | string | Scalar(枚举) |
| bool | bool | Scalar(枚举) |
| aclDataType | aclDataType | Scalar(枚举) |
| int4_t ~ uint64_t 等 | 对应标量类型 | Scalar |
| float/float16/bfloat16/float32/double | 对应标量类型 | Scalar |

> **torchapi 模式**：torchapi 参数在步骤 1 已映射为以上内部类型（映射规则见 [torchapi-cleaning-guide.md](torchapi-cleaning-guide.md) §4），因此步骤 2 的类型判定规则与 aclnn 完全相同。


## 2. io_type 映射

| 01_parameter_description.md "输入/输出"列 | 02_test_factors.yaml | 说明 |
|---|---|---|
| 输入 | `io_type: input` | 纯输入 |
| 输出 | `io_type: output` | 纯输出 |
| **输入/输出（内存复用）** | `io_type: input` + **`in_place: true`** | 地址复用参数，`io_type` 取 `input` 以保证参数顺序、初始数据生成和 IMPL-RANGE 注册，`in_place: true` 触发 `output_tensor_indexes` 标识 |

> **torchapi 返回值**：torchapi 签名 `-> Tensor` 在 01 中作为独立输出参数行处理（参数名通常为 `out`），`io_type: output`。

> **可选参数 exist 映射补充说明**（对上述 `{name}.exist` 规则的细化）：
>
> | 01_parameter_description.md "必选/可选"列 | 02_test_factors.yaml exist 因子 | 适用类型 |
> |---|---|---|
> | 必选 | `[true]` | 所有类型 |
> | 可选 | `[true, false]` | aclTensor、aclScalar、aclIntArray、char* 等指针类型 |
> | 必须为nullptr（预留参数） | `[false]` | 仅 exist=false |
> | 条件可选（由其他参数控制） | **不在 YAML 中定义 exist 因子**（不写即可，引擎将通过 @solves 推导） | aclTensor、aclScalar、aclIntArray 等指针类型 |
>
> - 当参数判定为可选时，**必须**将 exist 设为 `[true, false]`
> - 当 exist=false 时，该参数的其他因子（dtype、shape 等）由约束函数处理（返回 NOT_APPLICABLE）
> - 预留参数（必须为 nullptr）的 exist 设为 `[false]`，dtype 等因子仍需定义（用于约束函数内部引用）
>
> **条件可选参数的 exist 映射**：当 `01_parameter_description.md` 中某参数的"必选/可选"列标记为"条件可选"，或"补充说明"明确指出其存在性由另一个参数控制时，**禁止**在 YAML 中定义 `{name}.exist` 因子。必须在 `04_constraints.py` 中写 `@solves('{name}.exist', sources=['{control_param}.{attribute}'])` 从控制参数推导 exist 值。
>
> 控制源类型与实现模板（详见 [constraint-writing-guide.md](constraint-writing-guide.md) 模式 7 情况 E）：
> - **BoolArray 元素**：`@solves('gradInputOut.exist', sources=['outputMask.value'])` → `return outputMask_value[0]`
> - **bool 标量**：`@solves('inverseOut.exist', sources=['returnInverse.value'])` → `return returnInverse_value`
> - **null 状态**：`@solves('y2.exist', sources=['scales2Optional.exist'])` → `return scales2Optional_exist`
> - **enum 值**：`@solves('x3.exist', sources=['fusedOpType.value'])` → `return fusedOpType_value in ['add', 'mul']`
>
> **反模式（禁止）**：将条件可选参数的 exist 设为静态值 `[true]`。这导致控制参数为"不产出"值时，被控参数仍为非空，null 指针场景完全遗漏。

## 3. 各类型因子生成规则

### Tensor 类 (aclTensor / aclTensorList)

| 因子 | 映射来源 | 规则 | 溯源标注 |
|---|---|---|---|
| {name}.exist | 必选/可选 | 必选 -> [true]，可选 -> [true, false] | — |
| {name}.format | 数据格式 | 直接取值：ND -> [ND]，ND/NCHW -> [ND, NCHW] | — |
| {name}.dimensions | 维度/长度 | 严格按 §4 维度解析规则映射；"0-8维" -> [0,1,2,3,4,5,6,7,8]，"3维" -> [3]，"2-4维" -> [2,3,4] | **必须** |
| {name}.dtype | 数据类型 | 大写转小写：FLOAT16 -> float16 | — |
| {name}.length_ranges | 维度/长度(TensorList) | 优先从 01 "维度/长度"列解析（如 "个数: [1,32]" → `[[1,32]]`）；仅当文档未明确约束个数范围时才使用默认值 `[[1,128]]` | **必须** |
| {name}.dtype_list | 数据类型 (TensorList) | **仅当** 01 补充说明中存在 TensorList 内部 dtype 约束时生成。因子值为空列表 `[]`，由 `04_constraints.py` 中的 `@solves` 函数填充（参见 constraint-writing-guide.md 模式 14） | **必须**（当生成时） |
| {name}.shape | 维度/长度 | 仅当shape为固定常量值时定义（如"shape固定为[1]"→`[[1]]`，"shape固定为[1,1]"→`[[1,1]]`）；值格式为外层列表包裹候选shape，即`[[shape1], [shape2], ...]`；未定义时由引擎内置 IMPL-SHAPE 从 dimensions 生成随机 shape | **必须**（当shape固定时） |
| {name}.value_range_{dtype} | 取值范围 | 仅在有特殊要求时显式定义 | 自定义时**必须** |
| {name}.in_place | 补充说明 | 01 中被判定为内存复用参数（"输入/输出"列 = "输入/输出"）→ `true`；否则不定义（默认 `false`） | **必须**（当判定为内存复用时） |
| support_infnan | 约束说明/取值范围 | 参数级字段（与 `type`/`io_type` 同级，不在 `factors` 下）。仅当文档明确声明"不支持inf/nan"时定义为 `false`；不定义时默认 `true`（覆盖 inf/nan）。仅对含 float dtype 的输入 tensor 有意义 | **必须**（当文档声明不支持时） |
| support_empty_tensor | 空tensor列 | 参数级字段（与 `type`/`io_type` 同级，不在 `factors` 下）。01 "空tensor" 列为"不支持"时定义为 `false`；不定义时默认 `true`（QA 检查空tensor轴覆盖，生成器覆盖 ET 场景）。仅对 input tensor 有意义 | **必须**（当01标注"不支持"时） |

> **TensorList dtype_list 因子检测规则**：当 `01_parameter_description.md` 中某 `aclTensorList` 参数的"补充说明"列包含"列表内部...推导规则"或"互推导"措辞（即 §E 的 `[互推导]` (TensorList 内部) 格式）时，**必须**为该参数额外生成 `{name}.dtype_list` 因子（值为空列表 `[]`），作为约束函数的 target 占位。该因子不参与默认枚举，其值完全由 `04_constraints.py` 中的 `@solves('{name}.dtype_list', ...)` 函数生成。未检测到 TensorList 内部 dtype 约束时，**不生成**此因子。

> **format 与 dimensions 的依赖关系**：当算子使用固定维度格式（NCL、NCHW、NC1HWC0 等，完整列表见 [format-constraints.md](format-constraints.md) §1）时，`dimensions` 域值必须覆盖所有 format 对应的维度数（如 `format: [NCL, NCHW]` 时 `dimensions: [3, 4]`），且**必须**在 `04_constraints.py` 中用查找表映射模式写 `@solves('{name}.dimensions', sources=['{name}.format'])` 约束（参见 [constraint-writing-guide.md](constraint-writing-guide.md) 模式 13 format→dimensions 特例）。**禁止**在 YAML 中定义 format 和 dimensions 但不写约束，否则引擎独立采样会产生 NCL+4D 等非法组合。

### Array 类

| 因子 | 映射来源 | 规则 | 溯源标注 |
|---|---|---|---|
| {name}.exist | 必选/可选 | 同上 | — |
| {name}.length_ranges | 维度/长度 | 优先从 01 "维度/长度"列解析；仅当文档未明确约束长度范围时才使用默认值 `[[0,8]]` | **必须** |
| {name}.dtype | 数据类型 | 同上 | — |
| {name}.value_range_{dtype} | 取值范围 | 仅特殊要求时定义 | 自定义时**必须** |

> **torchapi `List[int]` 参数**：torchapi 的 `List[int]` 参数 size 通常固定（如"size大小为3"），`length_ranges` 直接设为文档声明值（如 `[[3, 3]]`）；合法排列枚举写入 `.value`（如 `[[0,1,2], [1,0,2]]`）。详见 [torchapi-cleaning-guide.md](torchapi-cleaning-guide.md) §3.2。

### Scalar 类

| 因子 | 映射来源 | 规则 | 溯源标注 |
|---|---|---|---|
| {name}.exist | 必选/可选 | 同上 | — |
| {name}.dtype | 数据类型 | 同上 | — |
| {name}.value | 取值范围(枚举/固定值) | 满足以下**任一条件**时使用 `.value`（详见下方判定规则）：<br>• bool 类型：`[true, false]`<br>• 文档明确列举所有合法值（≤10 个离散值），如"取值为0、1"<br>• 文档标注"不支持此字段"/"历史遗留接口"/"固定传N"：固定单值 `[N]` | — |
| {name}.value_range_{dtype} | 取值范围(连续区间) | **以上 `.value` 条件均不满足时使用 `value_range`**。具体包括：<br>• 文档含不等式（"≥N"、">N"、"≤N"）或区间（"[lo,hi]"）<br>• 参数语义为计数/索引/长度/比例（推断为连续值域，见 parameter-cleaning-guide.md §2.6 模式 #8）<br>• 文档写"默认值N"但参数参与跨参数比较/匹配（详见下方消歧规则）<br>• 有哨兵值+连续范围（如 -1 表示自动推断/不生效）<br>不定义时由引擎 `DEFAULT_VALUE_RANGES` 自动覆盖 | 自定义时**必须** |

> **Scalar `.value` vs `value_range` 判定规则**
>
> 对每个非 Tensor 的标量参数（`int64_t`、`float`、`bool`、`aclScalar` 等），按以下优先级判定使用
> `.value` 还是 `value_range`：
>
> | 优先级 | 文档信号 | 使用形式 | 典型示例 |
> |--------|---------|---------|---------|
> | 1（最高） | "不支持此字段"/"历史遗留接口"/"固定传N" | `.value: [N]` | activationMode: "不支持此字段" → `.value: [0]` |
> | 2 | bool 类型 | `.value: [true, false]` | residualConnection: bool → `.value: [true, false]` |
> | 3 | 文档明确列举所有合法值（≤10 个离散值） | `.value: [v1, v2, ...]` | convMode: "取值为0、1" → `.value: [0, 1]` |
> | 4 | 文档含不等式（"≥N"、">N"、"≤N"）或区间（"[lo,hi]"） | `value_range_{dtype}` | blockSize: "取值范围≥2" → `value_range_int64` |
> | 5 | 参数语义为计数/索引/长度/比例（连续值域推断） | `value_range_{dtype}` | maxQueryLen: seq_len 计数语义 ≥1，-1 为哨兵 → `value_range_int64` |
> | 6 | 文档写"默认值N"但参数参与跨参数比较/匹配 | `value_range_{dtype}` | padSlotId: "默认值-1"，与 cacheIndices 值比较 → `value_range_int64` |
> | 7（最低） | 无约束且不影响输出 | 不定义（引擎默认填充） | — |
>
> **⚠️ "默认值N" ≠ "固定值N"**
>
> | 文档措辞 | 含义 | 正确做法 |
> |---------|------|---------|
> | "默认值N" | N 是默认初始值，参数**可取其他值** | 分析完整值域，通常为 `range` |
> | "固定值N"/"固定传N" | 参数**只能取** N | `.value: [N]` |
> | "不支持此字段" | 字段无意义 | `.value: [N]` |
>
> 当文档出现"默认值N"时，检查该参数是否与其他参数有比较/匹配关系
> （如"当 `X[i]==param` 时..."）。若有，说明参数可取 X 值域中的任意值，
> 应使用 `value_range` 而非固定为默认值。典型示例：
>
> | 参数 | 文档措辞 | 跨参数关联 | 正确形式 |
> |------|---------|-----------|---------|
> | padSlotId | "默认值-1" | "当 cacheIndices[i]==padSlotId 时跳过" | `value_range_int64`：`[-1,-1]` + `[0, numSlots-1]` |
> | activationMode | "不支持此字段" | 无 | `.value: [0]`（固定值） |

## 4. 维度解析规则

| 01_parameter_description.md 原文 | dimensions 值 | 说明 |
|---|---|---|
| 0-8维 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 0 维 = 标量 tensor（shape=[]） |
| 1-4维 | [1, 2, 3, 4] | 不含 0 维 |
| 3维 | [3] | 固定维度 |
| 2维 | [2] | 固定维度 |
| N维 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 等价于 0-8维 |
| X-Y维 | [X, X+1, ..., Y] | 通用模式：X、Y 为正整数或 0，X ≤ Y；若 X=0 则包含 0 维 |
| K维 | [K] | 固定维度，K 为正整数 |

## 4.1 场景感知因子域收窄

当 `01_parameter_description.md`（经 parameter-cleaning-guide §2.1.1 S1 清洗后）标注目标产品仅支持部分场景时，步骤 2 YAML 生成时对 01 中已标注"仅在不支持场景下可达"的因子值执行收窄：

| 因子类型 | 收窄规则 | 示例 |
|---------|---------|------|
| dimensions | 剔除仅在不支持场景可达的维度值 | value.dimensions："0、3、4" → 01 标注0维仅场景6 → YAML `[3, 4]` |
| exist | exist=False 仅在不支持场景可达时，收窄为 `[true]` | value.exist：0维仅场景6 → YAML `[true]` |
| 枚举值 | 剔除仅在不支持场景使用的取值 | scatterMode："NHSD"仅场景7 → YAML `.value` 去掉"NHSD" |

> **注意**：收窄依据来自 01 的 S1 清洗标注。步骤 2 直接读取 01 已清洗后的因子域值，无需重复判断场景可达性。

## 5. 数据类型映射

| 01_parameter_description.md | 02_test_factors.yaml |
|---|---|
| FLOAT16 | float16 |
| FLOAT32 | float32 |
| FLOAT64 | float64 |
| INT8 | int8 |
| INT16 | int16 |
| INT32 | int32 |
| INT64 | int64 |
| UINT8 | uint8 |
| UINT16 | uint16 |
| UINT32 | uint32 |
| UINT64 | uint64 |
| BOOL | bool |
| BFLOAT16 | bfloat16 |
| COMPLEX32 | complex32 |
| COMPLEX64 | complex64 |
| COMPLEX128 | complex128 |

## 6. value_range 定义规则

### 6.0 值域模式前置判定与场景分类

#### 6.0.0 前置判定：`.value` 还是 `value_range`？

**在应用 S1/S2 场景分类之前，必须先完成值域模式前置判定**（依据 §3 Scalar 映射表的判定规则）。

| 文档信号 | 使用形式 | 是否继续 S1/S2 |
|---------|---------|--------------|
| bool / 明确枚举（≤10 离散值）/ "不支持此字段"/"固定传N" | `.value` | **否**（无需 value_range） |
| 不等式 / 区间 / 计数索引语义 / "默认值"+跨参数关联 / 哨兵值+连续范围 | `value_range` | **是**（S1/S2 决定分段构造方式） |
| 无约束且不影响输出 | 不定义（引擎默认） | 否 |

> 此前置判定**优先于**下方的 S1/S2 分类。一个不影响 shape 的连续值域参数
> （如 blockSize "≥2"），无论 S1 还是 S2，都应使用 `value_range` 而非 `.value`。

#### 6.0.1 场景分类（仅适用于 `value_range` 参数）

`value_range` 的构造目标取决于该因子的值是否直接决定 tensor shape。

| 场景 | 判定条件 | 覆盖目标 | 推荐做法 |
|------|---------|---------|---------|
| **S1: 值域影响 shape** | 该参数的 `.value` 被 `@solves` 用于推导某个 tensor 的 `.shape` | 完整 shape 范围 `[0, MAX_SHAPE_PRODUCT]`，必要时覆盖溢出边界 | 必须显式定义 `value_range`，按数量级分层构造 |
| **S2: 值域不影响 shape** | 该参数的 `.value` 不驱动任何 `.shape` | 数据类型的完整边界集合 + 文档明确定义的语义边界 | 通常不定义 `value_range`，由引擎 `DEFAULT_VALUE_RANGES` 自动覆盖；若文档有额外语义边界，再追加 |

**数据类型完整边界**指引擎 `scripts/utils.py` 中 `DEFAULT_VALUE_RANGES` 为该 dtype 预定义的关键取值，包括但不限于：
- 极值（如 float32 的 `±3.4028235e38`）
- 零、±1
- 最小正数（如 float32 的 `±1.1754943508e-38`）
- 特殊浮点值（`inf`、`-inf`、`nan`）
- 整数类型的最小/最大值

**文档语义边界**指参数说明表、错误码或功能说明中显式提及的阈值（如 `dim ∈ [-ndim, ndim)`、`steps ≥ 0`、`alpha ∈ [0, 1]` 等）。

### 6.1 判定流程

```
Step 0: 值域模式前置判定（§3 Scalar 映射表判定规则，优先级从高到低）
├─ "不支持此字段" / "历史遗留" / "固定传N" ───────► .value: [N]
├─ bool 类型 ─────────────────────────────────► .value: [true, false]
├─ 文档明确列举所有合法值（≤10 离散值）─────────► .value: [v1, v2, ...]
├─ 文档含不等式（≥N, >N）/ 区间（[lo,hi]）──────► value_range → 进入 Step 1
├─ 计数/索引/长度/比例语义（连续值域推断）──────► value_range → 进入 Step 1
├─ "默认值N" + 跨参数比较/匹配关系 ─────────────► value_range → 进入 Step 1
│    ⚠️ "默认值N"不等于"固定值N"，需分析完整值域
├─ 哨兵值 + 连续范围（如 -1 + [1,+∞)）─────────► value_range → 进入 Step 1
└─ 无约束且不影响输出 ──────────────────────► 不定义（引擎默认填充）

Step 1: value_range 参数的 S1/S2 场景分类
├─ 该参数的 .value 是否驱动 .shape?
│   ├─ 是（S1: 影响 shape）────────────────────► 按 §6.3 构造完整 shape 范围 value_range
│   │                                            必须覆盖 [0, MAX_SHAPE_PRODUCT] 及溢出边界
│   └─ 否（S2: 不影响 shape）
│         01 "取值范围"列含值域约束信号？
│         │  （"推断值域：{表达式}" / 显式不等式 >X, ≥X, <X, ≤X / 显式区间 [lo,hi]）
│         ├─ 是 → 进入值域分段构造
│         └─ 否 → 参数值影响算子输出?
│                ├─ 否 → 不定义（引擎默认填充 DEFAULT_VALUE_RANGES）
│                │        适用: Tensor 类、输出参数、不影响输出的参数
│                └─ 是 → 值域跨度≤3 个数量级 且 语义边界≤2 个?
│                       ├─ 是 → 单段 [[lo, hi]]
│                       │        例: alpha.value_range_float32: [[0.0, 1.0]]
│                       └─ 否 → 分段式 [[lo1,hi1], [lo2,hi2], ...]
```

**S2 场景优先策略**：若文档未显式约束值域，且该参数不影响 shape，通常**不需要在 YAML 中定义 `value_range`**，引擎会自动使用 `DEFAULT_VALUE_RANGES` 覆盖该 dtype 的完整边界集合。只有当文档给出了额外的语义边界（如"必须在 [-10, 10] 内"）时，才需要在 YAML 中追加自定义分段。

以下情况**需要**显式定义：S1 场景、元素范围与默认不同的 Array 参数、取值受限的 Scalar 参数、文档明确限制范围的参数、名称含 dim/axis 的参数（默认 `[-ndim, ndim)`）。

### 6.2 分段构造规则

**核心原则**：以语义边界值为分段端点构造覆盖完整有效值域的分段列表；关键语义边界值必须使用退化段 `[v, v]` 强制精确命中（随机采样在宽区间内命中精确值的概率趋近零）。

**构造步骤**：

1. **提取语义边界 + 补充分割点**：从 `01_parameter_description.md` 提取改变输出行为的关键阈值，按数量级插入分割点（典型：1, 10, 100, 1000, 10000, 100000）
2. **排序构造段**：将所有边界值排序，相邻值构成 `[lo, hi]` 段；确定有效上下界（取 dtype min/max 或语义约束端点）
3. **验证覆盖**：首段 lo = 有效下界，末段 hi = 有效上界

**语义边界识别**：

| 边界类型 | 识别方法 | 示例 |
|---------|---------|------|
| 功能开关值 | 参数=某值时功能不生效或切换分支 | minlength=0 不生效 |
| 有效值端点 | 约束条件中的最小/最大值 | dim ∈ [-ndim, ndim) |
| 公式临界点 | 输出 shape/计算公式发生变化的值 | minlength > max(self) 时 out.shape 改变 |
| dtype / 产品极值 | 数据类型 min/max 或shape边界限制 | int64 极值; MAX_OUTPUT_SIZE=2147483648 |

**段构造约束**：
- 关键语义边界值用退化段 `[v, v]` 强制命中；相邻段可重叠（如 `[0,0]` 和 `[0,1]`）
- 每段跨度 ≤2 个数量级；分段总数 6-12 段

**S2 场景补充**：对于不影响 shape 的参数，`value_range` 的首要目标是覆盖 `DEFAULT_VALUE_RANGES` 为该 dtype 预定义的完整边界集合。因此：
- 若文档未给出额外语义边界，**不必在 YAML 中重复定义** value_range，由引擎自动填充
- 若文档给出了额外语义边界，在引擎默认值基础上追加自定义分段，而非用一个窄范围替换默认值

**错误示例**（start 是 float32，不影响 shape）：
```yaml
# ❌ 错误：只定义了 [-100, 100]，遗漏了 float32 的极值、最小正数、inf/nan 等 dtype 边界
start.value_range_float32:
  - [-100.0, 100.0]
```

**正确做法**：
```yaml
# ✅ 推荐：不定义 value_range，引擎自动使用 DEFAULT_VALUE_RANGES 覆盖完整 dtype 边界
start:
  type: aclScalar
  factors:
    start.dtype: [float32]
    # value_range 留空，由引擎自动填充完整 dtype 边界

# 或：若文档有额外语义边界，需手动完整定义 value_range（包含 dtype 边界 + 语义边界）
# 注意：引擎不会自动合并默认值，YAML 中一旦定义 value_range 就会完全替换默认值
start.value_range_float32:
  - [-3.4028235e38, 3.4028235e38]   # float32 极值
  - [0.0, 0.0]
  - [1.0, 1.0]
  - [-1.0, -1.0]
  - [1.1754943508e-38, 1.1754943508e-38]   # 最小正数
  - [-1.1754943508e-38, -1.1754943508e-38]
  - ["inf", "inf"]
  - ["-inf", "-inf"]
  - ["nan", "nan"]
  - [-100.0, 100.0]                 # 文档语义边界（示例：若文档限制指数在 [-100, 100]）
```

### 6.3 S1 场景：shape 决定因子的 value_range 构造模板

当某参数的 `.value` 直接决定 tensor shape 时（如 `steps.value` → `out.shape=[steps]`），其 `value_range` 必须覆盖从 0 到 `MAX_SHAPE_PRODUCT` 的完整 shape 范围，必要时包含溢出边界以验证异常行为。

**标准分段结构**（以 int64 类型的 shape 决定因子为例）：

```yaml
steps.value_range_int64:
  - [0, 0]                          # 空 tensor
  - [1, 1]                          # 单元素 tensor
  - [0, 1]                          # 0-1 过渡
  - [1, 10]                         # 小 shape
  - [10, 100]                       # 中小 shape
  - [100, 1000]                     # 中 shape
  - [1000, 10000]                   # 较大 shape
  - [10000, 100000]                 # 大 shape
  - [100000, 1000000]               # 很大 shape
  - [1000000, 100000000]            # 超大 shape
  - [100000000, 2147483648]         # 近 2G 边界（int32 最大值）
```

**分段原则**：
1. 必须包含 `[0, 0]` 和 `[1, 1]` 退化段
2. 按数量级递增分层，每段跨度不超过 2 个数量级
3. 必须覆盖到 `MAX_SHAPE_PRODUCT`（默认 2147483648）
5. 分段总数控制在 6-12 段之间

**反模式**：
- ❌ 使用 `.value` 枚举固定值（如 `[1, 2, 5, 10, 50, 100, ...]`）→ 会导致 shape 多样性严重不足
- ❌ 只覆盖小范围（如 `[1, 10000]`）→ 遗漏大 shape 和边界场景
- ❌ 单段 `[0, 2147483648]` → 随机采样无法命中 0、1 等关键退化边界

### 6.3.1 文档值域保真原则

当因子的值域在 `01_parameter_description.md` 中有明确文档约束（约束关系 R{n} 中的 `[N, M]`、`≥N`、`≤M` 等数值范围）时，YAML `value_range` **必须覆盖文档完整范围**，且上界不得低于文档上界。

**禁止**以以下理由缩减 YAML 域上界：
- "避免shape溢出"
- "测试资源预算"
- "组合爆炸"
- "限制到X"

测试执行性能问题在 `@solves` 采样策略中解决（如偏向小值采样），不在域定义阶段截断。

> 此原则与 SKILL.md "⚠️ 锚点数量不作为因子形式选择依据"平行：后者禁止将 `value_range` 改为 `.value` 单值，本原则禁止缩减 `value_range` 上界。两者均会导致值域覆盖缺失、边界值未测试。

**中间因子说明**：中间因子（如 `_cu_seq_len`）不在 01 参数列表中，但其值域约束记录在 01 的 `## 约束关系` R{n} 章节中。需从 R{n} 提取文档范围，同样适用本原则。场景相关值域采用 YAML 声明最宽范围 + @solves 按场景收窄的模式（详见 constraint-writing-guide.md §3.3"场景相关值域中间因子"）。

当多个shape决定因子的乘积受上限约束（如 `product ≤ 2G`）时，禁止将这些因子定义为独立采样的锚点中间因子，应使用预算分配模式——详见 constraint-writing-guide.md §3.3.2"多维度Product约束的预算分配模式"。

**反模式示例**：
```yaml
# ❌ 错误：文档约束 cu_seq_len ∈ [batch, 1024*1024]，YAML 截断为 8192
_cu_seq_len.value_range: [[1, 8192]]
# 来源: 文档约束cu_seq_len范围[batch, 1024*1024]，限制到8192避免shape溢出

# ✅ 正确：覆盖文档完整范围 [1, 1048576]
_cu_seq_len.value_range:
  - [1, 1]
  - [1, 16]
  - [16, 256]
  - [256, 1024]
  - [1024, 8192]
  - [8192, 65536]
  - [65536, 1048576]
# 来源: 01_parameter_description.md 约束说明章节 "cu_seq_len范围[batch, 1024*1024]"
```

### 6.4 场景模板

**有符号整数参数**（索引/轴类）：
```yaml
value_range_int64:
  - [0, 0]        # 零轴（退化段）
  - [1, 1]        # 正1轴（退化段）
  - [-1, -1]      # 末轴（退化段）
  - [0, 1]        # 首轴附近
  - [-1, 0]       # 末轴附近
  - [-1, 1]       # 正负过渡
  - [-8, 8]       # 宽范围
  - [-8, -1]      # 纯负
  - [1, 8]        # 纯正
```

**归一化浮点参数**（[0, 1]）：
```yaml
value_range_float32:
  - [0.0, 0.0]    # 零（退化段）
  - [0.5, 0.5]    # 中点（退化段）
  - [1.0, 1.0]    # 满值（退化段）
  - [0.0, 0.5]    # 前半
  - [0.5, 1.0]    # 后半
```

### 6.5 检查清单

- [ ] 每个关键语义边界值有退化段 `[v, v]` 强制覆盖
- [ ] 段集合覆盖从有效下界到有效上界的完整值域
- [ ] 每段跨度 ≤2 个数量级
- [ ] 分段总数在 6-12 之间
- [ ] 与引擎默认值域对比过，确认自定义更优（见附录 A）
- [ ] 01 中含"推断值域"或显式值域表达式的参数在 YAML 中有对应 value_range 或 .value 定义

---

### 附录 A：引擎默认值域参考

见 `scripts/utils.py` 中 `DEFAULT_VALUE_RANGES`（函数 `get_default_value_range(dtype)`）。自定义 value_range 时应与默认对比，仅在自定义能提供更精准的语义边界覆盖时替换。

---

### 附录 B：完整示例

以 `aclnnBincount` 的 `minlength`（int64_t，非负，有效范围 `[0, 2147483648]`）为例：

- 语义边界：0（不生效）、1（最小生效）、2147483648（产品上界）
- 数量级分割：10, 100, 1000, 10000, 100000, 1000000

```yaml
minlength.value_range_int64:
  - [0, 0]                
  - [0, 1]                
  - [1, 10]
  - [10, 100]
  - [100, 1000]
  - [1000, 10000]
  - [10000, 100000]
  - [100000, 1000000]
  - [1000000, 2147483648] 
```

> **对比默认**：引擎默认 int64 含负值段 `[-1,0]`、`[-1000,-10]` 等，对非负参数无意义。自定义版移除负值段，新增 `[0,0]` 退化段，更优。

---

### 附录 C：Array 类参数注意事项

Array 类参数（aclIntArray / aclFloatArray / aclBoolArray）的 value_range 与 Scalar 差异：

1. **双维度控制**：`length_ranges` 控制元素个数，`value_range_{dtype}` 控制每个元素的取值范围，二者独立
2. **元素级范围**：分段列表适用于**每个元素**，引擎为每个元素独立选段采样
3. **动态范围**：可通过 `@solves('param.value_range_int64', sources=[...])` 在约束函数中动态计算
4. **length_ranges 优先**：数组长度为 0 时 `value_range` 不生效

## 7. 完整示例与溯源标注规范

### 7.1 标注格式

当参数因子的域值来源于 `01_parameter_description.md` 中的明确约束时，**必须**在 YAML 中以注释标注来源：

```yaml
参数名:
  type: 类型
  io_type: input/output
  factors:
    因子名: 域值
    # 来源: {来源描述}
```

**来源描述的两种模板**：

1. **文档有明确约束**：`# 来源: 01_parameter_description.md "{列名}"列 "{原文关键片段}"`
2. **文档未约束，使用默认值**：`# 来源: 映射规则默认值（文档未约束{属性}范围）`

需标注的因子类型见 §3 各类型因子生成规则表的"溯源标注"列。

### 7.2 完整示例：aclnnReduceNansum

```yaml
operator_name: aclnnReduceNansum  # aclnn 接口填 aclnn{Op}，REG_OP 接口填算子名（如 AddN）

self:
  type: aclTensor
  io_type: input
  factors:
    self.exist: [true]
    self.format: [ND]
    self.dimensions: [0, 1, 2, 3, 4, 5, 6, 7, 8]
    # 来源: 01_parameter_description.md "维度/长度"列 "0-8维"
    self.dtype: [float16, float32, int8, int16, int32, int64, uint8, bool, bfloat16]

dim:
  type: aclIntArray
  io_type: input
  factors:
    dim.exist: [true]
    dim.length_ranges: [[0, 8]]
    # 来源: 01_parameter_description.md "维度/长度"列 "[0, self.dim()]。长度为0时表示对所有轴做ReduceNansum计算"
    dim.dtype: [int64]
    dim.value_range_int64:
      - [-8, 7]
      - [-8, -8]
      - [7, 7]
      - [-1, 0]
      - [0, 0]
      - [0, 1]
      - [-1, 1]
      - [-2, -1]
      - [1, 2]
      - [-7, 7]
    # 来源: 01_parameter_description.md "取值范围"列 "每个元素取值范围为[-self.dim(), self.dim())"

keepDim:
  type: bool
  io_type: input
  factors:
    keepDim.exist: [true]
    keepDim.dtype: [bool]
    keepDim.value: [true, false]

dtype:
  type: aclDataType
  io_type: input
  factors:
    dtype.exist: [true]
    dtype.dtype: [string]
    dtype.value: [float16, float32, int8, int16, int32, int64, uint8, bool, bfloat16]

out:
  type: aclTensor
  io_type: output
  factors:
    out.exist: [true]
    out.format: [ND]
    out.dimensions: [0, 1, 2, 3, 4, 5, 6, 7, 8]
    # 来源: 01_parameter_description.md "维度/长度"列 "0-8维"
    out.dtype: [float16, float32, int8, int16, int32, int64, uint8, bool, bfloat16]
```

### 7.2.1 内存复用参数示例

当参数"输入/输出"列为"输入/输出"时（如 scatter 类算子的 cache 参数），需设置 `io_type: input` + `in_place: true`：

```yaml
keyCacheRef:
  type: aclTensor
  io_type: input       # 取 input 保证参数顺序、初始数据、IMPL-RANGE
  in_place: true       # 标识为内存复用，触发 output_tensor_indexes 生成
  factors:
    keyCacheRef.exist: [true]
    keyCacheRef.format: [ND, FRACTAL_NZ]
    keyCacheRef.dimensions: [4, 5]
    keyCacheRef.dtype: [float16, float32, bfloat16]
```

**`in_place` 字段规则**：

| 属性 | 值 |
|------|-----|
| 类型 | `bool`，可选字段，默认 `false` |
| 取值条件 | 仅当参数"输入/输出"列 = "输入/输出"且被判定为内存复用时设为 `true` |
| 禁止场景 | 纯输入参数禁止设 `in_place: true`；纯输出参数应直接用 `io_type: output` |
| 作用域 | 与 `io_type` 同级定义在参数节点下 |

### 7.3 检查清单

- [ ] `length_ranges` 的上下界是否与 01 中记录的个数/长度约束一致
- [ ] `dimensions` 的范围是否与 01 中记录的维度范围一致（若 01 原文含 "0" 则域值须包含 0）
- [ ] 溯源标注引用的原文范围与域值实际覆盖范围是否一致（如原文 "0-8维" 则域值须从 0 开始）
- [ ] 自定义的 `value_range_{dtype}` 分段是否标注了文档中对应的语义边界
- [ ] 每个标注的来源描述中，列名和原文片段是否可在 01 中定位到
- [ ] 使用默认值时是否标注了"映射规则默认值（文档未约束...）"
