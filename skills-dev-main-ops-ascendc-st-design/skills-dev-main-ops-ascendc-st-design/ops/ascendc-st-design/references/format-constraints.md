# Format 维度约束参考

本文档定义所有 `aclFormat` 格式对应的**维度数、shape 各轴语义、维度值约束**，用于指导：
- `02_test_factors.yaml` 中 `dimensions` 域值的正确设定
- `04_constraints.py` 中 `format → dimensions` 约束的正确编写
- `04_constraints.py` 中私有格式 shape 值约束的编写

---

## 1. 固定维度格式

以下格式的维度数为固定值，**必须在 `04_constraints.py` 中用查找表映射模式（模式 13）建立 `format → dimensions` 约束**。

| Format | 维度 | shape 各轴语义 | 维度值约束 |
|--------|------|---------------|-----------|
| NCHW | 4 | [N, C, H, W] | 各轴 ≥ 1 |
| NHWC | 4 | [N, H, W, C] | 各轴 ≥ 1 |
| HWCN | 4 | [H, W, C, N] | 各轴 ≥ 1 |
| NC | 2 | [N, C] | 各轴 ≥ 1 |
| NCL | 3 | [N, C, L] | 各轴 ≥ 1 |
| NCW | 3 | [N, C, W] | 各轴 ≥ 1 |
| NLC | 3 | [N, L, C] | 各轴 ≥ 1 |
| NCDHW | 5 | [N, C, D, H, W] | 各轴 ≥ 1 |
| NDHWC | 5 | [N, D, H, W, C] | 各轴 ≥ 1 |
| NC1HWC0 | 5 | [N, C1, H, W, C0] | C0 = 32/sizeof(dtype)；C1 = ceil(C/C0) |
| NC1HWC0_C04 | 5 | [N, C1, H, W, 4] | C0 = 4（固定）；C1 = ceil(C/4) |
| NDC1HWC0 | 6 | [N, D, C1, H, W, C0] | C0 = 32/sizeof(dtype)；C1 = ceil(C/C0) |
| FRACTAL_Z | 4 | [C1×H×W, N1, 16, C0] | N0 = 16；C0 = 32/sizeof(dtype)；C1 = ceil(Cin/C0)；N1 = ceil(Cout/16) |
| FRACTAL_Z_3D | 4 | [D×C1×H×W, N1, 16, C0] | N0 = 16；C0 = 32/sizeof(dtype)；C1 = ceil(Cin/C0)；N1 = ceil(Cout/16) |

> **维度语义缩写**：N=Batch, C=Channel, H=Height, W=Width, D=Depth, L=Length。
> C1=通道分块数, C0=通道微块大小, N1=输出通道分块数, N0=输出通道微块大小（固定 16）。

---

## 2. 可变维度格式

以下格式的维度数不固定，**不需要 `format → dimensions` 约束**。维度范围由算子文档的"维度/长度"列决定，直接在 `02_test_factors.yaml` 中定义 `dimensions` 域值。

| Format | 维度范围 | shape 各轴语义 | 维度值约束 |
|--------|---------|---------------|-----------|
| ND | 0~8 | 0 维: 无轴（标量）；1~8 维: 无固定语义 | 0 维: shape=[]；1~8 维: 各轴 ≥ 1 |
| FRACTAL_NZ | ndim+2 (4~8) | […, ceil(K/c0), ceil(M/16), 16, c0] | 倒数第 2 轴 = 16（固定）；c0 = 32/sizeof(dtype) |
| FRACTAL_NZ_C0_2 | ndim+2 (4~8) | […, ceil(K/2), ceil(M/16), 16, 2] | 倒数第 2 轴 = 16；倒数第 1 轴 = 2 |
| FRACTAL_NZ_C0_4 | ndim+2 (4~8) | […, ceil(K/4), ceil(M/16), 16, 4] | 倒数第 2 轴 = 16；倒数第 1 轴 = 4 |
| FRACTAL_NZ_C0_8 | ndim+2 (4~8) | […, ceil(K/8), ceil(M/16), 16, 8] | 倒数第 2 轴 = 16；倒数第 1 轴 = 8 |
| FRACTAL_NZ_C0_16 | ndim+2 (4~8) | […, ceil(K/16), ceil(M/16), 16, 16] | 倒数第 2 轴 = 16；倒数第 1 轴 = 16 |
| FRACTAL_NZ_C0_32 | ndim+2 (4~8) | […, ceil(K/32), ceil(M/16), 16, 32] | 倒数第 2 轴 = 16；倒数第 1 轴 = 32 |

> **FRACTAL_NZ 转换规则**：ND `[..., M, K]` → NZ `[..., ceil(K/c0), ceil(M/16), 16, c0]`。
> 前导轴保持不变，仅最后 2 维被分块为 4 维 NZ 结构。
> NZ 维度数 = ND 维度数 + 2，合法范围 4~8。

---

## 3. C0 计算规则

C0 = 32（字节）/ sizeof(dtype)，计算结果为元素个数。

| dtype | sizeof (字节) | C0 |
|-------|--------------|-----|
| int8 / uint8 / float8_e4m3fn / hifloat8 / int4 | 1 | 32 |
| float16 / bfloat16 | 2 | 16 |
| float32 / int32 / uint32 | 4 | 8 |
| float64 / int64 | 8 | 4 |
| float4_e2m1 / hifloat4 | 0.5 | 64 |
| hifloat4_scale | 0.5 | 64 |

---

## 4. 约束编写指导

### 4.1 固定维度格式：必须写 format→dimensions 约束

当算子参数使用固定维度格式（§1 中的格式）时，**必须**在 `04_constraints.py` 中用查找表映射模式建立约束。否则引擎会将 `format` 和 `dimensions` 视为独立因子，产生 NCL+4D 等非法组合。

**正确写法**：

```python
# 来源: references/format-constraints.md §1
_FORMAT_DIMS = {
    'NCL': 3,
    'NCHW': 4,
}

@solves('self.dimensions', sources=['self.format'])
def solve_self_dimensions(self_format):
    dims = _FORMAT_DIMS.get(self_format)
    assert dims is not None, f"unknown format: {self_format}"
    return dims
```

**常见错误**：在 `02_test_factors.yaml` 中同时定义 `self.format: [NCL, NCHW]` 和 `self.dimensions: [3, 4]`，但不写 `@solves` 约束 → 引擎独立采样 → 产生 NCL+4D 非法组合。

**YAML 正确写法**：当 `format → dimensions` 约束存在时，`dimensions` 域值仅作为 ND 等可变维度格式的回退域，或可省略（由 `@solves` 完全决定）。若同时存在固定和可变维度格式，`dimensions` 域值应覆盖可变格式允许的范围：

```yaml
self:
  type: aclTensor
  io_type: input
  factors:
    self.format: [NCHW, NCL]
    self.dimensions: [3, 4]
    # dimensions 域值须覆盖 NCL(3) 和 NCHW(4)，
    # 实际维度由 04_constraints.py 中 @solves 按 format 推导
```

### 4.2 可变维度格式：dimensions 由算子文档决定

ND 等可变维度格式的维度范围由算子文档"维度/长度"列决定。此时**不需要** `format → dimensions` 约束，直接在 YAML 中定义 `dimensions` 域值：

```yaml
self:
  type: aclTensor
  io_type: input
  factors:
    self.format: [ND]
    self.dimensions: [1, 2, 3, 4, 5, 6, 7, 8]
```

### 4.3 私有格式的 shape 值约束

NC1HWC0、FRACTAL_Z、FRACTAL_NZ 等私有格式的 shape 值有 C0 对齐等约束（见 §1 和 §2 中各格式的"维度值约束"列）。当算子使用这些格式时，需在 `@solves` 中实现轴值约束。

**编写模式**：先生成逻辑形状（采样空间大），再转换为物理形状（满足格式约束）。`sources` 只需 `format` 和 `dtype`，不需要 `dimensions`（已被 format→dimensions 约束推导）。

```python
from solver import solves
from utils import generate_random_shape
import math

# C0 计算规则 (来源: format-constraints.md §3)
_DTYPE_C0 = {'float16': 16, 'bfloat16': 16, 'float32': 8, 'int32': 8, 'int8': 32}

# 逻辑 shape [N, C, H, W] → NC1HWC0 物理 shape [N, C1, H, W, C0]
def _to_nc1hwc0(logical_shape, dtype):
    n, c, h, w = logical_shape
    c0 = _DTYPE_C0.get(dtype, 16)
    c1 = math.ceil(c / c0)
    return [n, c1, h, w, c0]

# 逻辑 shape [N, C, D, H, W] → NDC1HWC0 物理 shape [N, D, C1, H, W, C0]
def _to_ndc1hwc0(logical_shape, dtype):
    n, c, d, h, w = logical_shape
    c0 = _DTYPE_C0.get(dtype, 16)
    c1 = math.ceil(c / c0)
    return [n, d, c1, h, w, c0]

# 逻辑 shape [Cout, Cin, H, W] → FRACTAL_Z 物理 shape [C1*H*W, N1, 16, C0]
def _to_fractal_z(logical_shape, dtype):
    n_out, c_in, h, w = logical_shape
    c0 = _DTYPE_C0.get(dtype, 16)
    c1 = math.ceil(c_in / c0)
    n1 = math.ceil(n_out / 16)
    return [c1 * h * w, n1, 16, c0]

# 逻辑 shape [..., M, K] → FRACTAL_NZ 物理 shape [..., ceil(K/c0), ceil(M/16), 16, c0]
def _to_fractal_nz(logical_shape, dtype):
    m, k = logical_shape[-2], logical_shape[-1]
    c0 = _DTYPE_C0.get(dtype, 16)
    return logical_shape[:-2] + [math.ceil(k / c0), math.ceil(m / 16), 16, c0]

@solves('self.shape', sources=['self.format', 'self.dtype'])
def solve_self_shape(fmt, dtype):
    if fmt == 'NC1HWC0':
        return _to_nc1hwc0(generate_random_shape(4), dtype)
    if fmt == 'NC1HWC0_C04':
        n, c, h, w = generate_random_shape(4)
        return [n, math.ceil(c / 4), h, w, 4]
    if fmt == 'NDC1HWC0':
        return _to_ndc1hwc0(generate_random_shape(5), dtype)
    if fmt == 'FRACTAL_Z':
        return _to_fractal_z(generate_random_shape(4), dtype)
    if fmt == 'FRACTAL_Z_3D':
        n_out, c_in, d, h, w = generate_random_shape(5)
        c0 = _DTYPE_C0.get(dtype, 16)
        c1 = math.ceil(c_in / c0)
        n1 = math.ceil(n_out / 16)
        return [d * c1 * h * w, n1, 16, c0]
    if fmt == 'FRACTAL_NZ' or fmt.startswith('FRACTAL_NZ_C0_'):
        c0_map = {'FRACTAL_NZ_C0_2': 2, 'FRACTAL_NZ_C0_4': 4,
                   'FRACTAL_NZ_C0_8': 8, 'FRACTAL_NZ_C0_16': 16,
                   'FRACTAL_NZ_C0_32': 32}
        c0 = c0_map.get(fmt, _DTYPE_C0.get(dtype, 16))
        logical = generate_random_shape(random.randint(2, 6))
        m, k = logical[-2], logical[-1]
        return logical[:-2] + [math.ceil(k / c0), math.ceil(m / 16), 16, c0]
    return generate_random_shape(5)
```

### 4.4 多参数 format 一致性

当多个参数的 format 必须一致时（常见于输入输出张量），使用等值约束：

```python
@solves('out.format', sources=['self.format'])
def solve_out_format(self_format):
    return self_format
```

此时输出参数的 `dimensions` 也应通过 format→dimensions 约束推导，确保 out 的维度数与 format 匹配。
