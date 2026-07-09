#!/usr/bin/env python3
#
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
#
"""
公共工具函数模块

功能：
1. dtype字符串映射与规范化
2. dtype可转换性计算
3. dtype可推导组合计算
4. dtype推导计算
5. Shape broadcast关系计算
6. Shape broadcast结果计算
7. 随机Shape生成（基于对数分段）
"""

from typing import List, Set, Optional, Union, Tuple
import itertools
import random
import math


def make_hashable(v):
    if isinstance(v, (str, bool, int, float)):
        return v
    if isinstance(v, (list, tuple)):
        return tuple(make_hashable(x) for x in v)
    if isinstance(v, set):
        return frozenset(make_hashable(x) for x in v)
    return v


# ==================== Precision 配置定义 ====================

PRECISION_CONFIG: dict = {
    "float32": {"precision_mode": 1, "precision_tolerance": ((0.0001, 0.0001, 0.1, 0.0001, 0.0001),)},
    "float16": {"precision_mode": 1, "precision_tolerance": ((0.001, 0.001, 0.1, 0.001, 0.001),)},
    "float64": {"precision_mode": 1, "precision_tolerance": ((0.0001, 0.0001, 0.1, 0.001, 0.0001),)},
    "bfloat16": {"precision_mode": 1, "precision_tolerance": ((0.005, 0.005, 0.1, 0.005, 0.005),)},
    "float4_e2m1": {"precision_mode": 7, "precision_tolerance": ((0, 0, 0, 0, 0),)},
    "float4_e1m2": {"precision_mode": 7, "precision_tolerance": ((0, 0, 0, 0, 0),)},
    "float8_e4m3fn": {"precision_mode": 10, "precision_tolerance": ((0, 0.001, 1, 0, 0),)},
    "float8_e5m2": {"precision_mode": 10, "precision_tolerance": ((0, 0.001, 1, 0, 0),)},
    "float8_e8m0": {"precision_mode": 10, "precision_tolerance": ((0, 0.001, 1, 0, 0),)},
    "hifloat8": {"precision_mode": 10, "precision_tolerance": ((0, 0.001, 1, 0, 0),)},
    "hifloat4": {"precision_mode": 7, "precision_tolerance": ((0, 0, 0, 0, 0),)},
    "hifloat4_scale": {"precision_mode": 7, "precision_tolerance": ((0, 0, 0, 0, 0),)},
    "int8": {"precision_mode": 7, "precision_tolerance": ((0, 0, 0, 0, 0),)},
    "int16": {"precision_mode": 7, "precision_tolerance": ((0, 0, 0, 0, 0),)},
    "int32": {"precision_mode": 7, "precision_tolerance": ((0, 0, 0, 0, 0),)},
    "int64": {"precision_mode": 7, "precision_tolerance": ((0, 0, 0, 0, 0),)},
    "uint8": {"precision_mode": 7, "precision_tolerance": ((0, 0, 0, 0, 0),)},
    "uint16": {"precision_mode": 7, "precision_tolerance": ((0, 0, 0, 0, 0),)},
    "uint32": {"precision_mode": 7, "precision_tolerance": ((0, 0, 0, 0, 0),)},
    "uint64": {"precision_mode": 7, "precision_tolerance": ((0, 0, 0, 0, 0),)},
    "bool": {"precision_mode": 7, "precision_tolerance": ((0, 0, 0, 0, 0),)},
    "complex32": {"precision_mode": 1, "precision_tolerance": ((0.001, 0.001, 0.1, 0.001, 0.001),)},
    "complex64": {"precision_mode": 8, "precision_tolerance": ((0.0001, 0.0001, 0.1, 0.0001, 0.0001),)},
    "complex128": {"precision_mode": 8, "precision_tolerance": ((0.0001, 0.0001, 0.1, 0.0001, 0.0001),)},
}

# ==================== 默认 value_range 定义 ====================

DEFAULT_VALUE_RANGES = {
    "float16": [
        [0, 0.001], [0.001, 0.01], [0.01, 1], [1, 2], [2, 10],
        [10, 1000], [-0.001, 0], [-0.01, -0.001], [-1, -0.01],
        [-2, -1], [-10, -2], [-1000, -10], [-1, 1], [-0.01, 0.01],
        [-100, 100], [0, 0], [-65504.0, 65504.0],
        [-0.0078125, 0.0078125], [65504.0, 65504.0],
        [-65504.0, -65504.0], [-6.103515625e-05, -6.103515625e-05],
        [6.103515625e-05, 6.103515625e-05],
        ["inf", "inf"], ["-inf", "-inf"], ["nan", "nan"],
    ],
    "float32": [
        [0, 0.001], [0.001, 0.01], [0.01, 1], [1, 2], [2, 10],
        [10, 1000], [-0.001, 0], [-0.01, -0.001], [-1, -0.01],
        [-2, -1], [-10, -2], [-1000, -10], [-1, 1], [-0.01, 0.01],
        [-100, 100], [0, 0], [-3.4028235e38, 3.4028235e38],
        [-0.000030517578125, 0.000030517578125],
        [3.4028235e38, 3.4028235e38],
        [-3.4028235e38, -3.4028235e38],
        [-1.1754943508e-38, -1.1754943508e-38],
        [1.1754943508e-38, 1.1754943508e-38],
        ["inf", "inf"], ["-inf", "-inf"], ["nan", "nan"],
    ],
    "float64": [
        [0, 0.001], [0.001, 0.01], [0.01, 1], [1, 2], [2, 10],
        [10, 1000], [-0.001, 0], [-0.01, -0.001], [-1, -0.01],
        [-2, -1], [-10, -2], [-1000, -10], [-1, 1], [-0.01, 0.01],
        [-100, 100], [0, 0], [-3.4028235e38, 3.4028235e38],
        [3.4028235e38, 3.4028235e38],
        [-3.4028235e38, -3.4028235e38],
        [-0.000030517578125, 0.000030517578125],
        [-1.1754943508e-38, -1.1754943508e-38],
        [1.1754943508e-38, 1.1754943508e-38],
        [1.7976931348623157e308, 1.7976931348623157e308],
        [-1.7976931348623157e308, -1.7976931348623157e308],
        [-2.2250738585072014e-308, -2.2250738585072014e-308],
        [2.2250738585072014e-308, 2.2250738585072014e-308],
        ["inf", "inf"], ["-inf", "-inf"], ["nan", "nan"],
    ],
    "bfloat16": [
        [0, 0.001], [0.001, 0.01], [0.01, 1], [-1, 1], [1, 2],
        [2, 10], [10, 1000], [-0.001, 0], [-0.01, -0.001],
        [-1, -0.01], [-2, -1], [-10, -2], [-1000, -10], [-1, 1],
        [-0.01, 0.01], [-100, 100], [0, 0], [-3.38e38, 3.38e38],
        [-0.000030517578125, 0.000030517578125],
        [3.3895313892515355e38, 3.3895313892515355e38],
        [-3.3895313892515355e38, -3.3895313892515355e38],
        [-1.1754943508e-38, -1.1754943508e-38],
        [1.1754943508e-38, 1.1754943508e-38],
        ["inf", "inf"], ["-inf", "-inf"], ["nan", "nan"],
    ],
    "hf32": [
        [0, 0.001], [0.001, 0.01], [0.01, 1], [1, 2], [2, 10],
        [10, 1000], [-0.001, 0], [-0.01, -0.001], [-1, -0.01],
        [-2, -1], [-10, -2], [-1000, -10], [-1, 1], [-0.01, 0.01],
        [-100, 100], [0, 0], [-3.4028235e38, 3.4028235e38],
        [3.4028235e38, 3.4028235e38],
        [-3.4028235e38, -3.4028235e38],
        [-1.1754943508e-38, -1.1754943508e-38],
        [1.1754943508e-38, 1.1754943508e-38],
    ],
    "float4_e1m2": [
        [0, 0], [-0, -0], [0.25, 0.25], [-0.25, -0.25],
        [0.5, 0.5], [-0.5, -0.5], [0.75, 0.75], [-0.75, -0.75],
        [1, 1], [-1, -1], [1.25, 1.25], [-1.25, -1.25],
        [1.5, 1.5], [-1.5, -1.5], [1.75, 1.75], [-1.75, -1.75],
    ],
    "float4_e2m1": [
        [0.5, 0.5], [-0.5, -0.5], [1, 1], [-1, -1],
        [1.5, 1.5], [-1.5, -1.5], [2, 2], [-2, -2],
        [3, 3], [-3, -3], [4, 4], [-4, -4], [6, 6], [-6, -6],
    ],
    "float8_e4m3fn": [
        [-448, 448], [2e-6, 1], [-1, -2e-6],
        [2e-9, 1.75e-06], [-1.75e-06, 2e-9], [-0, 0],
    ],
    "float8_e5m2": [
        [-57344, 57344], [2e-14, 1], [-1, -2e-14],
        [2e-16, 1.5e-14], [-1.5e-14, 2e-16], [-0, 0],
    ],
    "float8_e8m0": [
        [-127, 127], [-10, 10], [-64, 64],
        [-100, 100], [0, 10], [-10, 0],
    ],
    "hifloat8": [
        [256, 32768], [-32768, -256],
        [0.000030517578125, 0.0078125],
        [-0.0078125, -0.000030517578125],
        [16, 256], [-256, 16], [-256, -16],
        [0.0078125, 0.125], [-0.125, -0.0078125],
        [4, 16], [-16, -4], [0.125, 0.5], [-0.5, -0.125],
        [2, 4], [-4, -2], [0.5, 1], [-1, -0.5],
        [1, 2], [-2, -1],
        [0.0000002384185791015625, 0.000030517578125], [-0, 0],
    ],
    "hifloat4": [
        [0.5, 0.5], [-0.5, -0.5], [1, 1], [-1, -1],
        [1.5, 1.5], [-1.5, -1.5], [2, 2], [-2, -2],
        [3, 3], [-3, -3], [4, 4], [-4, -4], [6, 6], [-6, -6],
        [0.0000002384185791015625, 0.0078125],
        [-0.0078125, -0.0000002384185791015625],
        [0.0078125, 0.125], [-0.125, -0.0078125],
        [0.125, 0.5], [-0.5, -0.125],
        [-0, 0],
    ],
    "hifloat4_scale": [
        [0.0000002384185791015625, 0.0078125],
        [-0.0078125, -0.0000002384185791015625],
        [0.0078125, 0.125], [-0.125, -0.0078125],
        [0.125, 0.5], [-0.5, -0.125],
        [0.5, 1], [-1, -0.5],
        [1, 2], [-2, -1],
        [2, 4], [-4, -2],
        [4, 16], [-16, -4],
        [16, 256], [-256, -16],
        [-0, 0],
    ],
    "complex32": [
        [0, 0.001], [0.001, 0.01], [0.01, 1], [1, 2], [2, 10],
        [10, 1000], [-0.001, 0], [-0.01, -0.001], [-1, -0.01],
        [-2, -1], [-10, -2], [-1000, -10], [-1, 1],
        [-0.01, 0.01], [-100, 100], [0, 0],
        [-3.4028235e38, 3.4028235e38],
        [3.4028235e38, 3.4028235e38],
        [-3.4028235e38, -3.4028235e38],
        [-1.1754943508e-38, -1.1754943508e-38],
        [1.1754943508e-38, 1.1754943508e-38],
    ],
    "complex64": [
        [0, 0.001], [0.001, 0.01], [0.01, 1], [1, 2], [2, 10],
        [10, 1000], [-0.001, 0], [-0.01, -0.001], [-1, -0.01],
        [-2, -1], [-10, -2], [-1000, -10], [-1, 1],
        [-0.01, 0.01], [-100, 100], [0, 0],
        [-3.4028235e38, 3.4028235e38],
        [-0.000030517578125, 0.000030517578125],
        [3.4028235e38, 3.4028235e38],
        [-3.4028235e38, -3.4028235e38],
        [-1.1754943508e-38, -1.1754943508e-38],
        [1.1754943508e-38, 1.1754943508e-38],
    ],
    "complex128": [
        [0, 0.001], [0.001, 0.01], [0.01, 1], [1, 2], [2, 10],
        [10, 1000], [-0.001, 0], [-0.01, -0.001], [-1, -0.01],
        [-2, -1], [-10, -2], [-1000, -10], [-1, 1],
        [-0.01, 0.01], [-100, 100], [0, 0],
        [-3.4028235e38, 3.4028235e38],
        [3.4028235e38, 3.4028235e38],
        [-3.4028235e38, -3.4028235e38],
        [-0.000030517578125, 0.000030517578125],
        [-1.1754943508e-38, -1.1754943508e-38],
        [1.1754943508e-38, 1.1754943508e-38],
        [1.7976931348623157e308, 1.7976931348623157e308],
        [-1.7976931348623157e308, -1.7976931348623157e308],
        [-2.2250738585072014e-308, -2.2250738585072014e-308],
        [2.2250738585072014e-308, 2.2250738585072014e-308],
    ],
    "int4": [
        [0, 0], [-1, 0], [0, 1], [-1, 1], [-8, 7], [-8, -8],
        [7, 7], [-8, -1], [1, 7], [-4, 4], [-2, -1], [1, 2],
    ],
    "int8": [
        [0, 1], [1, 2], [2, 10], [-1, 0], [-2, -1], [-10, -2],
        [-1, 1], [-100, 100], [-10, 10], [0, 0],
        [-128, 127], [-128, -128], [127, 127],
    ],
    "int16": [
        [0, 1], [1, 2], [2, 10], [10, 1000], [-1, 0], [-2, -1],
        [-10, -2], [-1000, -10], [-1, 1], [-100, 100], [0, 0],
        [-32768, 32767], [-32768, -32768], [32767, 32767],
    ],
    "int32": [
        [0, 1], [1, 2], [2, 10], [10, 1000], [-1, 0], [-2, -1],
        [-10, -2], [-1000, -10], [-1, 1], [-100, 100], [0, 0],
        [-2147483648, 2147483647],
        [-2147483648, -2147483648],
        [2147483647, 2147483647],
    ],
    "int64": [
        [0, 1], [1, 2], [2, 10], [10, 1000], [-1, 0], [-2, -1],
        [-10, -2], [-1000, -10], [-1, 1], [-100, 100], [0, 0],
        [-9223372036854775808, 9223372036854775807],
        [-9223372036854775808, -9223372036854775808],
        [9223372036854775807, 9223372036854775807],
    ],
    "uint1": [[0, 1]],
    "uint8": [
        [0, 1], [1, 2], [2, 10], [0, 100], [0, 10],
        [0, 255], [0, 0], [255, 255],
    ],
    "uint16": [
        [0, 1], [1, 2], [2, 10], [10, 1000], [0, 100],
        [0, 65535], [0, 0], [65535, 65535],
    ],
    "uint32": [
        [0, 1], [1, 2], [2, 10], [10, 1000], [0, 100],
        [0, 4294967295], [0, 0], [4294967295, 4294967295],
    ],
    "uint64": [
        [0, 1], [1, 2], [2, 10], [10, 1000], [0, 100],
        [0, 18446744073709551615],
        [0, 0], [18446744073709551615, 18446744073709551615],
    ],
    "qint8": [[-128, 127]],
    "qint16": [
        [-1, 1], [1, 2], [2, 10], [10, 1000], [-2, -1],
        [-10, -2], [-1000, -10], [-1, 1], [0, 1], [1, 2],
        [2, 10], [10, 1000], [0, 100], [0, 65535],
        [0, 0], [65535, 65535],
        [-32768, 32767], [-32768, -32768], [32767, 32767],
    ],
    "qint32": [[-2147483648, 2147483647]],
    "quint8": [
        [0, 1], [1, 2], [2, 10], [0, 100], [0, 10],
        [0, 255], [0, 0], [255, 255],
    ],
    "quint16": [
        [0, 1], [1, 2], [2, 10], [10, 1000], [0, 100],
        [0, 65535], [0, 0], [65535, 65535],
    ],
    "bool": [[0, 1], [0, 0], [1, 1]],
    "char": [
        [0, 1], [1, 2], [2, 10], [-1, 0], [-2, -1], [-10, -2],
        [-1, 1], [-100, 100], [-10, 10], [0, 0],
        [-128, 127], [-128, -128], [127, 127],
    ],
    "string": [],
}


def param_excludes_infnan(param_data) -> bool:
    """Decide whether to exclude inf/nan from the default value range for a param.

    标量默认剔除 inf/nan（避免 nan 物化进 .value 组合因子后被 _clean_nan_cases
    丢弃）；张量/数组默认包含 inf/nan（保持现有行为，与
    IMPROVEMENT_INFNAN_SUPPORT.md 的设计一致）。

    - 标量：support_infnan 未设/false → 剔除；true → 包含（opt-in）
    - 张量/数组：support_infnan false → 剔除；未设/true → 包含
    """
    if not isinstance(param_data, dict):
        return False
    param_type = param_data.get('type', '')
    _nonscalar = ('aclTensor', 'aclTensorList',
                  'aclIntArray', 'aclFloatArray', 'aclBoolArray', 'aclScalarList',
                  'bool', 'string')
    if param_type not in _nonscalar:
        return param_data.get('support_infnan') is not True
    return param_data.get('support_infnan') is False


def get_default_value_range(dtype: str, exclude_infnan: bool = False) -> List[List]:
    normalized = normalize_dtype(dtype)
    if normalized is None:
        return [[0, 100]]
    ranges = DEFAULT_VALUE_RANGES.get(normalized, [[0, 100]])
    if exclude_infnan:
        ranges = [r for r in ranges
                  if not (isinstance(r, (list, tuple)) and
                          ('inf' in str(r).lower() or 'nan' in str(r).lower()))]
    return ranges


def get_precision_mode_and_tolerance(
    output_dtypes: List[str],
    is_copy_op: bool = False
) -> Tuple[Union[int, List[int]], Tuple]:
    """
    根据输出 dtype 生成 precision_mode 和 precision_tolerance
    
    Args:
        output_dtypes: 输出张量的数据类型列表（如 ["float32", "float16"]）
        is_copy_op: 是否为搬运类算子
    
    Returns:
        Tuple[Union[int, List[int]], Tuple]: 
            - precision_mode: 可以是 int 或 list
              - 单输出：int（如 1）
              - 多输出：list（如 [1, 7]）
            - precision_tolerance: 元组形式
              - 单输出：((0.0001, 0.0001, 0.1, 0.0001, 0.0001),)
              - 多输出：((0.0001, 0.0001, 0.1, 0.0001, 0.0001), (0, 0, 0, 0, 0),)
    
    Examples:
        >>> get_precision_mode_and_tolerance(["float32"], False)
        (1, ((0.0001, 0.0001, 0.1, 0.0001, 0.0001),))
        
        >>> get_precision_mode_and_tolerance(["float32", "int32"], False)
        ([1, 7], ((0.0001, 0.0001, 0.1, 0.0001, 0.0001), (0, 0, 0, 0, 0),))
        
        >>> get_precision_mode_and_tolerance(["float32"], True)
        (7, ((0, 0, 0, 0, 0),))
        
        >>> get_precision_mode_and_tolerance(["float32", "int32"], True)
        (7, ((0, 0, 0, 0, 0),))
    """
    if is_copy_op:
        # 搬运类算子：所有输出统一使用 precision_mode=7
        return (7, ((0, 0, 0, 0, 0),))
    
    if not output_dtypes:
        # 默认值
        return (1, ((0.0001, 0.0001, 0.1, 0.0001, 0.0001),))
    
    # 根据 dtype 配置生成 precision_mode 和 precision_tolerance
    modes = []
    tolerances = []
    
    for dtype in output_dtypes:
        # 规范化 dtype
        normalized_dtype = normalize_dtype(dtype)
        if normalized_dtype is None:
            normalized_dtype = dtype
        
        # 查找配置
        config = PRECISION_CONFIG.get(normalized_dtype)
        if config is None:
            # 如果找不到配置，使用默认值（float32）
            config = PRECISION_CONFIG.get("float32")
        
        modes.append(config["precision_mode"])
        tolerances.append(config["precision_tolerance"][0])
    
    # 根据输出数量决定返回格式
    if len(output_dtypes) == 1:
        # 单输出：返回 int
        return (modes[0], (tolerances[0],))
    else:
        # 多输出：返回 list
        return (modes, tuple(tolerances))


def format_precision_output(
    precision_mode: Union[int, List[int]],
    precision_tolerance: Tuple
) -> Tuple[str, str]:
    """
    格式化 precision_mode 和 precision_tolerance 为字符串形式
    
    Args:
        precision_mode: precision_mode 值（int 或 list）
        precision_tolerance: precision_tolerance 值（tuple）
    
    Returns:
        Tuple[str, str]: 格式化后的字符串
            - precision_mode_str: 如 "1" 或 "[1, 7]"
            - precision_tolerance_str: 如 "((),)" 或 "((0.0001,0.0001,0.1,0.0001,0.0001),)"
    
    Examples:
        >>> format_precision_output(1, ((0.0001, 0.0001, 0.1, 0.0001, 0.0001),))
        ('1', '((0.0001,0.0001,0.1,0.0001,0.0001),)')
        
        >>> format_precision_output([1, 7], ((0.0001, 0.0001, 0.1, 0.0001, 0.0001), (0, 0, 0, 0, 0)))
        ('[1,7]', '((0.0001,0.0001,0.1,0.0001,0.0001),(0,0,0,0,0),)')
    """
    # 格式化 precision_mode
    if isinstance(precision_mode, list):
        precision_mode_str = str(precision_mode).replace(" ", "")
    else:
        precision_mode_str = str(precision_mode)
    
    # 格式化 precision_tolerance
    tolerance_parts = []
    for tolerance_tuple in precision_tolerance:
        tolerance_str = "(" + ",".join(str(v) for v in tolerance_tuple) + ")"
        tolerance_parts.append(tolerance_str)
    
    precision_tolerance_str = "(" + ",".join(tolerance_parts) + ",)"
    
    return (precision_mode_str, precision_tolerance_str)


# ==================== dtype 映射定义 ====================

# dtype 标准名称到各种别名的映射
DTYPE_ALIASES: dict = {
    "float32": ["float32", "float", "acl_float", "FLOAT", "FLOAT32", "f32"],
    "float16": ["float16", "acl_float16", "FLOAT16", "FP16", "fp16", "half", "f16"],
    "bfloat16": ["bfloat16", "acl_bf16", "BF16", "bf16", "ACL_BF16"],
    "float64": ["float64", "double", "acl_double", "DOUBLE", "FLOAT64", "f64"],
    "int8": ["int8", "acl_int8", "INT8", "i8", "s8"],
    "uint8": ["uint8", "acl_uint8", "UINT8", "u8"],
    "int16": ["int16", "acl_int16", "INT16", "i16", "s16"],
    "uint16": ["uint16", "acl_uint16", "UINT16", "u16"],
    "int32": ["int32", "acl_int32", "INT32", "i32", "s32"],
    "uint32": ["uint32", "acl_uint32", "UINT32", "u32"],
    "int64": ["int64", "acl_int64", "INT64", "i64", "s64"],
    "uint64": ["uint64", "acl_uint64", "UINT64", "u64"],
    "bool": ["bool", "acl_bool", "BOOL", "boolean"],
    "complex32": ["complex32", "acl_complex32", "COMPLEX32", "c32"],
    "complex64": ["complex64", "acl_complex64", "COMPLEX64", "c64"],
    "complex128": ["complex128", "acl_complex128", "COMPLEX128", "c128"],
    "hifloat8": ["hifloat8", "HIFLOAT8", "hi8"],
    "hifloat4": ["hifloat4", "HIFLOAT4", "hi4"],
    "hifloat4_scale": ["hifloat4_scale", "HIFLOAT4_SCALE", "hi4_scale", "hifloat4scale"],
    "float8_e4m3fn": ["float8_e4m3fn", "FLOAT8_E4M3FN", "fp8_e4m3fn", "e4m3"],
    "float8_e5m2": ["float8_e5m2", "FLOAT8_E5M2", "fp8_e5m2", "e5m2"],
    "float8_e8m0": ["float8_e8m0", "FLOAT8_E8M0", "fp8_e8m0", "e8m0"],
    "float4_e2m1": ["float4_e2m1", "FLOAT4_E2M1", "fp4_e2m1"],
    "float4_e1m2": ["float4_e1m2", "FLOAT4_E1M2", "fp4_e1m2"],
    "int4": ["int4", "INT4", "i4", "s4"],
    "uint1": ["uint1", "UINT1", "u1"],
    "float6_e3m2": ["float6_e3m2", "FLOAT6_E3M2", "fp6_e3m2"],
    "float6_e2m3": ["float6_e2m3", "FLOAT6_E2M3", "fp6_e2m3"],
}

# 反向映射：别名 -> 标准名称
_ALIAS_TO_STANDARD: dict = {}
_STANDARD_DTYPES: set = set()

for standard, aliases in DTYPE_ALIASES.items():
    _STANDARD_DTYPES.add(standard)
    for alias in aliases:
        _ALIAS_TO_STANDARD[alias.lower()] = standard
        _ALIAS_TO_STANDARD[alias] = standard


def normalize_dtype(dtype_str: Optional[Union[str, int]]) -> Optional[str]:
    """
    将dtype字符串映射为标准名称

    Args:
        dtype_str: dtype字符串，可以是各种格式
            - "FLOAT" / "float" / "FLOAT32" / "float32" -> "float32"
            - "FLOAT16" / "float16" / "FP16" -> "float16"
            - "INT32" / "int32" -> "int32"
            ...

    Returns:
        标准化的dtype名称，如果无法识别则返回 None

    Examples:
        >>> normalize_dtype("FLOAT")
        'float32'
        >>> normalize_dtype("float16")
        'float16'
        >>> normalize_dtype("INT32")
        'int32'
        >>> normalize_dtype("unknown")
        None
    """
    if dtype_str is None:
        return None

    if isinstance(dtype_str, int):
        return None

    dtype_str = str(dtype_str).strip()

    result = _ALIAS_TO_STANDARD.get(dtype_str)
    if result:
        return result

    return _ALIAS_TO_STANDARD.get(dtype_str.lower())


def normalize_dtype_list(dtype_list: List[str]) -> List[str]:
    """
    批量规范化dtype列表

    Args:
        dtype_list: dtype字符串列表

    Returns:
        规范化后的dtype列表（过滤掉无法识别的）

    Examples:
        >>> normalize_dtype_list(["FLOAT", "FLOAT16", "INT32"])
        ['float32', 'float16', 'int32']
    """
    result: List[str] = []
    for dtype_str in dtype_list:
        normalized = normalize_dtype(dtype_str)
        if normalized is not None:
            result.append(normalized)
    return result


# ==================== dtype 类型分类 ====================

# 整数类型集合（标准名称）
INTEGER_DTYPES: Set[str] = {
    "int8",
    "uint8",
    "int16",
    "uint16",
    "int32",
    "uint32",
    "int64",
    "uint64",
}

# 浮点类型集合（标准名称）
FLOAT_DTYPES: Set[str] = {"float16", "float32", "float64", "bfloat16", "hifloat4", "hifloat4_scale"}

# 复数类型集合（标准名称）
COMPLEX_DTYPES: Set[str] = {"complex32", "complex64", "complex128"}

# BOOL类型
BOOL_DTYPE: str = "bool"


def get_dtype_category(dtype: Optional[str]) -> Optional[str]:
    """
    获取dtype的类型分类

    Args:
        dtype: dtype字符串（可以是各种格式，会自动规范化）

    Returns:
        类型分类: "integer", "float", "complex", "bool" 或 None
    """
    if dtype is None:
        return None

    normalized = normalize_dtype(dtype)
    if normalized is None:
        return None

    if normalized in INTEGER_DTYPES:
        return "integer"
    elif normalized in FLOAT_DTYPES:
        return "float"
    elif normalized in COMPLEX_DTYPES:
        return "complex"
    elif normalized == BOOL_DTYPE:
        return "bool"

    return None


# ==================== dtype 可转换性计算 ====================


def get_convertible_source_dtypes(
    target_dtype: str, source_dtypes: List[str]
) -> List[str]:
    """
    根据 dtype 可转换规则，从原始 dtype 列表中筛选出可转换为目标 dtype 的列表

    可转换规则（参考：互转换关系.md）：
    1. 整数类型间可以转换，也支持往浮点、复数类型转换
    2. 浮点类型间可以转换，也支持往复数类型转换
    3. 复数类型间可以转换
    4. BOOL支持往整数、浮点、复数类型转换
    5. 其他场景不支持转换

    Args:
        target_dtype: 目标 dtype（需要转换到的类型）
        source_dtypes: 原始支持的 dtype 列表

    Returns:
        原始 dtype 列表中可转换为目标 dtype 的子列表

    Examples:
        >>> get_convertible_source_dtypes("float32", ["float32", "float16", "int32", "bool"])
        ['float32', 'float16', 'int32', 'bool']

        >>> get_convertible_source_dtypes("float32", ["float16", "int32", "int64", "complex64"])
        ['float16', 'int32', 'int64']

        >>> get_convertible_source_dtypes("int32", ["float32", "int8", "uint8", "bool"])
        ['int8', 'uint8', 'bool']

        >>> get_convertible_source_dtypes("complex64", ["float16", "float32", "int32", "bool"])
        ['float16', 'float32', 'int32', 'bool']

        >>> get_convertible_source_dtypes("bool", ["int32", "float32", "bool"])
        ['bool']
    """
    target_normalized = normalize_dtype(target_dtype)
    if target_normalized is None:
        return []

    normalized_sources = normalize_dtype_list(source_dtypes)

    target_category = get_dtype_category(target_normalized)
    if target_category is None:
        return []

    convertible: List[str] = []

    for source_dtype in normalized_sources:
        source_category = get_dtype_category(source_dtype)

        if source_category is None:
            continue

        if _can_convert(
            source_category, source_dtype, target_category, target_normalized
        ):
            convertible.append(source_dtype)

    return convertible


def get_convertible_target_dtypes(
    source_dtype: str, target_dtypes: List[str]
) -> List[str]:
    """
    根据 dtype 可转换规则，从目标 dtype 列表中筛选出 source dtype 可以转换到的列表

    可转换规则（参考：互转换关系.md）：
    1. 整数类型间可以转换，也支持往浮点、复数类型转换
    2. 浮点类型间可以转换，也支持往复数类型转换
    3. 复数类型间可以转换
    4. BOOL支持往整数、浮点、复数类型转换
    5. 其他场景不支持转换

    Args:
        source_dtype: 源 dtype（需要从该类型转换出去）
        target_dtypes: 候选目标 dtype 列表

    Returns:
        候选目标 dtype 列表中 source dtype 可以转换到的子列表

    Examples:
        >>> get_convertible_target_dtypes("float32", ["float32", "float16", "int32", "bool"])
        ['float32', 'float16']

        >>> get_convertible_target_dtypes("int32", ["float32", "int8", "complex64", "bool"])
        ['float32', 'int8', 'complex64']

        >>> get_convertible_target_dtypes("complex64", ["float32", "int32", "complex128", "bool"])
        ['complex128']

        >>> get_convertible_target_dtypes("bool", ["float32", "int32", "complex64", "bool"])
        ['float32', 'int32', 'complex64', 'bool']
    """
    source_normalized = normalize_dtype(source_dtype)
    if source_normalized is None:
        return []

    normalized_targets = normalize_dtype_list(target_dtypes)

    source_category = get_dtype_category(source_normalized)
    if source_category is None:
        return []

    convertible: List[str] = []

    for t_dtype in normalized_targets:
        t_category = get_dtype_category(t_dtype)

        if t_category is None:
            continue

        if _can_convert(
            source_category, source_normalized, t_category, t_dtype
        ):
            convertible.append(t_dtype)

    return convertible


def _can_convert(
    source_category: str, source_dtype: str, target_category: str, target_dtype: str
) -> bool:
    """
    判断源 dtype 是否可以转换到目标 dtype

    Args:
        source_category: 源 dtype 的类型分类
        source_dtype: 源 dtype（已规范化）
        target_category: 目标 dtype 的类型分类
        target_dtype: 目标 dtype（已规范化）

    Returns:
        是否可以转换
    """
    if source_dtype == target_dtype:
        return True

    # 目标是整数：可以从整数、BOOL转换
    if target_category == "integer":
        return source_category in ("integer", "bool")

    # 目标是浮点：可以从整数、浮点、BOOL转换
    if target_category == "float":
        return source_category in ("integer", "float", "bool")

    # 目标是复数：可以从整数、浮点、复数、BOOL转换
    if target_category == "complex":
        return source_category in ("integer", "float", "complex", "bool")

    # 目标是BOOL：只能从BOOL转换（BOOL不接收其他类型的转换）
    if target_category == "bool":
        return source_category == "bool"

    return False


def can_convert_dtype(source_dtype: str, target_dtype: str) -> bool:
    """
    判断单个 dtype 是否可以转换到目标 dtype

    Args:
        source_dtype: 源 dtype
        target_dtype: 目标 dtype

    Returns:
        是否可以转换

    Examples:
        >>> can_convert_dtype("int32", "float32")
        True
        >>> can_convert_dtype("float32", "int32")
        False
        >>> can_convert_dtype("bool", "float32")
        True
        >>> can_convert_dtype("float32", "bool")
        False
    """
    source_normalized = normalize_dtype(source_dtype)
    target_normalized = normalize_dtype(target_dtype)

    if source_normalized is None or target_normalized is None:
        return False

    source_category = get_dtype_category(source_normalized)
    target_category = get_dtype_category(target_normalized)

    if source_category is None or target_category is None:
        return False

    return _can_convert(
        source_category, source_normalized, target_category, target_normalized
    )


# ==================== ConvertToTensor 接口7 转换 ====================

# ConvertToTensor 接口7 支持的 23 种数据类型（source: ConvertToTensor.md 接口7 参数表）
# 语义：任何两个支持的类型间可互相转换（全连接矩阵 23×23）
_CONVERT_TO_TENSOR_IFACE7_DTYPES: Set[str] = {
    "bool",
    "int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64",
    "float32", "float64", "float16", "bfloat16",
    "complex64", "complex128",
    "float8_e5m2", "float8_e4m3fn", "float8_e8m0",
    "float6_e3m2", "float6_e2m3",
    "float4_e2m1", "float4_e1m2",
    "hifloat8", "hifloat4", "hifloat4_scale",
}


def can_convert_to_tensor(source_dtype: str, target_dtype: str) -> bool:
    """
    ConvertToTensor 接口7 转换能力判定（全连接矩阵）

    与 can_convert_dtype 的区别：
    - can_convert_dtype: 遵循互转换关系.md，15 种类型，有方向限制
    - can_convert_to_tensor: 遵循 ConvertToTensor.md 接口7，23 种类型，全连接
    """
    s = normalize_dtype(source_dtype)
    t = normalize_dtype(target_dtype)
    if s is None or t is None:
        return False
    return s in _CONVERT_TO_TENSOR_IFACE7_DTYPES and t in _CONVERT_TO_TENSOR_IFACE7_DTYPES


def get_convert_to_tensor_source_dtypes(
    target_dtype: str, source_dtypes: List[str]
) -> List[str]:
    """
    从源 dtype 列表中筛选出 ConvertToTensor 接口7 可转换为目标 dtype 的子集

    由于 ConvertToTensor 接口7 是全连接矩阵，结果等价于
    normalize_dtype_list(source_dtypes) ∩ _CONVERT_TO_TENSOR_IFACE7_DTYPES
    （前提：target_dtype 本身也在接口7 类型集合中）
    """
    t = normalize_dtype(target_dtype)
    if t is None or t not in _CONVERT_TO_TENSOR_IFACE7_DTYPES:
        return []
    return [d for d in normalize_dtype_list(source_dtypes)
            if d in _CONVERT_TO_TENSOR_IFACE7_DTYPES]


# ==================== dtype 推导相关 ====================

# dtype推导表（参考：互推导关系.md）
# 格式: (dtype1, dtype2) -> result_dtype
# None 表示不能推导
# 表格行/列顺序: f32, f16, f64, bf16, s8, u8, s16, u16, s32, u32, s64, u64, bool, c32, c64, c128
DTYPE_INFER_TABLE: dict = {
    # f32 行
    ("float32", "float32"): "float32",
    ("float32", "float16"): "float32",
    ("float32", "float64"): "float64",
    ("float32", "bfloat16"): "float32",
    ("float32", "int8"): "float32",
    ("float32", "uint8"): "float32",
    ("float32", "int16"): "float32",
    ("float32", "uint16"): None,
    ("float32", "int32"): "float32",
    ("float32", "uint32"): None,
    ("float32", "int64"): "float32",
    ("float32", "uint64"): None,
    ("float32", "bool"): "float32",
    ("float32", "complex32"): "complex64",
    ("float32", "complex64"): "complex64",
    ("float32", "complex128"): "complex128",
    # f16 行
    ("float16", "float32"): "float32",
    ("float16", "float16"): "float16",
    ("float16", "float64"): "float64",
    ("float16", "bfloat16"): "float32",
    ("float16", "int8"): "float16",
    ("float16", "uint8"): "float16",
    ("float16", "int16"): "float16",
    ("float16", "uint16"): None,
    ("float16", "int32"): "float16",
    ("float16", "uint32"): None,
    ("float16", "int64"): "float16",
    ("float16", "uint64"): None,
    ("float16", "bool"): "float16",
    ("float16", "complex32"): "complex32",
    ("float16", "complex64"): "complex64",
    ("float16", "complex128"): "complex128",
    # f64 行
    ("float64", "float32"): "float64",
    ("float64", "float16"): "float64",
    ("float64", "float64"): "float64",
    ("float64", "bfloat16"): "float64",
    ("float64", "int8"): "float64",
    ("float64", "uint8"): "float64",
    ("float64", "int16"): "float64",
    ("float64", "uint16"): None,
    ("float64", "int32"): "float64",
    ("float64", "uint32"): None,
    ("float64", "int64"): "float64",
    ("float64", "uint64"): None,
    ("float64", "bool"): "float64",
    ("float64", "complex32"): "complex128",
    ("float64", "complex64"): "complex128",
    ("float64", "complex128"): "complex128",
    # bf16 行
    ("bfloat16", "float32"): "float32",
    ("bfloat16", "float16"): "float32",
    ("bfloat16", "float64"): "float64",
    ("bfloat16", "bfloat16"): "bfloat16",
    ("bfloat16", "int8"): "bfloat16",
    ("bfloat16", "uint8"): "bfloat16",
    ("bfloat16", "int16"): "bfloat16",
    ("bfloat16", "uint16"): None,
    ("bfloat16", "int32"): "bfloat16",
    ("bfloat16", "uint32"): None,
    ("bfloat16", "int64"): "bfloat16",
    ("bfloat16", "uint64"): None,
    ("bfloat16", "bool"): "bfloat16",
    ("bfloat16", "complex32"): "complex32",
    ("bfloat16", "complex64"): "complex64",
    ("bfloat16", "complex128"): "complex128",
    # s8 行
    ("int8", "float32"): "float32",
    ("int8", "float16"): "float16",
    ("int8", "float64"): "float64",
    ("int8", "bfloat16"): "bfloat16",
    ("int8", "int8"): "int8",
    ("int8", "uint8"): "int16",
    ("int8", "int16"): "int16",
    ("int8", "uint16"): None,
    ("int8", "int32"): "int32",
    ("int8", "uint32"): None,
    ("int8", "int64"): "int64",
    ("int8", "uint64"): None,
    ("int8", "bool"): "int8",
    ("int8", "complex32"): "complex32",
    ("int8", "complex64"): "complex64",
    ("int8", "complex128"): "complex128",
    # u8 行
    ("uint8", "float32"): "float32",
    ("uint8", "float16"): "float16",
    ("uint8", "float64"): "float64",
    ("uint8", "bfloat16"): "bfloat16",
    ("uint8", "int8"): "int16",
    ("uint8", "uint8"): "uint8",
    ("uint8", "int16"): "int16",
    ("uint8", "uint16"): None,
    ("uint8", "int32"): "int32",
    ("uint8", "uint32"): None,
    ("uint8", "int64"): "int64",
    ("uint8", "uint64"): None,
    ("uint8", "bool"): "uint8",
    ("uint8", "complex32"): "complex32",
    ("uint8", "complex64"): "complex64",
    ("uint8", "complex128"): "complex128",
    # s16 行
    ("int16", "float32"): "float32",
    ("int16", "float16"): "float16",
    ("int16", "float64"): "float64",
    ("int16", "bfloat16"): "bfloat16",
    ("int16", "int8"): "int16",
    ("int16", "uint8"): "int16",
    ("int16", "int16"): "int16",
    ("int16", "uint16"): None,
    ("int16", "int32"): "int32",
    ("int16", "uint32"): None,
    ("int16", "int64"): "int64",
    ("int16", "uint64"): None,
    ("int16", "bool"): "int16",
    ("int16", "complex32"): "complex32",
    ("int16", "complex64"): "complex64",
    ("int16", "complex128"): "complex128",
    # u16 行
    ("uint16", "float32"): None,
    ("uint16", "float16"): None,
    ("uint16", "float64"): None,
    ("uint16", "bfloat16"): None,
    ("uint16", "int8"): None,
    ("uint16", "uint8"): None,
    ("uint16", "int16"): None,
    ("uint16", "uint16"): "uint16",
    ("uint16", "int32"): None,
    ("uint16", "uint32"): None,
    ("uint16", "int64"): None,
    ("uint16", "uint64"): None,
    ("uint16", "bool"): None,
    ("uint16", "complex32"): None,
    ("uint16", "complex64"): None,
    ("uint16", "complex128"): None,
    # s32 行
    ("int32", "float32"): "float32",
    ("int32", "float16"): "float16",
    ("int32", "float64"): "float64",
    ("int32", "bfloat16"): "bfloat16",
    ("int32", "int8"): "int32",
    ("int32", "uint8"): "int32",
    ("int32", "int16"): "int32",
    ("int32", "uint16"): None,
    ("int32", "int32"): "int32",
    ("int32", "uint32"): None,
    ("int32", "int64"): "int64",
    ("int32", "uint64"): None,
    ("int32", "bool"): "int32",
    ("int32", "complex32"): "complex32",
    ("int32", "complex64"): "complex64",
    ("int32", "complex128"): "complex128",
    # u32 行
    ("uint32", "float32"): None,
    ("uint32", "float16"): None,
    ("uint32", "float64"): None,
    ("uint32", "bfloat16"): None,
    ("uint32", "int8"): None,
    ("uint32", "uint8"): None,
    ("uint32", "int16"): None,
    ("uint32", "uint16"): None,
    ("uint32", "int32"): None,
    ("uint32", "uint32"): "uint32",
    ("uint32", "int64"): None,
    ("uint32", "uint64"): None,
    ("uint32", "bool"): None,
    ("uint32", "complex32"): None,
    ("uint32", "complex64"): None,
    ("uint32", "complex128"): None,
    # s64 行
    ("int64", "float32"): "float32",
    ("int64", "float16"): "float16",
    ("int64", "float64"): "float64",
    ("int64", "bfloat16"): "bfloat16",
    ("int64", "int8"): "int64",
    ("int64", "uint8"): "int64",
    ("int64", "int16"): "int64",
    ("int64", "uint16"): None,
    ("int64", "int32"): "int64",
    ("int64", "uint32"): None,
    ("int64", "int64"): "int64",
    ("int64", "uint64"): None,
    ("int64", "bool"): "int64",
    ("int64", "complex32"): "complex32",
    ("int64", "complex64"): "complex64",
    ("int64", "complex128"): "complex128",
    # u64 行
    ("uint64", "float32"): None,
    ("uint64", "float16"): None,
    ("uint64", "float64"): None,
    ("uint64", "bfloat16"): None,
    ("uint64", "int8"): None,
    ("uint64", "uint8"): None,
    ("uint64", "int16"): None,
    ("uint64", "uint16"): None,
    ("uint64", "int32"): None,
    ("uint64", "uint32"): None,
    ("uint64", "int64"): None,
    ("uint64", "uint64"): "uint64",
    ("uint64", "bool"): None,
    ("uint64", "complex32"): None,
    ("uint64", "complex64"): None,
    ("uint64", "complex128"): None,
    # bool 行
    ("bool", "float32"): "float32",
    ("bool", "float16"): "float16",
    ("bool", "float64"): "float64",
    ("bool", "bfloat16"): "bfloat16",
    ("bool", "int8"): "int8",
    ("bool", "uint8"): "uint8",
    ("bool", "int16"): "int16",
    ("bool", "uint16"): None,
    ("bool", "int32"): "int32",
    ("bool", "uint32"): None,
    ("bool", "int64"): "int64",
    ("bool", "uint64"): None,
    ("bool", "bool"): "bool",
    ("bool", "complex32"): "complex32",
    ("bool", "complex64"): "complex64",
    ("bool", "complex128"): "complex128",
    # c32 行
    ("complex32", "float32"): "complex64",
    ("complex32", "float16"): "complex32",
    ("complex32", "float64"): "complex128",
    ("complex32", "bfloat16"): "complex32",
    ("complex32", "int8"): "complex32",
    ("complex32", "uint8"): "complex32",
    ("complex32", "int16"): "complex32",
    ("complex32", "uint16"): None,
    ("complex32", "int32"): "complex32",
    ("complex32", "uint32"): None,
    ("complex32", "int64"): "complex32",
    ("complex32", "uint64"): None,
    ("complex32", "bool"): "complex32",
    ("complex32", "complex32"): "complex32",
    ("complex32", "complex64"): "complex64",
    ("complex32", "complex128"): "complex128",
    # c64 行
    ("complex64", "float32"): "complex64",
    ("complex64", "float16"): "complex64",
    ("complex64", "float64"): "complex128",
    ("complex64", "bfloat16"): "complex64",
    ("complex64", "int8"): "complex64",
    ("complex64", "uint8"): "complex64",
    ("complex64", "int16"): "complex64",
    ("complex64", "uint16"): None,
    ("complex64", "int32"): "complex64",
    ("complex64", "uint32"): None,
    ("complex64", "int64"): "complex64",
    ("complex64", "uint64"): None,
    ("complex64", "bool"): "complex64",
    ("complex64", "complex32"): "complex64",
    ("complex64", "complex64"): "complex64",
    ("complex64", "complex128"): "complex128",
    # c128 行
    ("complex128", "float32"): "complex128",
    ("complex128", "float16"): "complex128",
    ("complex128", "float64"): "complex128",
    ("complex128", "bfloat16"): "complex128",
    ("complex128", "int8"): "complex128",
    ("complex128", "uint8"): "complex128",
    ("complex128", "int16"): "complex128",
    ("complex128", "uint16"): None,
    ("complex128", "int32"): "complex128",
    ("complex128", "uint32"): None,
    ("complex128", "int64"): "complex128",
    ("complex128", "uint64"): None,
    ("complex128", "bool"): "complex128",
    ("complex128", "complex32"): "complex128",
    ("complex128", "complex64"): "complex128",
    ("complex128", "complex128"): "complex128",
    # hifloat4 行
    ("hifloat4", "float32"): "float32",
    ("hifloat4", "float16"): "float16",
    ("hifloat4", "float64"): "float64",
    ("hifloat4", "bfloat16"): "bfloat16",
    ("hifloat4", "hifloat4"): "hifloat4",
    ("hifloat4", "hifloat4_scale"): "float16",
    ("hifloat4", "int8"): "hifloat4",
    ("hifloat4", "uint8"): "hifloat4",
    ("hifloat4", "int16"): "hifloat4",
    ("hifloat4", "int32"): "hifloat4",
    ("hifloat4", "int64"): "hifloat4",
    ("hifloat4", "bool"): "hifloat4",
    # hifloat4 与其他 dtype 行的交叉推导
    ("float32", "hifloat4"): "float32",
    ("float16", "hifloat4"): "float16",
    ("float64", "hifloat4"): "float64",
    ("bfloat16", "hifloat4"): "bfloat16",
    ("int8", "hifloat4"): "hifloat4",
    ("uint8", "hifloat4"): "hifloat4",
    ("int16", "hifloat4"): "hifloat4",
    ("int32", "hifloat4"): "hifloat4",
    ("int64", "hifloat4"): "hifloat4",
    ("bool", "hifloat4"): "hifloat4",
    ("complex32", "hifloat4"): "complex32",
    ("complex64", "hifloat4"): "complex64",
    ("complex128", "hifloat4"): "complex128",
    # hifloat4_scale 行
    ("hifloat4_scale", "float32"): "float32",
    ("hifloat4_scale", "float16"): "float16",
    ("hifloat4_scale", "float64"): "float64",
    ("hifloat4_scale", "bfloat16"): "bfloat16",
    ("hifloat4_scale", "hifloat4_scale"): "hifloat4_scale",
    ("hifloat4_scale", "hifloat4"): "float16",
    ("hifloat4_scale", "int8"): "hifloat4_scale",
    ("hifloat4_scale", "uint8"): "hifloat4_scale",
    ("hifloat4_scale", "int16"): "hifloat4_scale",
    ("hifloat4_scale", "int32"): "hifloat4_scale",
    ("hifloat4_scale", "int64"): "hifloat4_scale",
    ("hifloat4_scale", "bool"): "hifloat4_scale",
    # hifloat4_scale 与其他 dtype 行的交叉推导
    ("float32", "hifloat4_scale"): "float32",
    ("float16", "hifloat4_scale"): "float16",
    ("float64", "hifloat4_scale"): "float64",
    ("bfloat16", "hifloat4_scale"): "bfloat16",
    ("int8", "hifloat4_scale"): "hifloat4_scale",
    ("uint8", "hifloat4_scale"): "hifloat4_scale",
    ("int16", "hifloat4_scale"): "hifloat4_scale",
    ("int32", "hifloat4_scale"): "hifloat4_scale",
    ("int64", "hifloat4_scale"): "hifloat4_scale",
    ("bool", "hifloat4_scale"): "hifloat4_scale",
    ("complex32", "hifloat4_scale"): "complex32",
    ("complex64", "hifloat4_scale"): "complex64",
    ("complex128", "hifloat4_scale"): "complex128",
}

# dtype推导表（参考：TensorScalar互推导关系.md）
# 格式: (scalar_dtype, tensor_dtype) -> result_dtype
# 行 = Scalar dtype, 列 = Tensor dtype
# 与 DTYPE_INFER_TABLE 的13处关键差异：
#   f16/bf16 Scalar + 整数 Tensor → f32（而非 f16/bf16）
#   s8 Scalar + u8/s16 Tensor → u8/u16（而非 s16）
DTYPE_TENSOR_SCALAR_INFER_TABLE: dict = {
    ("float32", "float32"): "float32", ("float32", "float16"): "float16",
    ("float32", "float64"): "float64", ("float32", "bfloat16"): "bfloat16",
    ("float32", "int8"): "float32", ("float32", "uint8"): "float32",
    ("float32", "int16"): "float32", ("float32", "uint16"): None,
    ("float32", "int32"): "float32", ("float32", "uint32"): None,
    ("float32", "int64"): "float32", ("float32", "uint64"): None,
    ("float32", "bool"): "float32",
    ("float32", "complex32"): "complex32", ("float32", "complex64"): "complex64",
    ("float32", "complex128"): "complex128",
    ("float16", "float32"): "float32", ("float16", "float16"): "float16",
    ("float16", "float64"): "float64", ("float16", "bfloat16"): "bfloat16",
    ("float16", "int8"): "float32", ("float16", "uint8"): "float32",
    ("float16", "int16"): "float32", ("float16", "uint16"): None,
    ("float16", "int32"): "float32", ("float16", "uint32"): None,
    ("float16", "int64"): "float32", ("float16", "uint64"): None,
    ("float16", "bool"): "float32",
    ("float16", "complex32"): "complex32", ("float16", "complex64"): "complex64",
    ("float16", "complex128"): "complex128",
    ("float64", "float32"): "float32", ("float64", "float16"): "float16",
    ("float64", "float64"): "float64", ("float64", "bfloat16"): "bfloat16",
    ("float64", "int8"): "float32", ("float64", "uint8"): "float32",
    ("float64", "int16"): "float32", ("float64", "uint16"): None,
    ("float64", "int32"): "float32", ("float64", "uint32"): None,
    ("float64", "int64"): "float32", ("float64", "uint64"): None,
    ("float64", "bool"): "float32",
    ("float64", "complex32"): "complex128", ("float64", "complex64"): "complex128",
    ("float64", "complex128"): "complex128",
    ("bfloat16", "float32"): "float32", ("bfloat16", "float16"): "float16",
    ("bfloat16", "float64"): "float64", ("bfloat16", "bfloat16"): "bfloat16",
    ("bfloat16", "int8"): "float32", ("bfloat16", "uint8"): "float32",
    ("bfloat16", "int16"): "float32", ("bfloat16", "uint16"): None,
    ("bfloat16", "int32"): "float32", ("bfloat16", "uint32"): None,
    ("bfloat16", "int64"): "float32", ("bfloat16", "uint64"): None,
    ("bfloat16", "bool"): "float32",
    ("bfloat16", "complex32"): "complex32", ("bfloat16", "complex64"): "complex64",
    ("bfloat16", "complex128"): "complex128",
    ("int8", "float32"): "float32", ("int8", "float16"): "float32",
    ("int8", "float64"): "float64", ("int8", "bfloat16"): "float32",
    ("int8", "int8"): "int8", ("int8", "uint8"): "uint8",
    ("int8", "int16"): "uint16", ("int8", "uint16"): "uint16",
    ("int8", "int32"): "int32", ("int8", "uint32"): "uint32",
    ("int8", "int64"): "int64", ("int8", "uint64"): "uint64",
    ("int8", "bool"): "int8",
    ("int8", "complex32"): "complex32", ("int8", "complex64"): "complex64",
    ("int8", "complex128"): "complex128",
    ("uint8", "float32"): "float32", ("uint8", "float16"): "float32",
    ("uint8", "float64"): "float64", ("uint8", "bfloat16"): "float32",
    ("uint8", "int8"): "int8", ("uint8", "uint8"): "uint8",
    ("uint8", "int16"): "uint16", ("uint8", "uint16"): "uint16",
    ("uint8", "int32"): "int32", ("uint8", "uint32"): "uint32",
    ("uint8", "int64"): "int64", ("uint8", "uint64"): "uint64",
    ("uint8", "bool"): "uint8",
    ("uint8", "complex32"): "complex32", ("uint8", "complex64"): "complex64",
    ("uint8", "complex128"): "complex128",
    ("int16", "float32"): "float32", ("int16", "float16"): "float32",
    ("int16", "float64"): "float64", ("int16", "bfloat16"): "float32",
    ("int16", "int8"): "int8", ("int16", "uint8"): "uint8",
    ("int16", "int16"): "int16", ("int16", "uint16"): "uint16",
    ("int16", "int32"): "int32", ("int16", "uint32"): "uint32",
    ("int16", "int64"): "int64", ("int16", "uint64"): "uint64",
    ("int16", "bool"): "int16",
    ("int16", "complex32"): "complex32", ("int16", "complex64"): "complex64",
    ("int16", "complex128"): "complex128",
    ("uint16", "float32"): "float32", ("uint16", "float16"): "float32",
    ("uint16", "float64"): "float64", ("uint16", "bfloat16"): "float32",
    ("uint16", "int8"): "int8", ("uint16", "uint8"): "uint8",
    ("uint16", "int16"): "uint16", ("uint16", "uint16"): "uint16",
    ("uint16", "int32"): "int32", ("uint16", "uint32"): "uint32",
    ("uint16", "int64"): "int64", ("uint16", "uint64"): "uint64",
    ("uint16", "bool"): None,
    ("uint16", "complex32"): "complex32", ("uint16", "complex64"): "complex64",
    ("uint16", "complex128"): "complex128",
    ("int32", "float32"): "float32", ("int32", "float16"): "float32",
    ("int32", "float64"): "float64", ("int32", "bfloat16"): "float32",
    ("int32", "int8"): "int8", ("int32", "uint8"): "uint8",
    ("int32", "int16"): "uint16", ("int32", "uint16"): "uint16",
    ("int32", "int32"): "int32", ("int32", "uint32"): "uint32",
    ("int32", "int64"): "int64", ("int32", "uint64"): "uint64",
    ("int32", "bool"): "int32",
    ("int32", "complex32"): "complex32", ("int32", "complex64"): "complex64",
    ("int32", "complex128"): "complex128",
    ("uint32", "float32"): "float32", ("uint32", "float16"): "float32",
    ("uint32", "float64"): "float64", ("uint32", "bfloat16"): "float32",
    ("uint32", "int8"): "int8", ("uint32", "uint8"): "uint8",
    ("uint32", "int16"): "uint16", ("uint32", "uint16"): "uint16",
    ("uint32", "int32"): "int32", ("uint32", "uint32"): "uint32",
    ("uint32", "int64"): "int64", ("uint32", "uint64"): "uint64",
    ("uint32", "bool"): None,
    ("uint32", "complex32"): "complex32", ("uint32", "complex64"): "complex64",
    ("uint32", "complex128"): "complex128",
    ("int64", "float32"): "float32", ("int64", "float16"): "float32",
    ("int64", "float64"): "float64", ("int64", "bfloat16"): "float32",
    ("int64", "int8"): "int8", ("int64", "uint8"): "uint8",
    ("int64", "int16"): "uint16", ("int64", "uint16"): "uint16",
    ("int64", "int32"): "int32", ("int64", "uint32"): "uint32",
    ("int64", "int64"): "int64", ("int64", "uint64"): "uint64",
    ("int64", "bool"): "int64",
    ("int64", "complex32"): "complex32", ("int64", "complex64"): "complex64",
    ("int64", "complex128"): "complex128",
    ("uint64", "float32"): "float32", ("uint64", "float16"): "float32",
    ("uint64", "float64"): "float64", ("uint64", "bfloat16"): "float32",
    ("uint64", "int8"): "int8", ("uint64", "uint8"): "uint8",
    ("uint64", "int16"): "uint16", ("uint64", "uint16"): "uint16",
    ("uint64", "int32"): "int32", ("uint64", "uint32"): "uint32",
    ("uint64", "int64"): "int64", ("uint64", "uint64"): "uint64",
    ("uint64", "bool"): None,
    ("uint64", "complex32"): "complex32", ("uint64", "complex64"): "complex64",
    ("uint64", "complex128"): "complex128",
    ("bool", "float32"): "float32", ("bool", "float16"): "float16",
    ("bool", "float64"): "float64", ("bool", "bfloat16"): "bfloat16",
    ("bool", "int8"): "int8", ("bool", "uint8"): "uint8",
    ("bool", "int16"): "int16", ("bool", "uint16"): "uint16",
    ("bool", "int32"): "int32", ("bool", "uint32"): "uint32",
    ("bool", "int64"): "int64", ("bool", "uint64"): "uint64",
    ("bool", "bool"): "bool",
    ("bool", "complex32"): "complex32", ("bool", "complex64"): "complex64",
    ("bool", "complex128"): "complex128",
    ("complex32", "float32"): "complex64", ("complex32", "float16"): "complex32",
    ("complex32", "float64"): "complex128", ("complex32", "bfloat16"): "complex64",
    ("complex32", "int8"): "complex64", ("complex32", "uint8"): "complex64",
    ("complex32", "int16"): "complex64", ("complex32", "uint16"): "complex64",
    ("complex32", "int32"): "complex64", ("complex32", "uint32"): "complex64",
    ("complex32", "int64"): "complex64", ("complex32", "uint64"): "complex64",
    ("complex32", "bool"): "complex64",
    ("complex32", "complex32"): "complex32", ("complex32", "complex64"): "complex64",
    ("complex32", "complex128"): "complex128",
    ("complex64", "float32"): "complex64", ("complex64", "float16"): "complex32",
    ("complex64", "float64"): "complex128", ("complex64", "bfloat16"): "complex64",
    ("complex64", "int8"): "complex64", ("complex64", "uint8"): "complex64",
    ("complex64", "int16"): "complex64", ("complex64", "uint16"): "complex64",
    ("complex64", "int32"): "complex64", ("complex64", "uint32"): "complex64",
    ("complex64", "int64"): "complex64", ("complex64", "uint64"): "complex64",
    ("complex64", "bool"): "complex64",
    ("complex64", "complex32"): "complex32", ("complex64", "complex64"): "complex64",
    ("complex64", "complex128"): "complex128",
    ("complex128", "float32"): "complex64", ("complex128", "float16"): "complex32",
    ("complex128", "float64"): "complex128", ("complex128", "bfloat16"): "complex64",
    ("complex128", "int8"): "complex64", ("complex128", "uint8"): "complex64",
    ("complex128", "int16"): "complex64", ("complex128", "uint16"): "complex64",
    ("complex128", "int32"): "complex64", ("complex128", "uint32"): "complex64",
    ("complex128", "int64"): "complex64", ("complex128", "uint64"): "complex64",
    ("complex128", "bool"): "complex64",
    ("complex128", "complex32"): "complex32", ("complex128", "complex64"): "complex64",
    ("complex128", "complex128"): "complex128",
}


def infer_tensor_scalar_dtypes(scalar_dtype: str, tensor_dtype: str) -> Optional[str]:
    """
    根据Scalar dtype和Tensor dtype推导结果dtype（基于TensorScalar推导表）

    参考文档：TensorScalar互推导关系.md

    Args:
        scalar_dtype: Scalar 参数的 dtype
        tensor_dtype: Tensor 参数的 dtype

    Returns:
        推导后的dtype，如果不能推导则返回None

    Examples:
        >>> infer_tensor_scalar_dtypes("float16", "int8")
        'float32'
        >>> infer_tensor_scalar_dtypes("float16", "int8") != infer_two_dtypes("float16", "int8")
        True
        >>> infer_tensor_scalar_dtypes("float32", "int8")
        'float32'
    """
    d1 = normalize_dtype(scalar_dtype)
    d2 = normalize_dtype(tensor_dtype)

    if d1 is None or d2 is None:
        return None

    if d1 == d2:
        return d1

    result = DTYPE_TENSOR_SCALAR_INFER_TABLE.get((d1, d2))
    return result


def get_inferable_tensor_scalar_combinations(
    scalar_dtypes: List[str], tensor_dtypes: List[str]
) -> List[List[str]]:
    """
    根据Scalar和Tensor支持的dtype列表，计算所有支持TS推导的有效组合

    Args:
        scalar_dtypes: Scalar参数支持的dtype列表
        tensor_dtypes: Tensor参数支持的dtype列表

    Returns:
        所有有效的 [scalar_dtype, tensor_dtype] 组合列表

    Examples:
        >>> scalar_dtypes = ["float16", "float32"]
        >>> tensor_dtypes = ["float16", "int8"]
        >>> result = get_inferable_tensor_scalar_combinations(scalar_dtypes, tensor_dtypes)
        >>> len(result) > 0
        True
    """
    normalized_scalars = normalize_dtype_list(scalar_dtypes)
    normalized_tensors = normalize_dtype_list(tensor_dtypes)

    combinations: List[List[str]] = []
    for s in normalized_scalars:
        for t in normalized_tensors:
            result = infer_tensor_scalar_dtypes(s, t)
            if result is not None:
                combinations.append([s, t])

    return combinations


def infer_two_dtypes(dtype1: str, dtype2: str) -> Optional[str]:
    """
    根据两个dtype推导结果dtype（基于推导表）

    Args:
        dtype1: 第一个dtype
        dtype2: 第二个dtype

    Returns:
        推导后的dtype，如果不能推导则返回None

    Examples:
        >>> infer_two_dtypes("float16", "float32")
        'float32'
        >>> infer_two_dtypes("float16", "bfloat16")
        'float32'
        >>> infer_two_dtypes("float32", "uint16")
        None
    """
    d1 = normalize_dtype(dtype1)
    d2 = normalize_dtype(dtype2)

    if d1 is None or d2 is None:
        return None

    if d1 == d2:
        return d1

    result = DTYPE_INFER_TABLE.get((d1, d2))
    return result


def infer_dtypes(dtype_list: List[str]) -> Optional[str]:
    """
    根据dtype列表计算推导后的dtype
    多个dtype依次两两推导，得到最终结果

    Args:
        dtype_list: dtype列表

    Returns:
        推导后的dtype，如果无法推导则返回None

    Examples:
        >>> infer_dtypes(["float16", "float32"])
        'float32'
        >>> infer_dtypes(["float16", "float16", "float32"])
        'float32'
        >>> infer_dtypes(["float16", "bfloat16"])
        'float32'
        >>> infer_dtypes(["float16", "uint16"])
        None
    """
    if not dtype_list:
        return None

    normalized_list = normalize_dtype_list(dtype_list)
    if not normalized_list:
        return None

    if len(normalized_list) == 1:
        return normalized_list[0]

    result = normalized_list[0]
    for i in range(1, len(normalized_list)):
        result = infer_two_dtypes(result, normalized_list[i])
        if result is None:
            return None

    return result


def get_inferable_dtype_combinations(
    tensor_dtype_lists: List[List[str]],
) -> List[List[str]]:
    """
    根据多个tensor支持的dtype列表，计算所有支持推导的有效dtype组合

    Args:
        tensor_dtype_lists: 多个tensor参数各自支持的dtype列表
            例如: [["float16", "float32", "bfloat16"],
                   ["float16", "float32", "bfloat16"],
                   ["float16", "float32", "bfloat16"]]

    Returns:
        所有有效的dtype组合列表（每个组合中的dtype可以相互推导）
        例如: [["float16", "float16", "float16"],
               ["float16", "float16", "float32"],
               ["float16", "float16", "bfloat16"],
               ...]

    Examples:
        >>> dtypes1 = ["float16", "float32", "bfloat16"]
        >>> dtypes2 = ["float16", "float32", "bfloat16"]
        >>> result = get_inferable_dtype_combinations([dtypes1, dtypes2])
        >>> len(result) > 0
        True
        >>> # 验证每个组合都可以推导
        >>> all(infer_dtypes(combo) is not None for combo in result)
        True
    """
    if not tensor_dtype_lists:
        return []

    if len(tensor_dtype_lists) == 1:
        normalized = normalize_dtype_list(tensor_dtype_lists[0])
        return [[d] for d in normalized]

    # 规范化所有dtype列表
    normalized_lists = []
    for dtype_list in tensor_dtype_lists:
        normalized = normalize_dtype_list(dtype_list)
        if not normalized:
            return []
        normalized_lists.append(normalized)

    # 生成所有可能的组合
    all_combinations = list(itertools.product(*normalized_lists))

    # 筛选可以推导的组合
    valid_combinations = []
    for combo in all_combinations:
        if infer_dtypes(list(combo)) is not None:
            valid_combinations.append(list(combo))

    return valid_combinations


# ==================== 辅助函数 ====================


def get_all_supported_dtypes() -> List[str]:
    """获取所有支持的 dtype 列表"""
    return list(_STANDARD_DTYPES)


def is_valid_dtype(dtype: Optional[str]) -> bool:
    """检查 dtype 是否有效"""
    return normalize_dtype(dtype) is not None


def dtype_to_acl_format(dtype: Optional[str]) -> Optional[str]:
    """
    将标准 dtype 名称转换为 ACL 格式

    Args:
        dtype: 标准 dtype 名称

    Returns:
        ACL 格式的 dtype 名称

    Examples:
        >>> dtype_to_acl_format("float32")
        'ACL_FLOAT'
        >>> dtype_to_acl_format("float16")
        'ACL_FLOAT16'
        >>> dtype_to_acl_format("int32")
        'ACL_INT32'
    """
    normalized = normalize_dtype(dtype)
    if normalized is None:
        return None

    acl_map: dict = {
        "float32": "ACL_FLOAT",
        "float16": "ACL_FLOAT16",
        "float64": "ACL_DOUBLE",
        "bfloat16": "ACL_BF16",
        "int8": "ACL_INT8",
        "uint8": "ACL_UINT8",
        "int16": "ACL_INT16",
        "uint16": "ACL_UINT16",
        "int32": "ACL_INT32",
        "uint32": "ACL_UINT32",
        "int64": "ACL_INT64",
        "uint64": "ACL_UINT64",
        "bool": "ACL_BOOL",
        "complex32": "ACL_COMPLEX32",
        "complex64": "ACL_COMPLEX64",
        "complex128": "ACL_COMPLEX128",
        "hifloat4": "ACL_HIFLOAT4",
        "hifloat4_scale": "ACL_HIFLOAT4_SCALE",
    }

    return acl_map.get(normalized)


# ==================== Shape 相关函数 ====================

# 常量定义
MAX_SHAPE_PRODUCT = 2 * 1024 * 1024 * 1024  # 2G
MAX_DIM_VALUE = 2 * 1024 * 1024 * 1024  # 单轴最大值2G
MIN_DIM_VALUE = 1
MAX_DIMENSIONS = 8  # 最大维度数
NUM_LOG_SEGMENTS = 500  # 对数分段数量

# Shape size intervals (byte budget), following TestCaseGenerator proportions
# Format: (chose_range_max, min_size_bytes, max_size_bytes)
_SHAPE_SIZE_INTERVALS = [
    (0.85, 2,                            100 * 1024 * 1024),
    (0.90, 100 * 1024 * 1024,            500 * 1024 * 1024),
    (0.95, 100 * 1024 * 1024,            500 * 1024 * 1024),
    (0.99, 500 * 1024 * 1024,            1024 * 1024 * 1024),
    (1.00, 1024 * 1024 * 1024,           2 * 1024 * 1024 * 1024),
]
_SHAPE_INTERVAL_WEIGHTS = [85, 5, 5, 4, 1]
_SHAPE_RULE_NAMES = ["avg", "shuffle", "max", "split_dim", "min"]
_SHAPE_MAX_ITERATIONS = 1000


def _calculate_shape_product(shape: List[int]) -> int:
    """计算shape的乘积"""
    product = 1
    for dim in shape:
        product *= dim
        if product > MAX_SHAPE_PRODUCT:
            return MAX_SHAPE_PRODUCT + 1
    return product


def _get_dtype_byte(dtype: str) -> int:
    if dtype in ('int8', 'uint8', 'bool', 'int4', 'uint1'):
        return 1
    elif dtype in ('float16', 'int16', 'uint16', 'bfloat16'):
        return 2
    elif dtype in ('float32', 'int32', 'uint32', 'complex32', 'float'):
        return 4
    elif dtype in ('int64', 'uint64', 'float64', 'double', 'complex64'):
        return 8
    elif dtype in ('complex128',):
        return 16
    return 4


def _compute_product(shape):
    product = 1
    for s in shape:
        product *= s
    return product


def _select_size_interval(dtype_byte, chose_range=None):
    if chose_range is not None:
        min_size_bytes = _SHAPE_SIZE_INTERVALS[0][1]
        max_size_bytes = _SHAPE_SIZE_INTERVALS[0][2]
        for interval in _SHAPE_SIZE_INTERVALS:
            if chose_range <= interval[0]:
                min_size_bytes, max_size_bytes = interval[1], interval[2]
                break
    else:
        total_weight = sum(_SHAPE_INTERVAL_WEIGHTS)
        rand_val = random.randint(1, total_weight)
        cumulative = 0
        selected_idx = 0
        for i, weight in enumerate(_SHAPE_INTERVAL_WEIGHTS):
            cumulative += weight
            if rand_val <= cumulative:
                selected_idx = i
                break
        min_size_bytes = _SHAPE_SIZE_INTERVALS[selected_idx][1]
        max_size_bytes = _SHAPE_SIZE_INTERVALS[selected_idx][2]
    min_elements = max(min_size_bytes // dtype_byte, 1)
    max_elements = min(max_size_bytes // dtype_byte, MAX_SHAPE_PRODUCT)
    if max_elements < min_elements:
        max_elements = min_elements
    return min_elements, max_elements


def _shape_rule_avg(dim_num, max_elements, min_elements):
    for _ in range(_SHAPE_MAX_ITERATIONS):
        shape_value_max = max(math.floor(math.pow(max_elements, 1 / dim_num)), 1)
        shape_value_min = max(math.floor(math.pow(min_elements, 1 / dim_num)), 1)
        shape = [random.randint(shape_value_min, max(shape_value_max, shape_value_min)) for _ in range(dim_num)]
        shape_all = _compute_product(shape)
        if shape_all < min_elements:
            min_range = min_elements / max(shape_all, 1)
            max_range = max_elements / max(shape_all, 1)
            idx = shape.index(min(shape))
            shape[idx] = max(1, math.ceil(min(shape) * random.uniform(min_range, max_range)))
        shape_all = _compute_product(shape)
        if shape_all <= max_elements and shape_all >= min_elements:
            break
    return shape


def _shape_rule_shuffle(dim_num, max_elements, min_elements):
    dim_min = 1
    for _ in range(_SHAPE_MAX_ITERATIONS):
        lst = list(range(dim_num))
        random.shuffle(lst)
        shape_value_range_tmp = []
        shape_size = max(max_elements, 1)
        if dim_min != 1:
            for i in range(dim_num - 1):
                shape_size = shape_size // dim_min
        dim_min = random.randint(2, 10)
        for i in range(dim_num):
            a = random.randint(dim_min, max(shape_size, dim_min))
            dim_value = min(a, MAX_DIM_VALUE)
            dim_value = max(dim_value, dim_min)
            shape_value_range_tmp.append(dim_value)
            shape_size = max(shape_size // max(dim_value, 1), dim_min)
        shape_value_range = [v for _, v in sorted(zip(lst, shape_value_range_tmp))]
        shape = [random.randint(dim_min, shape_value_range[i]) for i in range(dim_num)]
        shape_all = _compute_product(shape)
        if shape_all < min_elements:
            min_range = min_elements / max(shape_all, 1)
            max_range = max_elements / max(shape_all, 1)
            idx = shape.index(min(shape))
            shape[idx] = max(1, math.ceil(min(shape) * random.uniform(min_range, max_range)))
        shape_all = _compute_product(shape)
        if shape_all <= max_elements and shape_all >= min_elements:
            break
        else:
            dim_min = 1
    return shape


def _shape_rule_max(dim_num, max_elements, min_elements):
    dim_min = 1
    for _ in range(_SHAPE_MAX_ITERATIONS):
        lst = list(range(dim_num))
        random.shuffle(lst)
        shape_value_range_tmp = []
        shape_size = max(max_elements, 1)
        if dim_min != 1:
            for i in range(dim_num - 1):
                shape_size = shape_size // dim_min
        dim_min = random.randint(2, 10)
        for i in range(dim_num):
            min_value = 1000 if shape_size > 1000 else dim_min
            a = random.randint(min_value, max(shape_size, min_value))
            dim_value = min(a, 9999)
            dim_value = max(dim_value, dim_min)
            shape_value_range_tmp.append(dim_value)
            shape_size = max(shape_size // max(dim_value, 1), dim_min)
        shape_value_range = [v for _, v in sorted(zip(lst, shape_value_range_tmp))]
        shape = [random.randint(dim_min, shape_value_range[i]) for i in range(dim_num)]
        shape_all = _compute_product(shape)
        if shape_all < min_elements:
            min_range = min_elements / max(shape_all, 1)
            max_range = max_elements / max(shape_all, 1)
            idx = shape.index(min(shape))
            shape[idx] = max(1, math.ceil(min(shape) * random.uniform(min_range, max_range)))
        shape_all = _compute_product(shape)
        if shape_all <= max_elements and shape_all >= min_elements:
            break
        else:
            dim_min = 1
    return shape


def _shape_rule_split_dim(dim_num, max_elements, min_elements):
    for _ in range(_SHAPE_MAX_ITERATIONS):
        dim_min = random.randint(2, 10)
        block_dim = random.randint(0, dim_num - 1)
        ub_dim = random.randint(block_dim, dim_num - 1)
        block_dim_value = random.randint(min(64, max_elements), min(267, max_elements))
        shape_value_range = [dim_min] * dim_num
        if dim_num > 1 and block_dim != ub_dim:
            ub_dim_value = max(max_elements // max(block_dim_value, 1), 1)
        else:
            ub_dim_value = max(max_elements, 1)
        j = 0
        for i in range(dim_num - 2):
            ub_dim_value = ub_dim_value // max(dim_min, 1)
            ub_dim_value = max(ub_dim_value, 1)
            while j == block_dim or j == ub_dim:
                j = j + 1
            if ub_dim_value > 1:
                shape_value_range[j] = dim_min
            else:
                shape_value_range[j] = 1
        if block_dim != ub_dim:
            shape_value_range[block_dim] = block_dim_value
        else:
            shape_value_range[block_dim] = ub_dim_value
        shape_value_range[ub_dim] = ub_dim_value
        shape = [random.randint(1, max(shape_value_range[i], 1)) for i in range(dim_num)]
        shape_all = _compute_product(shape)
        if shape_all < min_elements:
            min_range = min_elements / max(shape_all, 1)
            max_range = max_elements / max(shape_all, 1)
            idx = shape.index(min(shape))
            shape[idx] = max(1, math.ceil(min(shape) * random.uniform(min_range, max_range)))
        shape_all = _compute_product(shape)
        if shape_all <= max_elements and shape_all >= min_elements:
            break
    return shape


def _shape_rule_min(dim_num, max_elements, min_elements):
    min_value_list = [7, 32, 64, 65, 127, 128, 257]
    for _ in range(_SHAPE_MAX_ITERATIONS):
        min_value = random.choice(min_value_list)
        shape_value_min = min(math.floor(math.pow(max_elements, 1 / dim_num)), min_value)
        shape_value_range = [max(shape_value_min, 1)] * dim_num
        shape = [random.randint(2, shape_value_range[i]) for i in range(dim_num)]
        shape_all = _compute_product(shape)
        if shape_all < min_elements:
            min_range = min_elements / max(shape_all, 1)
            max_range = max_elements / max(shape_all, 1)
            idx = shape.index(min(shape))
            shape[idx] = max(1, math.ceil(min(shape) * random.uniform(min_range, max_range)))
        shape_all = _compute_product(shape)
        if shape_all <= max_elements and shape_all >= min_elements:
            break
    return shape


_SHAPE_RULE_MAP = {
    "avg": _shape_rule_avg,
    "shuffle": _shape_rule_shuffle,
    "max": _shape_rule_max,
    "split_dim": _shape_rule_split_dim,
    "min": _shape_rule_min,
}


def generate_random_shape(
    dimensions: int, num_segments: int = NUM_LOG_SEGMENTS, seed: Optional[int] = None,
    dtype: Optional[str] = None, rule: Optional[str] = None, chose_range: Optional[float] = None
) -> List[int]:
    """
    根据输入维度生成随机shape，参照TestCaseGenerator的shape泛化规则

    生成策略：
    1. 根据chose_range或权重随机选择shape大小区间
    2. 根据rule或随机选择shape生成规则（avg/shuffle/max/split_dim/min）
    3. 5种规则的shape特征：
       - avg: 各轴均匀分布
       - shuffle: 各轴不等分布，维度顺序打乱
       - max: 至少一轴取值在1000~9999
       - split_dim: block轴[64,267]，模拟UB/Block切分
       - min: 小shape，轴上限从[7,32,64,65,127,128,257]随机取

    Shape大小区间占比：
    - 85%: 小-中shape (2 ~ 100M/dtype_byte)
    - 5%:  中shape (100M ~ 500M/dtype_byte)
    - 5%:  中大shape (100M ~ 500M/dtype_byte)
    - 4%:  大shape (500M ~ 1G/dtype_byte)
    - 1%:  超大shape (1G ~ 2G/dtype_byte)

    约束：
    - shape乘积 <= MAX_SHAPE_PRODUCT (2G)
    - 单轴取值范围 [1, MAX_DIM_VALUE]
    - 维度数 <= MAX_DIMENSIONS (8)

    Args:
        dimensions: shape的维度数（0-8），0 表示标量 tensor 返回 []
        num_segments: 对数分段数量（仅rule="original"时使用）
        seed: 随机种子（可选）
        dtype: 数据类型（可选），用于计算dtype字节影响shape大小上限
        rule: shape生成规则（可选），"avg"/"shuffle"/"max"/"split_dim"/"min"/"original"
        chose_range: shape大小区间选择比例（可选），0.0~1.0

    Returns:
        随机生成的shape列表
    """
    if seed is not None:
        random.seed(seed)

    if dimensions == 0:
        return []
    if not isinstance(dimensions, int) or dimensions <= 0 or dimensions > MAX_DIMENSIONS:
        corrected = max(1, min(abs(int(dimensions)) if isinstance(dimensions, (int, float)) else 1, MAX_DIMENSIONS))
        dimensions = corrected
    else:
        dimensions = max(1, min(dimensions, MAX_DIMENSIONS))

    if rule == "original":
        if dimensions == 1:
            log_min = 0
            log_max = math.log2(MAX_SHAPE_PRODUCT)
            log_val = random.uniform(log_min, log_max)
            return [max(1, int(2**log_val))]
        log_min = 0
        log_max = math.log2(MAX_SHAPE_PRODUCT)
        log_segment_size = (log_max - log_min) / num_segments
        segment_idx = random.randint(0, num_segments - 1)
        segment_log_min = log_min + segment_idx * log_segment_size
        segment_log_max = segment_log_min + log_segment_size
        target_log = random.uniform(segment_log_min, segment_log_max)
        target_product = int(2**target_log)
        target_product = max(dimensions, target_product)
        target_product = min(target_product, MAX_SHAPE_PRODUCT)
        shape = _decompose_product_to_shape(target_product, dimensions)
        return shape

    dtype_byte = _get_dtype_byte(dtype) if dtype else 1
    min_elements, max_elements = _select_size_interval(dtype_byte, chose_range)

    if rule is not None and rule in _SHAPE_RULE_MAP:
        rule_func = _SHAPE_RULE_MAP[rule]
    else:
        rule_name = random.choice(_SHAPE_RULE_NAMES)
        rule_func = _SHAPE_RULE_MAP[rule_name]

    shape = rule_func(dimensions, max_elements, min_elements)
    shape = [max(1, min(d, MAX_DIM_VALUE)) for d in shape]

    return shape


def _decompose_product_to_shape(target_product: int, dimensions: int) -> List[int]:
    """
    将目标乘积分解为指定维度的shape

    分解策略：
    1. 使用对数均匀分布来分配各维度的值
    2. 先生成各维度的对数值，然后转换为实际值
    3. 调整使乘积精确匹配目标值

    Args:
        target_product: 目标乘积
        dimensions: 维度数

    Returns:
        分解后的shape列表
    """
    if dimensions == 1:
        return [target_product]

    # 策略：使用随机分解
    # 1. 随机生成各个维度的"权重"
    # 2. 根据权重分配乘积

    shape = []

    # 方法1：逐步分解法
    remaining_product = target_product
    remaining_dims = dimensions

    for i in range(dimensions - 1):
        # 计算当前维度的最大可能值
        # 确保剩余乘积至少能分配给剩余维度（每维至少为1）
        max_for_this_dim = remaining_product // (remaining_dims)

        if max_for_this_dim <= 1:
            shape.append(1)
            remaining_dims -= 1
            continue

        # 使用对数均匀分布来选择当前维度的值
        # 这样可以产生更多样化的维度值分布
        log_min = 0  # log(1) = 0
        log_max = math.log2(max_for_this_dim)

        # 在对数空间均匀采样
        log_val = random.uniform(log_min, log_max)
        dim_value = max(1, min(max_for_this_dim, int(2**log_val)))

        shape.append(dim_value)
        remaining_product //= dim_value
        remaining_dims -= 1

    # 最后一个维度取剩余值
    shape.append(max(1, remaining_product))

    # 微调：如果乘积不匹配，调整最后一个维度
    actual_product = 1
    for d in shape[:-1]:
        actual_product *= d

    if actual_product > 0:
        last_dim = target_product // actual_product
        shape[-1] = max(1, last_dim)

    # 确保单轴值不超过最大值
    shape = [min(d, MAX_DIM_VALUE) for d in shape]

    return shape


def generate_random_shapes(
    dimensions: int,
    count: int = 10,
    num_segments: int = NUM_LOG_SEGMENTS,
    seed: Optional[int] = None,
) -> List[List[int]]:
    """
    批量生成随机shape

    Args:
        dimensions: shape的维度数
        count: 需要生成的shape数量
        num_segments: 对数分段数量
        seed: 随机种子

    Returns:
        随机shape列表

    Examples:
        >>> shapes = generate_random_shapes(3, count=5, seed=42)
        >>> len(shapes)
        5
        >>> all(len(s) == 3 for s in shapes)
        True
    """
    if seed is not None:
        random.seed(seed)

    shapes = []
    for _ in range(count):
        shape = generate_random_shape(dimensions, num_segments)
        shapes.append(shape)

    return shapes


def generate_diverse_random_shapes(
    dimensions_list: List[int],
    count_per_dim: int = 5,
    num_segments: int = NUM_LOG_SEGMENTS,
    seed: Optional[int] = None,
) -> List[List[int]]:
    """
    为多个维度生成多样化的随机shape

    Args:
        dimensions_list: 维度数列表，如[1, 2, 3, 4]
        count_per_dim: 每个维度生成的shape数量
        num_segments: 对数分段数量
        seed: 随机种子

    Returns:
        随机shape列表

    Examples:
        >>> shapes = generate_diverse_random_shapes([1, 2, 3], count_per_dim=2, seed=42)
        >>> len(shapes)
        6
    """
    if seed is not None:
        random.seed(seed)

    all_shapes = []
    for dims in dimensions_list:
        shapes = generate_random_shapes(dims, count_per_dim, num_segments)
        all_shapes.extend(shapes)

    return all_shapes


def generate_random_value_by_dtype(
    dtype: str,
    value_range: Optional[List[Union[int, float]]] = None,
    seed: Optional[int] = None
) -> Union[int, float, bool]:
    """
    按照数据类型和取值区间生成随机数

    Args:
        dtype: 数据类型（如 "float32", "int32", "bool" 等）
        value_range: 取值区间 [min, max]，如果为None则使用dtype的默认范围
        seed: 随机种子（可选）

    Returns:
        根据数据类型生成的随机值

    Examples:
        >>> generate_random_value_by_dtype("int32", [0, 100], seed=42)
        82
        >>> generate_random_value_by_dtype("float32", [0.0, 1.0], seed=42)
        0.6394267984578837
        >>> generate_random_value_by_dtype("bool", seed=42)
        False
    """
    if seed is not None:
        random.seed(seed)

    normalized = normalize_dtype(dtype)
    if normalized is None:
        raise ValueError(f"Unsupported dtype: {dtype}")

    dtype_ranges = {
        "int8": (-128, 127),
        "uint8": (0, 255),
        "int16": (-32768, 32767),
        "uint16": (0, 65535),
        "int32": (-2147483648, 2147483647),
        "uint32": (0, 4294967295),
        "int64": (-9223372036854775808, 9223372036854775807),
        "uint64": (0, 18446744073709551615),
        "float16": (-65504.0, 65504.0),
        "float32": (-3.4028235e38, 3.4028235e38),
        "float64": (-1.7976931348623157e308, 1.7976931348623157e308),
        "bfloat16": (-3.3895313892515355e38, 3.3895313892515355e38),
        "hifloat4": (-6, 6),
        "hifloat4_scale": (-32768, 32768),
    }

    if normalized == "bool":
        if value_range is not None and len(value_range) == 2:
            min_val, max_val = value_range[0], value_range[1]
            if min_val == max_val:
                return bool(min_val)
            return random.choice([True, False])
        return random.choice([True, False])

    if value_range is None or len(value_range) != 2:
        value_range = dtype_ranges.get(normalized, (0, 100))

    min_val, max_val = value_range[0], value_range[1]

    def _parse_special_value(v):
        if isinstance(v, str):
            v_lower = v.lower().strip()
            if v_lower == 'inf' or v_lower == '+inf':
                return float('inf')
            elif v_lower == '-inf':
                return float('-inf')
            elif v_lower == 'nan':
                return float('nan')
        return v

    min_val = _parse_special_value(min_val)
    max_val = _parse_special_value(max_val)

    if min_val == max_val:
        if isinstance(min_val, float) and (min_val != min_val):
            return float('nan')
        if normalized in INTEGER_DTYPES:
            return int(min_val)
        return float(min_val)

    if normalized in INTEGER_DTYPES:
        return random.randint(int(min_val), int(max_val))
    elif normalized in FLOAT_DTYPES:
        return random.uniform(float(min_val), float(max_val))
    elif normalized in COMPLEX_DTYPES:
        real = random.uniform(float(min_val), float(max_val))
        imag = random.uniform(float(min_val), float(max_val))
        return f"({real}+{imag}j)"
    else:
        return random.uniform(float(min_val), float(max_val))


def _can_broadcast_single_dim(source_dim: int, target_dim: int) -> bool:
    """
    判断单个维度是否可以broadcast

    规则：source_dim == target_dim 或 source_dim == 1
    """
    return source_dim == target_dim or source_dim == 1


def can_broadcast_to(source_shape: List[int], target_shape: List[int]) -> bool:
    """
    判断source_shape是否可以broadcast到target_shape

    Broadcast规则：
    1. 从后往前对齐维度
    2. 每个维度必须相等，或者source维度为1
    3. source维度数可以少于target

    Args:
        source_shape: 源shape
        target_shape: 目标shape

    Returns:
        是否可以broadcast

    Examples:
        >>> can_broadcast_to([1, 3], [2, 3])
        True
        >>> can_broadcast_to([3], [2, 3])
        True
        >>> can_broadcast_to([2, 3], [2, 3])
        True
        >>> can_broadcast_to([2, 4], [2, 3])
        False
    """
    source_rev = list(reversed(source_shape))
    target_rev = list(reversed(target_shape))

    for i in range(max(len(source_rev), len(target_rev))):
        if i >= len(source_rev):
            continue
        if i >= len(target_rev):
            return False

        s = source_rev[i]
        t = target_rev[i]

        if not _can_broadcast_single_dim(s, t):
            return False

    return True


def get_broadcast_result(shapes: List[List[int]]) -> Optional[List[int]]:
    """
    根据多个shape计算broadcast后的结果shape

    Broadcast规则：
    1. 从后往前对齐维度
    2. 每个维度取最大值
    3. 如果某个维度不兼容（都不为1且不相等），返回None

    Args:
        shapes: shape列表

    Returns:
        broadcast后的shape，如果不兼容则返回None

    Examples:
        >>> get_broadcast_result([[1, 3], [2, 3]])
        [2, 3]
        >>> get_broadcast_result([[3], [2, 3]])
        [2, 3]
        >>> get_broadcast_result([[2, 1], [1, 3]])
        [2, 3]
        >>> get_broadcast_result([[2, 3], [3, 4]])
        None
    """
    if not shapes:
        return None

    if len(shapes) == 1:
        return shapes[0]

    # 找到最大维度数
    max_dims = max(len(s) for s in shapes)

    result = []

    for i in range(max_dims):
        dim_values = []
        for shape in shapes:
            idx = len(shape) - 1 - i
            if idx >= 0:
                dim_values.append(shape[idx])

        # 0 是真实维度（不可广播），1 才可广播；与非 1 且不相等的维度一样视为不兼容
        max_dim = None
        for d in dim_values:
            if d == 1:
                continue
            if max_dim is None:
                max_dim = d
            elif max_dim != d:
                return None
        if max_dim is None:
            max_dim = 1
        result.append(max_dim)

    return list(reversed(result))


def generate_broadcast_shapes(
    source_shape: List[int], seed: Optional[int] = None
) -> List[int]:
    """
    根据输入shape生成满足broadcast关系的shape

    Broadcast规则：从后往前对齐维度，每个维度必须相等或其中一方为1。

    Broadcast场景（生成的shape与source_shape满足双向broadcast关系之一）：
    | 场景 | 说明 | 示例source | 生成的shape | broadcast方向 |
    |------|------|-----------|-------------|---------------|
    | 相等 | 与输入shape完全相等 | [2,3,4] | [2,3,4] | 双向相等 |
    | 维度少 | 维度数小于source，某些轴为1 | [2,3,4] | [4], [3,4], [1,4] | 生成→source |
    | 维度多 | 维度数大于source | [2,3,4] | [6,2,3,4] | source→生成 |
    | 维度相等 | 某些轴设为1 | [2,3,4] | [1,3,4], [2,1,4] | 生成→source |
    | 扩展1轴 | source中为1的轴变非1 | [1,3,1] | [2,3,4], [5,3,8] | source→生成 |

    约束：
    - shape乘积小于2G
    - 单轴取值范围1~2G
    - 最大维度数8

    Args:
        source_shape: 输入shape
        seed: 随机种子（可选）

    Returns:
        满足broadcast关系的shape，从5种场景种随机选择一个场景生成并返回
    """
    # 1. 初始化随机种子
    if seed is not None:
        random.seed(seed)
    
    # 2. 校验输入合法性
    if not isinstance(source_shape, list) or not all(isinstance(x, int) and x >= 1 for x in source_shape):
        raise ValueError("source_shape必须是由正整数组成的列表")
    if len(source_shape) > MAX_DIMENSIONS:
        raise ValueError(f"source_shape维度数不能超过{MAX_DIMENSIONS}")
    
    # 3. 核心辅助函数：校验两个shape是否满足broadcast规则
    def is_broadcast_compatible(shape1: List[int], shape2: List[int]) -> bool:
        """检查shape1和shape2是否满足广播规则"""
        # 从后往前对齐维度
        for dim1, dim2 in zip(reversed(shape1), reversed(shape2)):
            if dim1 != dim2 and dim1 != 1 and dim2 != 1:
                return False
        return True
    
    # 4. 辅助函数：计算shape乘积
    def product(shape: List[int]) -> int:
        if not shape:
            return 1
        prod = 1
        for val in shape:
            prod *= val
            if prod > MAX_SHAPE_PRODUCT:
                break
        return prod
    
    # 5. 辅助函数：校验生成的shape是否满足所有约束（含广播兼容性）
    def is_valid(shape: List[int]) -> bool:
        # 约束1：维度数≤8
        if len(shape) > MAX_DIMENSIONS:
            return False
        # 约束2：单轴取值1~2G
        if any(val < MIN_DIM_VALUE or val > MAX_DIM_VALUE for val in shape):
            return False
        # 约束3：乘积<2G
        if product(shape) >= MAX_SHAPE_PRODUCT:
            return False
        # 约束4：必须与source_shape满足广播规则
        if not is_broadcast_compatible(shape, source_shape):
            return False
        return True
    
    # 6. 定义5种场景的生成函数（全场景边界修复）
    def _scene_equal() -> List[int]:
        """场景1：与source_shape完全相等"""
        return source_shape.copy()
    
    def _scene_less_dims() -> List[int]:
        """场景2：维度数小于source，从后往前对齐，可选轴设为1"""
        source_dim = len(source_shape)
        # 边界：source_dim=1时，无法生成更少维度，返回[1]（兼容广播）
        if source_dim == 1:
            return [1]
        # 随机选择生成的维度数（1 ~ source_dim-1）
        gen_dim = random.randint(1, source_dim - 1)
        # 从source_shape末尾取gen_dim个维度，随机将部分轴设为1
        gen_shape = source_shape[-gen_dim:].copy()
        # 随机选择0~gen_dim个轴设为1
        axes_to_1 = random.sample(range(gen_dim), k=random.randint(0, gen_dim))
        for idx in axes_to_1:
            gen_shape[idx] = 1
        return gen_shape
    
    def _scene_more_dims() -> List[int]:
        """场景3：维度数大于source（但不超过8），前面新增随机正整数轴（边界修复）"""
        source_dim = len(source_shape)
        # 边界：source_dim已达MAX_DIMENSIONS，无法生成更多维度，返回场景1结果
        if source_dim >= MAX_DIMENSIONS:
            return _scene_equal()
        # 随机选择生成的维度数（source_dim+1 ~ MAX_DIMENSIONS）
        gen_dim = random.randint(source_dim + 1, MAX_DIMENSIONS)
        # 前面新增的轴取1~MAX_DIM_VALUE之间的随机正整数（保证乘积<2G）
        prefix_dims = []
        remaining_product = MAX_SHAPE_PRODUCT // (product(source_shape) if source_shape else 1)
        for _ in range(gen_dim - source_dim):
            # 确保新增轴的取值不超过剩余乘积上限
            max_val = min(MAX_DIM_VALUE, remaining_product)
            val = random.randint(1, max_val)
            prefix_dims.append(val)
            remaining_product = max(1, remaining_product // val)
        # 拼接前缀轴和source_shape
        gen_shape = prefix_dims + source_shape.copy()
        return gen_shape
    
    def _scene_same_dims() -> List[int]:
        """场景4：维度数与source相等，随机将部分轴设为1"""
        gen_shape = source_shape.copy()
        # 至少选择1个轴设为1（避免与场景1重复）
        axes_to_1 = random.sample(range(len(gen_shape)), k=random.randint(1, len(gen_shape)))
        for idx in axes_to_1:
            gen_shape[idx] = 1
        return gen_shape
    
    def _scene_expand_1d() -> List[int]:
        """场景5：source中为1的轴替换为非1的随机正整数（保证广播兼容）"""
        # 先检查source_shape是否有1的轴，无则跳过该场景（避免生成不兼容shape）
        one_axes = [idx for idx, val in enumerate(source_shape) if val == 1]
        if not one_axes:
            # 无1轴时，场景5无法生成兼容shape，返回场景1的结果（兜底）
            return _scene_equal()
        
        gen_shape = source_shape.copy()
        # 将所有1的轴替换为非1的随机正整数（保证乘积<2G + 广播兼容）
        remaining_product = MAX_SHAPE_PRODUCT // (product([v for v in gen_shape if v != 1]) if gen_shape else 1)
        for idx in one_axes:
            max_val = min(MAX_DIM_VALUE, remaining_product)
            # 确保替换后的值>1且<=max_val
            val = random.randint(2, max_val) if max_val >= 2 else 2
            gen_shape[idx] = val
            remaining_product = max(1, remaining_product // val)
        return gen_shape
    
    # 7. 过滤不可用场景（避免选择无法生成的场景）
    source_dim = len(source_shape)
    available_scenes = []
    # 场景1：始终可用
    available_scenes.append(_scene_equal)
    # 场景2：source_dim>1时可用
    if source_dim > 1:
        available_scenes.append(_scene_less_dims)
    # 场景3：source_dim<MAX_DIMENSIONS时可用
    if source_dim < MAX_DIMENSIONS:
        available_scenes.append(_scene_more_dims)
    # 场景4：始终可用
    available_scenes.append(_scene_same_dims)
    # 场景5：source有1轴时可用
    if any(val == 1 for val in source_shape):
        available_scenes.append(_scene_expand_1d)
    
    # 8. 随机选择可用场景生成shape，若不满足约束则重试
    max_retries = 1000  # 最大重试次数，避免死循环
    retries = 0
    gen_shape = []
    
    while retries < max_retries:
        # 随机选择一个可用场景
        selected_scene = random.choice(available_scenes)
        gen_shape = selected_scene()
        # 校验约束（含广播兼容性）
        if is_valid(gen_shape):
            break
        retries += 1
    
    if retries >= max_retries:
        raise RuntimeError("超出最大重试次数，无法生成满足约束的shape")
    
    return gen_shape


def generate_unidirectional_broadcast_shapes(
    shape1: List[int], seed: Optional[int] = None
) -> List[int]:
    """
    根据目标shape1获取可推导(broadcast)至目标shape1的shape2（仅保证shape2→shape1可广播）

    Broadcast规则：从后往前对齐维度，每个维度必须相等或其中一方为1。

    Broadcast场景：
    | 场景 | 说明 | 示例source | 生成的shape |
    |------|------|-----------|-------------|
    | 相等 | 与输入shape完全相等 | [2,3,4] | [2,3,4] |
    | 维度少 | 维度数小于source，某些轴为1 | [2,3,4] | [4], [3,4], [1,4] |
    | 维度相等 | 某些轴设为1 | [2,3,4] | [1,3,4], [2,1,4] | 生成→source |

    约束：
    - shape乘积小于2G
    - 单轴取值范围1~2G
    - 最大维度数8

    返回 ：
    - 仅保证shape2能broadcast至shape1（无需限制shape1反向广播）

    Args:
        shape1: 目标广播形状
        seed: 随机种子

    Returns:
        满足广播规则+约束的shape2
    """
    # 1. 初始化随机种子
    if seed is not None:
        random.seed(seed)
    
    # 2. 输入合法性校验
    if not isinstance(shape1, list) or not all(isinstance(x, int) and x >= 1 for x in shape1):
        raise ValueError("shape1必须是由正整数组成的列表")
    if len(shape1) > MAX_DIMENSIONS:
        raise ValueError(f"shape1维度数不能超过{MAX_DIMENSIONS}")
    
    # 3. 核心辅助函数：判断a是否能广播到b（标准广播规则）
    def can_broadcast(a: List[int], b: List[int]) -> bool:
        """检查a是否能广播到b（按numpy/pytorch广播规则）"""
        max_dim = max(len(a), len(b))
        # 补1对齐维度数
        a_padded = [1] * (max_dim - len(a)) + a
        b_padded = [1] * (max_dim - len(b)) + b
        
        # 逐维校验：相等 或 其中一方为1
        for dim_a, dim_b in zip(a_padded, b_padded):
            if dim_a != dim_b and dim_a != 1 and dim_b != 1:
                return False
        return True
    
    # 4. 辅助函数：计算shape乘积（用于约束校验）
    def calc_product(shape: List[int]) -> int:
        prod = 1
        for val in shape:
            prod *= val
            if prod > MAX_SHAPE_PRODUCT:
                break
        return prod
    
    # 5. 辅助函数：校验shape是否满足所有约束
    def is_valid_shape(shape: List[int]) -> bool:
        # 约束1：维度数≤8
        if len(shape) > MAX_DIMENSIONS:
            return False
        # 约束2：单轴取值1~2G
        if any(val < MIN_DIM_VALUE or val > MAX_DIM_VALUE for val in shape):
            return False
        # 约束3：乘积<2G
        if calc_product(shape) >= MAX_SHAPE_PRODUCT:
            return False
        return True
    
    # 6. 定义3种广播场景的生成函数
    def _scene_equal() -> List[int]:
        """场景1：与shape1完全相等"""
        return shape1.copy()
    
    def _scene_less_dims() -> List[int]:
        """场景2：维度数小于shape1，从后往前对齐，可选轴设为1"""
        shape1_dim = len(shape1)
        # 1维时特殊处理：返回[1]（唯一合法的少维度值）
        if shape1_dim == 1:
            return [1]
        # 多维时随机选择维度数（1 ~ shape1_dim-1）
        gen_dim = random.randint(1, shape1_dim - 1)
        # 从shape1末尾取gen_dim个维度，随机将部分轴设为1
        gen_shape = shape1[-gen_dim:].copy()
        # 随机选择0~gen_dim个轴设为1
        axes_to_1 = random.sample(range(gen_dim), k=random.randint(0, gen_dim))
        for idx in axes_to_1:
            gen_shape[idx] = 1
        return gen_shape
    
    def _scene_same_dims() -> List[int]:
        """场景3：维度数与shape1相等，随机将部分轴设为1"""
        gen_shape = shape1.copy()
        # 随机选择1~所有轴设为1（至少1个，避免与场景1重复）
        axes_to_1 = random.sample(range(len(gen_shape)), k=random.randint(1, len(gen_shape)))
        for idx in axes_to_1:
            gen_shape[idx] = 1
        return gen_shape
    
    # 7. 随机选择场景生成shape2，直到满足所有约束+广播规则
    scenes = [_scene_equal, _scene_less_dims, _scene_same_dims]
    max_retries = 1000  # 最大重试次数，避免死循环
    retries = 0
    shape2 = []
    
    while retries < max_retries:
        # 随机选择一个场景
        selected_scene = random.choice(scenes)
        shape2 = selected_scene()
        # 校验：约束合法 + shape2能广播到shape1
        if is_valid_shape(shape2) and can_broadcast(shape2, shape1):
            break
        retries += 1
    
    if retries >= max_retries:
        raise RuntimeError("超出最大重试次数，无法生成满足约束的广播shape2")
    
    return shape2
