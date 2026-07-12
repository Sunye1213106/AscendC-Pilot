# 约束函数 assert 模板

`@solves` 函数在 `return` 前用 `assert` 表达核心约束不变量，引擎在因子值生成阶段自动拦截 `AssertionError`（跳过该组合并统计）。这样可以在约束函数内部完成自校验，无需额外引擎改动。

## assert 模板速查表

| target 后缀 | 必须 assert 的不变量 | 模板 |
|------------|---------------------|------|
| `.shape_list` | 所有 shape 广播兼容 | `assert _broadcast_result(shapes) is not None, f"not broadcast-compatible: {shapes}"` |
| `.shape` | `len(result)` 与预期维度一致 | `assert len(result) == expected_ndim, f"shape len {len(result)} != {expected_ndim}"` |
| `.dtype` | 等值约束时 `result == source` | `assert result == source_dtype, f"dtype {result} != {source_dtype}"` |
| `.length` | 非负且不超上界 | `assert 0 <= result <= upper_bound, f"length {result} out of [0, {upper_bound}]"` |
| `.value` | 在合法范围内 | `assert all(lo <= v <= hi for v in result), f"value out of range: {result}"` |
| `.value`（条件过滤） | 条件过滤后候选集非空 | `assert len(allowed) > 0, f"no allowed values for {sources}: {allowed}"` |
| `.dimensions` | 0 ≤ n ≤ 8 | `assert 0 <= result <= 8, f"dimensions {result} out of [0,8]"` |
| `.value_range` | 格式为 `[min, max]` 且 min ≤ max | `assert result[0] <= result[1], f"invalid range: {result}"` |

assert 消息必须包含实际值，便于定位问题（如 `f"shapes not broadcast-compatible: {shapes}"`）。

## 公共 assert（含 exist 检查的函数）

可选参数的约束函数需要先处理 `exist=False` 的情况：

```python
if not exist:
    return NOT_APPLICABLE
```

当 `exist=False` 时返回 `NOT_APPLICABLE`，引擎不对其做契约校验。

## 广播兼容性工具函数

```python
def _broadcast_result(shape_list):
    if not shape_list:
        return []
    result = list(shape_list[0])
    for s in shape_list[1:]:
        padded_s = [1] * (len(result) - len(s)) + list(s)
        padded_r = [1] * (len(s) - len(result)) + list(result)
        new_result = []
        for a, b in zip(padded_r, padded_s):
            if a == 1:
                new_result.append(b)
            elif b == 1 or a == b:
                new_result.append(a)
            else:
                return None
        result = new_result
    return result
```

## 完整示例（aclnnIndexPutImpl）

### indices.shape_list — 广播兼容性 assert

```python
@solves('indices.shape_list', sources=['selfRef.shape', 'indices.dimensions', 'indices.length'])
def solve_indices_shape_list(selfRef_shape, indices_dimensions, indices_length):
    # ... 生成 shapes ...
    if len(shapes) > 1:
        assert _broadcast_result(shapes) is not None, \
            f"not broadcast-compatible: {shapes}"
    return shapes
```

### values.dimensions — 维度范围 assert

```python
@solves('values.dimensions', sources=['selfRef.shape', 'indices.shape_list', 'indices.length'])
def solve_values_dimensions(selfRef_shape, indices_shape_list, indices_length):
    broadcast_ndim = max(len(s) for s in indices_shape_list) if indices_shape_list else 0
    remaining = max(len(selfRef_shape) - indices_length, 0)
    result = broadcast_ndim + remaining
    assert 0 <= result <= 8, f"values.dimensions={result} out of [0,8]"
    return result
```

## dtype 结果集完备性 assert

**适用场景**：R{n} 标注为"类型可转换"、"推导约束"或"类型可转换(ConvertToTensor)"时，在 `@solves` 函数中增加结果集规模下界 assert，确保工具函数调用后返回了多个候选值（而非被等值替换退化为单值）。

### 模式 2（类型可转换）示例

```python
# 注：OUT_DTYPE_DOMAIN 应从 02_test_factors.yaml 中对应参数的 dtype 域取值
@solves('out.dtype', sources=['self.dtype'])
def solve_out_dtype(self_dtype):
    from utils import can_convert_dtype
    convertible = [d for d in OUT_DTYPE_DOMAIN if can_convert_dtype(self_dtype, d)]
    assert len(convertible) >= 1, f"no convertible dtypes for self.dtype={self_dtype}"
    return Candidates(convertible)
```

### 模式 1.5（类型推导）示例

```python
# 注：TENSOR_DTYPE_DOMAIN 应从 02_test_factors.yaml 中对应参数的 dtype 域取值
@solves('batch2.dtype', sources=['batch1.dtype'])
def solve_batch2_dtype(batch1_dtype):
    from utils import infer_two_dtypes
    valid = [d for d in TENSOR_DTYPE_DOMAIN if infer_two_dtypes(batch1_dtype, d) is not None]
    assert len(valid) >= 1, f"no inferable dtypes for batch1.dtype={batch1_dtype}"
    return Candidates(valid)
```

### 模式 2 + ConvertToTensor 接口7 示例

当 R{n} 链接指向 ConvertToTensor.md 时，使用 `can_convert_to_tensor` 系列：

```python
@solves('value.dtype', sources=['self.dtype'])
def solve_value_dtype(self_dtype):
    from utils import get_convert_to_tensor_source_dtypes
    valid = get_convert_to_tensor_source_dtypes(self_dtype, VALUE_DTYPE_DOMAIN)
    assert len(valid) >= 1, f"no convertible dtypes for self.dtype={self_dtype}"
    return Candidates(valid)
```

### `Candidates([])` 决策表

当 `@solves` 返回空 `Candidates([])` 时，引擎会静默跳过该 source 组合（不生成用例，不记录失败）。下表区分了应使用 `Candidates([])`、`assert` 和 `raise AssertionError` 的场景：

| 场景 | 根因 | 正确做法 | 错误做法 |
|------|------|---------|---------|
| 约束逻辑规定此 source 组合无合法 target 值 | 正常业务规则 | `return Candidates([])` — 引擎跳过，无告警 | `assert len(valid) >= 1` — 引擎抛异常，污染日志 |
| 工具函数返回意外 None（如 `infer_two_dtypes` bug） | 工具函数异常 | `raise AssertionError(f"unexpected failure: {source}")` — 终止执行 | `return Candidates([])` — 静默吞掉合法用例 |
| YAML 域定义与工具函数不匹配 | 配置错误 | `assert len(valid) >= 1, f"mismatch: {source}, domain={DOMAIN}"` — 告警可见 | `return Candidates([])` — 静默吞掉 |

**核心原则**：引擎静默行为是"已知合法的无候选"的正常处理路径，不是 bug 的遮羞布。若 `len(valid) == 0` 是**预期外的**（工具函数应返回非空但实际返回空），禁止静默返回空列表。

**注意**：单次 assert 只能检测"候选数为 0"的明显错误。对于"所有 source 值下 Candidates 列表长度始终为 1"的等值替换错误，需配合 `validate_dtype_coverage.py` 的 `[DTYPE-EQUALITY-SUSPECT]` 检测。
