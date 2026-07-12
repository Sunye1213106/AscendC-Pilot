# torchapi 接口参数清洗指南

## 1. 概述

本指南描述 torchapi 接口（op-plugin 项目的 `torch_npu.npu_{Op}` API）在 ascendc-st-design 技能中的参数清洗规则。

torchapi 接口文档与 aclnn 接口文档的结构存在显著差异（Python 签名 vs C++ 两段式、bullet-list vs HTML 表格、无错误码 vs 数字码表），但参数清洗后统一输出标准 11 列 Markdown 表格 + R{n} 约束章节，差异仅在信息提取层。

**核心挑战**：torchapi 文档无错误码表，aclnn 清洗指南 §2.3 的错误码隐含约束挖掘策略不适用。需使用本指南 §3 的替代约束挖掘策略。

> **文档定位**：本指南是 parameter-cleaning-guide.md §2.1.4（torchapi 专属步骤）的详细展开。主指南 §2.1.4 提供 T1-T5 摘要步骤和类型映射简表，本指南提供完整的 Python 签名解析规则、bullet-list 拆解模式、约束挖掘替代策略和完整类型映射速查表。

---

## 2. torchapi 文档信息收集

### 2.1 文档章节识别

torchapi 接口文档（`torch_npu-npu_{Op}.md`）包含以下章节：

| 章节 | 内容 | 提取目标 |
|------|------|---------|
| 产品支持情况 | 表格：产品型号 → 是否支持 | 目标产品校验（默认 950PR/950DT） |
| 功能说明 | 数学公式、计算逻辑、输入输出语义 | 功能描述 + shape 推导规则推断 |
| 函数原型 | Python 函数签名 | 参数顺序、类型、默认值 |
| 参数说明 | bullet list，每项含类型/约束 | 参数描述、dtype、shape、取值范围 |
| 返回值说明 | 输出 Tensor 的类型+shape | 输出 dtype 条件分支、输出 shape 公式 |
| 约束说明 | 跨参数约束、条件限制 | R{n} 约束提取 |
| 调用示例 | 代码示例 | 参数用法参考 |

### 2.2 Python 签名解析

从 Python signature 中提取结构化信息：

```python
torch_npu.npu_transpose_batchmatmul(input, weight, *, bias=None,
    scale=None, perm_x1=[0,1,2], perm_x2=[0,1,2], perm_y=[1,0,2],
    batch_split_factor=1) -> Tensor
```

**解析规则**：

| 签名特征 | 含义 | 提取结果 |
|---------|------|---------|
| `*` 分隔符 | 其后为仅关键字参数（kwargs） | 记录参数为 kwargs 类型 |
| 无默认值（如 `input, weight`） | 必选位置参数 | "必选/可选"列 = "必选" |
| `=None` | 可选参数，不存在时传 None | exist = [true, false] |
| `=[值]`（如 `=[0,1,2]`） | 可选参数，有默认值 | exist = [true]；默认值入"取值范围"列 |
| `=数值`（如 `=1`） | 可选参数，有默认值 | exist = [true]；默认值入"取值范围"列 |
| `-> Tensor` | 返回值为 Tensor | 记录为输出参数 |
| `-> tuple` | 返回值为多个 Tensor | 拆分为多个输出参数 |

### 2.3 Bullet-list 参数说明解析

torchapi 的参数说明使用 bullet-list 格式，每个 bullet 在一段散文中混合了多维信息。需要 **逐 bullet 结构化拆解**：

```
- **input**（`Tensor`）：必选参数，表示矩阵乘的第一个矩阵。
  数据类型支持`float16`、`bfloat16`、`float32`。同时-1轴（末轴）<=65535。
  数据格式支持ND，shape维度支持3维（B, M, K）或者（M, B, K），
  B的取值范围为[1, 65536)。支持非连续的Tensor。
```

**拆解规则**（逐 bullet 按以下模式提取）：

| 信息类型 | 提取模式 | 目标列 |
|---------|---------|--------|
| 参数名 | `- **{name}**` 或 `- {name}` | "参数名"列 |
| 类型 | `（\`{PythonType}\`）` 或 `(Tensor)` | "类型"列（按 §4 映射） |
| 必选/可选 | "必选参数" / "可选参数" / "预留参数" | "必选/可选"列 |
| 数据类型 | "数据类型支持\`X\`、\`Y\`、\`Z\`" | "数据类型"列（大写转小写） |
| 数据格式 | "数据格式支持ND" 或 "数据格式支持X" | "数据格式"列 |
| Shape/维度 | "shape维度支持N维" 或 "3维(B,M,K)" | "维度/长度"列 |
| 取值范围 | "取值范围为[X, Y)" 或 "B的取值范围为[1, 65536)" | "取值范围"列 |
| 空tensor | （torchapi 文档通常不显式声明，默认"支持"） | "空tensor"列 |
| 非连续 | "支持非连续的Tensor" / "不支持非连续" | "非连续"列 |
| 约束关系 | "X需要与Y..." / "当X时..." | "补充说明"列 + R{n} |

**特殊情况处理**：

| 情况 | 处理 |
|------|------|
| bullet 中嵌套多个约束（分号分隔） | 按分号拆分，每条独立提取 |
| 约束引用了功能说明中的变量（如 B, M, K） | 在"补充说明"列标注"（语义变量，见功能说明）" |
| "当前版本暂不支持该参数" | "必选/可选"列填"可选（当前版本暂不支持）"；exist = [false] |
| "预留参数" | 同上 |

### 2.4 功能说明中的 shape 计算规则提取

torchapi 的"功能说明"章节通常包含算子的数学公式和 shape 语义。需从中提取输出 shape 的计算规则：

**示例**（npu_transpose_batchmatmul）：

> API功能：完成张量`input`与张量`weight`的矩阵乘计算。仅支持三维的Tensor传入。
> Tensor支持转置，转置序列根据传入的数列进行变更。`perm_x1`代表张量input的转置序列，
> `perm_x2`代表张量weight的转置序列，序列值为0的是batch维度，其余两个维度做矩阵乘法。

**提取结果**：

| 信息 | 提取结论 | 来源 |
|------|---------|------|
| 固定维度 | input/weight dimensions = [3] | "仅支持三维的Tensor传入" |
| 转置语义 | perm 值为 0 的轴是 batch 维度，其余两轴做矩阵乘 | "序列值为0的是batch维度" |
| shape 依赖 | out.shape 依赖 input.shape + weight.shape + perm_x1 + perm_x2 + perm_y + batch_split_factor | "矩阵乘计算" + "转置序列" |

### 2.5 返回值说明解析

torchapi 的"返回值说明"章节可能包含条件分支，**必须**提取为约束关系 R{n}：

**示例**：

> - 当输入scale有值时，数据类型仅为`int8`类型，shape为(M, 1, B*N)；
>   否则数据类型支持`float16`、`bfloat16`、`float32`。
> - 当`batch_split_factor`>1时，shape大小计算公式为
>   [`batch_split_factor`, M, B*N/`batch_split_factor`]。

**提取规则**：

| 原文模式 | 提取的约束 | R{n} 格式 |
|---------|-----------|-----------|
| "当X有值时，dtype为Y" | 条件约束：X.exist=true → out.dtype=Y | R{n}: scale.exist → out.dtype |
| "当X>1时，shape为[...]" | 条件约束：X.value>1 → out.shape=公式 | R{m}: batch_split_factor.value → out.shape |
| "否则dtype支持A、B、C" | 补集约束：X.exist=false → out.dtype∈[A,B,C] | （合入同一 R{n}） |

---

## 3. torchapi 特有约束挖掘策略（替代 aclnn 错误码挖掘）

aclnn 清洗指南 §2.3 的错误码隐含约束是最丰富的约束来源。torchapi 无错误码，需使用以下替代策略：

### 3.1 默认值语义推断

Python 签名中的默认值包含丰富的语义信息：

| 签名默认值 | 推断结论 | YAML 因子 |
|-----------|---------|-----------|
| `param=None` | 可选参数，不存在时传 None | `exist: [true, false]` |
| `param=[0,1,2]` | 可选参数，默认值为枚举 | `exist: [true]`；`.value` 含默认值 |
| `param=1` | 可选参数，默认值为数值 | `exist: [true]`；`.value` 或 `value_range` 含默认值 |
| `param=True` | 可选 bool 参数 | `exist: [true]`；`.value: [true, false]` |

### 3.2 参数描述中的隐含值域约束

从 bullet-list 的约束描述中提取值域：

| 文档措辞 | 提取结论 | YAML 处理 |
|---------|---------|-----------|
| "取值范围为[1, N]且能被N整除" | 值域 [1,N] + 整除约束 | `value_range` + validate 整除校验 |
| "支持[0,1,2]、[1,0,2]" | 枚举排列（≤10 离散值） | `.value: [[0,1,2], [1,0,2]]` |
| "只支持[0,1,2]" | 单值枚举 | `.value: [[0,1,2]]` |
| "size大小为3" | List 长度固定 | `length_ranges: [[3, 3]]` |
| "-1轴（末轴）<=65535" | shape 最后一个轴的上界 | validate 校验 |
| "B的取值范围为[1, 65536)" | shape 某轴的上界 | `value_range` 或 validate |
| "K和N需要能被16整除" | shape 轴值整除约束 | validate 校验 |

### 3.3 功能说明中的隐含约束

从"功能说明"章节提取结构性约束：

| 文档措辞 | 提取结论 | 实现策略 |
|---------|---------|---------|
| "仅支持三维的Tensor" | dimensions 固定 | `dimensions: [3]` |
| "序列值为0的是batch维度" | perm 语义规则 | `@solves(out.shape, sources=[...perm...])` |
| "weight的Reduce维度需要与input的Reduce维度大小相等" | 跨参数 shape 约束 | `@solves(weight.shape, ...)` |

### 3.4 约束说明章节提取

torchapi 的"约束说明"章节提供跨参数约束：

**示例**：

> - 当perm_x1为[1,0,2]时，K*B的取值范围[1, 65536)；
>   当perm_x1为[0,1,2]时，K需要小于65536。
> - K和N需要能被16整除。
> - 当scale有值时，batch_split_factor只能为1。

**提取规则**：逐条提取为 R{n}，标注条件因子。

### 3.5 调用示例参数值验证

从调用示例代码中验证推断的约束：

```python
M, K, N, Batch = 32, 512, 128, 16
x1 = torch.randn((M, Batch, K), dtype=torch.float16)
x2 = torch.randn((Batch, K, N), dtype=torch.float16)
output = torch_npu.npu_transpose_batchmatmul(
    x1.npu(), x2.npu(), bias=None, scale=None,
    perm_x1=(1,0,2), perm_x2=(0,1,2), perm_y=(1,0,2),
    batch_split_factor=1)
```

**验证项**：
- shape 排列与 perm 语义一致（`perm_x1=(1,0,2)` 对应 `(M, Batch, K)`）
- dtype 在声明范围内
- 参数值符合约束

---

## 4. torchapi 参数类型映射表

torchapi 参数在步骤 1（01）阶段映射为引擎内部类型，步骤 2~4 与 aclnn 模式最大程度复用：

| torchapi 原始类型 | 步骤 1 "类型"列 | 步骤 2 YAML `type` | 因子类别 | 说明 |
|-------------------|----------------|-------------------|---------|------|
| `Tensor`（必选，无默认值） | `aclTensor` | `aclTensor` | Tensor | 必选张量 |
| `Optional[Tensor]` / `Tensor=None` | `aclTensor` | `aclTensor` | Tensor | 可选张量，exist=[true,false] |
| `Tensor`（"当前版本暂不支持"） | `aclTensor` | `aclTensor` | Tensor | 预留参数，exist=[false] |
| `List[Tensor]` | `aclTensorList` | `aclTensorList` | Tensor | 张量列表 |
| `List[int]` | `aclIntArray` | `aclIntArray` | Array | 整型数组 |
| `List[float]` | `aclFloatArray` | `aclFloatArray` | Array | 浮点数组 |
| `List[bool]` | `aclBoolArray` | `aclBoolArray` | Array | 布尔数组 |
| `int`（枚举型，小范围） | `int64_t` | `int64_t` | Scalar | 用 `.value` 枚举 |
| `int`（计数/大小型） | `int64_t` | `int64_t` | Scalar | 用 `value_range` |
| `float` | `float` | `float` | Scalar | 浮点标量 |
| `bool` | `bool` | `bool` | Scalar(枚举) | `.value: [true, false]` |
| `str` | `char*` | `string` | Scalar(枚举) | 字符串枚举 |
| `torch.dtype` | `aclDataType` | `aclDataType` | Scalar(枚举) | dtype 枚举 |
| `-> Tensor`（返回值） | `aclTensor` | `aclTensor` | Tensor(output) | 输出参数 |

---

## 5. 预留参数处理

torchapi 文档中的预留参数（如 bias 标注"当前版本暂不支持该参数"）处理规则：

1. "必选/可选"列填写"可选（当前版本暂不支持）"
2. "补充说明"列标注 `exist=[false]；当前版本暂不支持`
3. 其余列（dtype、shape、format）按文档填写或填 `-`
4. 步骤 2 YAML 中设置 `{name}.exist: [false]`
5. 引擎求解时自动为 exist=false 的参数返回 `NOT_APPLICABLE`
6. 步骤 4B 生成 L2 异常用例时，不为 exist=[false] 的参数生成 `required_param_missing` 异常
7. 步骤 4B 为该参数生成 `reserved_param_used` 异常用例（传入非 None 值）

---

## 6. 中间因子命名约定

torchapi 文档中的 shape 描述常含语义变量（如"3维（B, M, K）"），需提取为 **中间因子**（intermediate factors）。命名约定：

- **必须以 `_` 前缀命名**，与算子参数区分（下游输出层用 `startswith('_')` 识别并剔除）
- **统一使用小写**：`_batch`、`_m`、`_k`、`_n`、`_dim`、`_scenario` 等
- 因子名格式：`{name}.value`、`{name}.value_range`
- `@solves` sources 引用时必须与 YAML intermediate 键**精确一致（大小写敏感）**

> **权威依据**：本约定源自 `constraint-writing-guide.md §3.5`，与全部生产算子（aclnnFusedCausalConv1d、aclnnScatterPaKvCache、aclnnMoeFinalizeRoutingV3 等）一致。

---

## 7. 输出格式

与 aclnn 清洗结果完全相同的 11 列标准表格 + R{n} 约束章节。差异仅在"补充说明"列的标注方式：

| 差异项 | aclnn 模式 | torchapi 模式 |
|--------|-----------|--------------|
| 默认值来源 | 通常"默认值未知（文档未说明）" | Python 签名明确标注 |
| exist 标注 | 从错误码推断 | 从 `=None` 签名推断 |
| 预留参数 | 从错误码"预留参数"推断 | 从"当前版本暂不支持"推断 |
