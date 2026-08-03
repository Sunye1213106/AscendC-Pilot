# 【问题反馈】FlashAttentionScoreGrad (arch35)：FP32 + Rope 产出未声明 TilingKey

| 项 | 内容 |
|---|---|
| 算子 | `FlashAttentionScoreGrad` |
| 架构 | `arch35` / Ascend950 / DAV_3510 |
| 严重级别 | **High**（host 成功编码 key，kernel 无对应实例 → 运行期可能找不到 kernel） |
| 问题类型 | Host tiling 与 Kernel TPL / 产品约束不一致（契约断裂） |
| 发现时间 | 2026-08-03 |
| 复现环境 | ops-transformer host UT 框架直调 tiling（无需 NPU） |
| 相关仓库路径 | `attention/flash_attention_score_grad/` |

---

## 1. 一句话结论

当输入为 **`query.dtype = FLOAT32` 且同时提供 `query_rope` / `key_rope`** 时：

1. **Host tiling 接受该组合**，成功返回 `GRAPH_SUCCESS`，并编码出 `InputDType=1, IsRope=1` 的 TilingKey；
2. **Kernel TPL 从未为该组合声明 `ARGS_SEL` 实例**（FP32 段全部写死 `IsRope=0`；`IsRope=1` 仅出现在 FP16/BF16）；
3. 因此出现 **`undeclared_runtime`**：host 产出了声明空间之外的 key。

这不是测试框架编解码错误，也不是“随机非法输入”。**根因是算子内部契约不一致：OpDef/Host 允许，Kernel/TPL 不支持。**

---

## 2. 现象与影响

### 2.1 现象

在一轮覆盖搜索（约 1.1 万用例）中：

| 指标 | 数值 | 含义 |
|---|---:|---|
| TPL 声明合法 key 数 | 8705 | `expand_legal_instances` |
| host 实际产出 key 数 | 1031 | `ok=1` 且有 tiling_key |
| **undeclared_runtime** | **33** | host 产出但不在声明空间 |
| 其中 FP32+rope | **32** | 本文问题 |
| 其中 `tiling_key=0` | 1 | 语料噪声（另议） |

32 个 undeclared key **全部**满足：

- `InputDType = 1`（FLOAT32）
- `IsRope = 1`
- `DTemplateNum = 192`
- `IsDNoEqual = 1`
- 其余维度与某个**已声明**实例逐位相同，**仅差 `IsRope` 从 0→1**

声明空间中：

- **0** 条实例满足 `InputDType=1 ∧ IsRope=1`
- `IsRope=1` 的合法实例，`InputDType` 仅出现在 `{2, 3}`（BF16 / FP16）

### 2.2 影响

| 影响面 | 说明 |
|---|---|
| 功能正确性 | Host 返回成功并给出 key，但 kernel 侧无对应模板实例；上板/真正执行时可能出现 **找不到 kernel / 调度失败** |
| API 可信度 | Proto 声明 `query_rope` 支持 float32，用户按此构造输入会被 host 接受，却可能无法真正执行 |
| 覆盖/回归 | 覆盖分析会出现 `undeclared_runtime`，干扰“声明空间闭合”判断 |

---

## 3. 最小复现

### 3.1 输入（已实测）

语料 case：`rope524`

| 字段 | 值 |
|---|---|
| layout | `SBH` |
| dtype（query/key/value/dy） | `FLOAT` / `ge::DT_FLOAT` |
| rope | 开启（同时提供 `query_rope`、`key_rope`） |
| B / S1 / S2 / N2 / G | 1 / 256 / 256 / 1 / 1 |
| D（host 侧语义） | 192（rope 时 host 使用 `ROPE_D_192`） |
| rope D | 64 |

### 3.2 输出（实测）

| 字段 | 值 |
|---|---|
| tiling 返回 | 成功（`ok=1`） |
| `tiling_key` | **`18999562539110416`** |
| `dim_InputDType` / `log_inputDtype` | `1` |
| `dim_IsRope` / `log_hasRope` | `1` |
| `dim_DTemplateNum` | `192` |
| `dim_IsDNoEqual` | `1` |

同 key 在不同 layout 下也可复现（同轮语料中还有 BNSD/TND 等，组合计数见附录 A）。

### 3.3 复现方式建议

任意可调用 arch35 host tiling 的路径即可，例如：

1. ops-transformer host UT 框架（`ExecuteTiling`）直调；
2. 或现有回放驱动：构造 CSV 行，dtype=FLOAT + 非空 `query_rope`/`key_rope`。

**验收判据：**

- Host 返回成功，且 key 解码后 `InputDType=1, IsRope=1`；
- 该 key **不落在** `flash_attention_score_grad_template_tiling_key.h` 的任何 `ASCENDC_TPL_ARGS_SEL` 中。

---

## 4. 根因分析（按链路）

### 4.1 OpDef / Proto：允许 FP32 rope

`flash_attention_score_grad_proto.h`：

```text
query_rope / key_rope: The type support float16, bf16, float32.
OPTIONAL_INPUT(query_rope, TensorType({..., DT_FLOAT16, DT_BF16, DT_FLOAT32}))
OPTIONAL_INPUT(key_rope,   TensorType({..., DT_FLOAT16, DT_BF16, DT_FLOAT32}))
```

→ 从 OpDef 角度看，**FP32 + rope 是合法输入形态**。

### 4.2 Host tiling：不拦截 dtype×rope，直接编码

文件：`op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp`

1. **设置 hasRope**：只要 `query_rope` / `key_rope` 均非空，即置 `hasRope=1`（约 L95），不检查 query dtype。
2. **rope 校验**：仅检查 rope 的 D 是否为 64（约 L359–364），**无 dtype 相关拒绝**。
3. **编码 key**：`GetTilingKey()` 把 `hasRope` 直接打进模板参数（约 L1435–1468）。

因此 host 行为是：**接受 FP32+rope → 编码 `InputDType=1, IsRope=1`**，而不是拒绝。

### 4.3 Kernel TPL：FP32 从未声明 IsRope=1

文件：`op_kernel/arch35/flash_attention_score_grad_template_tiling_key.h`

- 维度注释（约 L57–64）：`InputDType: 1=FLOAT32, 2=BF16, 3=FP16, ...`
- FP32 段（`#if ORIG_DTYPE_QUERY == DT_FLOAT`，约 L1236 起）中所有 `ARGS_SEL` 均为：
  - `InputDType = 1`
  - **`IsRope = 0`**（例如 L1253）
- `IsRope = 1` 的 `ARGS_SEL` 仅出现在 FP16（`InputDType=3`）与 BF16（`InputDType=2`）段。

→ Kernel 侧明确：**不支持 FP32 + rope 模板实例**。

### 4.4 契约对照表

| 层级 | 对 FP32 + rope 的态度 |
|---|---|
| OpDef / Proto | **允许**（rope 支持 float32） |
| Host tiling | **允许并编码 key**（无 dtype×rope 拒绝） |
| Kernel TPL | **不支持**（无对应 ARGS_SEL） |
| 运行结果 | host 成功，但 key **undeclared** |

---

## 5. 这不是什么

为避免误判，明确排除：

| 误解 | 为何不成立 |
|---|---|
| 测试侧编解码算错 key | 33 个 undeclared key 全部 decode→encode roundtrip 成功 |
| 只是覆盖工具的统计噪声 | 同一 key 与 host `OP_LOGI` 的 `hasRope/inputDtype` 一致；UT 交叉校验路径曾验证 key 与维度一致 |
| 输入“完全非法”、host 本不该收到 | OpDef 显式允许 float32 rope；host 也未拒绝 |
| 仅个别脏 case | 同轮语料中至少 174 条 `ok=1` 命中这 32 个 key（多 layout：SBH/BNSD/TND/BSND/BSH） |

---

## 6. 期望修复（请产品/开发确认方向后择一）

### 方案 A（推荐，若产品确认“不支持 FP32+rope”）

在 **host tiling** 增加显式拒绝：

```cpp
// 伪代码
if (fBaseParams.hasRope && fBaseParams.queryType == ge::DT_FLOAT) {
    // 返回 GRAPH_PARAM_INVALID，并给出明确错误信息
}
```

同时建议：

- 对齐 **OpDef / Proto / ACLNN 文档**：`query_rope`/`key_rope` 是否仍声明 `float32`；
- 若文档也不支持，应从 OpDef 去掉 `DT_FLOAT32`，避免用户误用。

**效果：** host 不再产出未声明 key；`undeclared_runtime` 中此类问题消失。

### 方案 B（仅当产品确认“要支持 FP32+rope”）

1. 在 TPL FP32 段补充 `IsRope=1` 的 `ARGS_SEL`；
2. 补齐对应 kernel 实现与 UT；
3. 更新文档与精度/性能基线。

**注意：** 工作量明显大于方案 A，且需确认是否与整体产品规格一致。

### 方案 C（防御性，不能替代 A/B）

调用方/测试侧过滤 `dtype=FLOAT && rope`。这只能减少噪声，**不能修复 API 契约问题**。

---

## 7. 建议验收标准

修复后请至少满足其一：

**若走方案 A：**

1. 最小复现输入（§3）host 返回失败，错误信息明确指出 FP32 不支持 rope；
2. 覆盖搜索中不再出现 `InputDType=1 ∧ IsRope=1` 的成功 key；
3. OpDef/文档与 host 行为一致。

**若走方案 B：**

1. 最小复现 key 落在 TPL `ARGS_SEL` 合法集合内；
2. 对应 kernel 可正确执行并通过 UT；
3. 文档明确 FP32+rope 为支持特性。

---

## 8. 附录

### A. 同轮语料中 FP32+rope 成功用例分布（按 layout）

| (dtype, rope, layout) | 成功用例数 |
|---|---:|
| FLOAT, 1, SBH | 119 |
| FLOAT, 1, TND | 36 |
| FLOAT, 1, BNSD | 12 |
| FLOAT, 1, BSH | 5 |
| FLOAT, 1, BSND | 2 |
| **合计** | **174** |

对应 **32** 个不同 undeclared tiling key。

### B. 示例 undeclared key 列表（节选）

```
18999562539110416
18999562539110544
19039144957710352
19043543004222480
...（共 32 个；另有 1 个 tiling_key=0 为语料噪声，不纳入本问题）
```

完整列表见覆盖快照：`undeclared.txt`（去掉 `0` 后即为本问题集合）。

### C. 关键源码位置

| 文件 | 关注点 |
|---|---|
| `op_graph/flash_attention_score_grad_proto.h` | `query_rope`/`key_rope` 声明含 `DT_FLOAT32` |
| `op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp` | `hasRope` 设置、rope D=64 校验、`GetTilingKey` |
| `op_kernel/arch35/flash_attention_score_grad_template_tiling_key.h` | FP32 段 `IsRope=0`；FP16/BF16 段才有 `IsRope=1` |

### D. 联系人 / 发现方式

本问题由 TilingKey 覆盖闭环流程发现：对 host 真实回放产出的 key 集合与 TPL `ARGS_SEL` 声明集合做差，得到 `undeclared_runtime`，再逐 key 解码定位到 `InputDType=1 ∧ IsRope=1`。

如需提供完整 CSV 行、更多 key 解码表或本地复现脚本，可继续补充。
