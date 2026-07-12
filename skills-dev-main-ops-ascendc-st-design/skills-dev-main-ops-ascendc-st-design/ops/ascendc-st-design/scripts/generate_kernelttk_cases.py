#!/usr/bin/env python3
#
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
#
"""
Kernel TTK 用例格式转换模块
提供 convert_to_aclnn_kernel_format 及相关格式转换、校验、修复函数
供 generate_test_cases.py 在 csv_mode='kernel' 时调用
"""

import sys
import os
import re
import math
import random
import numpy as np
import pandas as pd
from ast import literal_eval

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import normalize_dtype, get_dtype_category

ARRAY_TYPES = ('aclIntArray', 'aclFloatArray', 'aclBoolArray', 'aclScalarList')

ACL_DTYPE_ENUM_MAP = {
    "float32": 0, "float16": 1, "int8": 2, "int32": 3, "uint8": 4,
    "int16": 5, "uint16": 6, "uint32": 7, "int64": 8, "uint64": 9,
    "float64": 10, "bool": 11, "string": 12, "complex64": 13,
    "complex128": 14, "bfloat16": 27, "int4": 29, "uint1": 30,
    "complex32": 32, "hifloat8": 33, "float8_e5m2": 35,
    "float8_e4m3fn": 36, "float8_e8m0": 37, "float6_e3m2": 38,
    "float6_e2m3": 39, "float4_e2m1": 40, "float4_e1m2": 41,
    "hifloat4": 42, "hifloat4_scale": 43,
}

ACLNN_KERNEL_COLUMNS = [
    'testcase_name', 'network_name', 'op_name',
    'input_shapes', 'input_dtypes', 'input_formats',
    'output_shapes', 'output_dtypes', 'output_formats',
    'input_ori_shapes', 'input_ori_formats',
    'output_ori_shapes', 'output_ori_formats',
    'attributes', 'input_data_ranges',
    'precision_tolerances', 'absolute_precision',
    'output_inplace_indexes', 'output_shape_unknown_indexes',
    'is_enabled', 'remark', 'soc_series', 'priority',
    'dump_file_prefix', 'manual_input_binaries', 'manual_golden_binaries',
]


# ==================== 辅助函数 ====================

def _is_safe_na(val):
    if isinstance(val, (list, tuple, dict)):
        return False
    try:
        result = pd.isna(val)
        return bool(result) if not isinstance(result, (list, tuple, np.ndarray)) else False
    except (ValueError, TypeError):
        return False


def parse_list_value(value):
    if isinstance(value, str):
        try:
            return literal_eval(value)
        except (ValueError, SyntaxError):
            return value
    return value


def _pick_single_range(value_range):
    if not value_range:
        return [-2, 2]
    if isinstance(value_range, (list, tuple)) and len(value_range) > 0:
        if isinstance(value_range[0], (list, tuple)):
            return random.choice(value_range)
    return value_range


def _resolve_value_range(row, param_name, dtype):
    vr_dtype_key = f"{param_name}.value_range_{dtype}"
    vr_dtype_val = row.get(vr_dtype_key)
    if vr_dtype_val is not None and not _is_safe_na(vr_dtype_val):
        parsed = parse_list_value(vr_dtype_val)
        if isinstance(parsed, list):
            return parsed
    value_range_raw = row.get(f"{param_name}.value_range", '[]')
    if _is_safe_na(value_range_raw):
        return [[0, 1]]
    parsed = parse_list_value(value_range_raw)
    if not isinstance(parsed, list):
        return [[0, 1]]
    return parsed


def _is_valid_value(value):
    if value is None:
        return False
    if isinstance(value, str) and value == '':
        return False
    if isinstance(value, float) and math.isnan(value):
        return True
    try:
        if not pd.notna(value):
            return False
    except (ValueError, TypeError):
        pass
    return True


# ==================== 格式化函数 ====================

def _format_number(x):
    if isinstance(x, float):
        if x == float('inf'):
            return 'float("inf")'
        elif x == float('-inf'):
            return 'float("-inf")'
        elif x != x:
            return 'float("nan")'
    elif isinstance(x, str):
        if x == 'inf':
            return 'float("inf")'
        elif x == '-inf':
            return 'float("-inf")'
        elif x == 'nan':
            return 'float("nan")'
    return str(x)


def format_aclnn_shapes(items):
    if not items:
        return "()"
    parts = []
    for item in items:
        if item is None:
            parts.append("None")
        elif isinstance(item, (list, tuple)):
            if len(item) == 0:
                parts.append("()")
            elif isinstance(item[0], (list, tuple)):
                inner_parts = []
                for sub in item:
                    if isinstance(sub, (list, tuple)):
                        if len(sub) == 0:
                            inner_parts.append("()")
                        else:
                            inner_parts.append("(" + ",".join(str(x) for x in sub) + ",)")
                    else:
                        inner_parts.append(str(sub))
                parts.append("(" + ",".join(inner_parts) + ",)")
            else:
                inner = ",".join(str(x) for x in item)
                parts.append(f"({inner},)")
        else:
            parts.append(str(item))
    return "(" + ",".join(parts) + ",)"


def format_aclnn_dtypes(dtypes):
    if not dtypes:
        return ""
    formatted = []
    for d in dtypes:
        if isinstance(d, (list, tuple)):
            inner = ",".join(f"'{x}'" for x in d)
            formatted.append(f"({inner},)")
        elif d is None:
            formatted.append("None")
        else:
            formatted.append(f"'{d}'")
    return "(" + ",".join(formatted) + ",)"


def format_aclnn_formats(formats):
    if not formats:
        return ""
    formatted = []
    for f in formats:
        if isinstance(f, (list, tuple)):
            inner = ",".join(f"'{x}'" for x in f)
            formatted.append(f"({inner},)")
        elif f is None:
            formatted.append("None")
        else:
            formatted.append(f"'{f}'")
    return "(" + ",".join(formatted) + ",)"


def format_aclnn_ranges(ranges):
    if not ranges:
        return ""
    parts = []
    for rng in ranges:
        if rng is None:
            parts.append("None")
        elif isinstance(rng, (list, tuple)):
            if len(rng) == 0:
                parts.append("((),)")
            elif isinstance(rng[0], (list, tuple)):
                inner_parts = []
                for sub in rng:
                    if isinstance(sub, (list, tuple)):
                        inner_parts.append("(" + ",".join(_format_number(x) for x in sub) + ",)")
                    else:
                        inner_parts.append(_format_number(sub))
                parts.append("(" + ",".join(inner_parts) + ",)")
            else:
                inner = ",".join(_format_number(x) for x in rng)
                parts.append(f"({inner},)")
        else:
            parts.append(_format_number(rng))
    return "(" + ",".join(parts) + ",)"


def format_aclnn_tuple(items):
    if not items:
        return "()"
    return "(" + ",".join(str(x) for x in items) + ",)"


def _python_literal_value(v):
    if v is None:
        return 'None'
    if isinstance(v, bool):
        return 'True' if v else 'False'
    if isinstance(v, (int,)):
        return str(v)
    if isinstance(v, float):
        if v == float('inf'):
            return 'float("inf")'
        elif v == float('-inf'):
            return 'float("-inf")'
        elif v != v:
            return 'float("nan")'
        return str(v)
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, (list, tuple)):
        items = ",".join(_python_literal_value(x) for x in v)
        return f"[{items}]"
    if isinstance(v, dict):
        items = ",".join(f'{_python_literal_value(k)}:{_python_literal_value(val)}' for k, val in v.items())
        return "{" + items + "}"
    if isinstance(v, complex):
        return f"({v.real}+{v.imag}j)"
    if isinstance(v, np.ndarray):
        return _python_literal_value(v.tolist())
    return str(v)


def format_aclnn_attributes(attrs_dict):
    if not attrs_dict:
        return "{}"
    items = ",".join(f"'{k}':{_python_literal_value(v)}" for k, v in attrs_dict.items())
    return "{" + items + "}"


def format_aclnn_attr_value(value, param_type):
    if isinstance(value, (list, tuple, np.ndarray)):
        if len(value) == 0:
            return []
        return list(value) if not isinstance(value, list) else value
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return value
    try:
        if pd.isna(value):
            return ''
    except (ValueError, TypeError):
        pass
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value in ('None', 'True', 'False'):
            return value
        try:
            parsed = literal_eval(value)
            if isinstance(parsed, (list, tuple)):
                return list(parsed)
            if isinstance(parsed, (int, float)) and not isinstance(parsed, bool):
                return parsed
            return value
        except (ValueError, SyntaxError):
            return value
    try:
        parsed = literal_eval(str(value))
        if isinstance(parsed, (list, tuple)):
            return list(parsed)
        return parsed
    except (ValueError, SyntaxError):
        return str(value)


def _get_precision_for_dtype(dtype):
    cat = get_dtype_category(dtype)
    if cat == 'integer':
        return {"precision_tolerances": "((0, 0),)", "absolute_precision": 0.0}
    elif cat == 'float':
        if dtype in ('bfloat16', 'float16', 'hifloat8', 'float8_e5m2', 'float8_e4m3fn',
                      'float4_e2m1', 'float4_e1m2', 'hifloat4', 'float6_e3m2', 'float6_e2m3'):
            return {"precision_tolerances": "", "absolute_precision": 1e-08}
        return {"precision_tolerances": "", "absolute_precision": 1e-08}
    elif cat == 'complex':
        return {"precision_tolerances": "", "absolute_precision": 1e-08}
    return {"precision_tolerances": "", "absolute_precision": ""}


# ==================== Kernel 格式转换 ====================

def convert_to_aclnn_kernel_format(df, param_def, aclnn_name, case_level):
    cases = []
    _skip_keys = {'operator_name', 'aclnn_name', 'parameters'}

    for idx, row in df.iterrows():
        input_shapes = []
        input_dtypes = []
        input_formats = []
        input_ranges = []
        output_shapes = []
        output_dtypes = []
        output_formats = []
        output_inplace_indexes = []
        attrs_dict = {}
        output_dtype_set = set()

        for param_name, param_info in param_def.items():
            if param_name in _skip_keys or not isinstance(param_info, dict):
                continue
            io_type = param_info.get('io_type', 'input')
            param_type = param_info.get('type', '')
            exist_col = f"{param_name}.exist"
            is_absent = exist_col in row.index and row[exist_col] == False

            if param_type == 'aclTensor' and io_type == 'input':
                if is_absent:
                    input_shapes.append(None)
                    dtype = row.get(f"{param_name}.dtype")
                    if dtype is None or _is_safe_na(dtype):
                        p_info = param_def.get(param_name, {})
                        dtypes_list = [d['dtype'] for d in p_info.get('dtype_with_values', [])] or [d['dtype'] for d in p_info.get('dtype_with_ranges', [])]
                        dtype = dtypes_list[0] if dtypes_list else 'float32'
                    dtype = normalize_dtype(dtype) or dtype
                    value_range = _resolve_value_range(row, param_name, dtype)
                    fmt = row.get(f"{param_name}.format", 'ND')
                    if pd.isna(fmt):
                        fmt = 'ND'
                    input_dtypes.append(dtype)
                    input_formats.append(fmt)
                    input_ranges.append(_pick_single_range(value_range))
                else:
                    shape = parse_list_value(row.get(f"{param_name}.shape", '[]'))
                    dtype = row.get(f"{param_name}.dtype", 'float32')
                    if pd.isna(dtype):
                        dtype = 'float32'
                    dtype = normalize_dtype(dtype) or dtype
                    value_range = _resolve_value_range(row, param_name, dtype)
                    fmt = row.get(f"{param_name}.format", 'ND')
                    input_shapes.append(shape)
                    input_dtypes.append(dtype)
                    input_formats.append(fmt)
                    input_ranges.append(_pick_single_range(value_range))
                if param_info.get('in_place', False):
                    output_inplace_indexes.append(len(input_shapes) - 1)

            elif param_type == 'aclTensorList' and io_type == 'input':
                if is_absent:
                    input_shapes.append(None)
                    dtype = row.get(f"{param_name}.dtype", 'float32')
                    if pd.isna(dtype):
                        dtype = 'float32'
                    dtype = normalize_dtype(dtype) or dtype
                    value_range = _resolve_value_range(row, param_name, dtype)
                    fmt = row.get(f"{param_name}.format", 'ND')
                    if pd.isna(fmt):
                        fmt = 'ND'
                    input_dtypes.append((dtype,))
                    input_formats.append((fmt,))
                    input_ranges.append((_pick_single_range(value_range),))
                else:
                    shape_list = parse_list_value(row.get(f"{param_name}.shape_list", '[]'))
                    dtype = row.get(f"{param_name}.dtype", 'float32')
                    dtype = normalize_dtype(dtype) or dtype
                    value_range = _resolve_value_range(row, param_name, dtype)
                    fmt = row.get(f"{param_name}.format", 'ND')
                    input_shapes.append(shape_list)
                    length = len(shape_list)
                    raw_dtype_list = row.get(f"{param_name}.dtype_list")
                    if isinstance(raw_dtype_list, list) and len(raw_dtype_list) == length:
                        dtype_list = [normalize_dtype(d) or dtype for d in raw_dtype_list]
                    else:
                        dtype_list = [dtype] * length
                    format_list = [fmt] * length
                    input_dtypes.append(tuple(dtype_list))
                    input_formats.append(tuple(format_list))
                    range_list = [_pick_single_range(value_range) for _ in range(length)]
                    input_ranges.append(tuple(range_list))
                if param_info.get('in_place', False):
                    output_inplace_indexes.append(len(input_shapes) - 1)

            elif param_type == 'aclTensor' and io_type == 'output':
                if is_absent:
                    output_shapes.append(None)
                    dtype = row.get(f"{param_name}.dtype", 'float32')
                    if pd.isna(dtype):
                        dtype = 'float32'
                    dtype = normalize_dtype(dtype) or dtype
                    fmt = row.get(f"{param_name}.format", 'ND')
                    if pd.isna(fmt):
                        fmt = 'ND'
                    output_dtypes.append(dtype)
                    output_formats.append(fmt)
                    output_dtype_set.add(dtype)
                else:
                    shape = parse_list_value(row.get(f"{param_name}.shape", '[]'))
                    dtype = row.get(f"{param_name}.dtype", 'float32')
                    if pd.isna(dtype):
                        dtype = 'float32'
                    dtype = normalize_dtype(dtype) or dtype
                    fmt = row.get(f"{param_name}.format", 'ND')
                    output_shapes.append(shape)
                    output_dtypes.append(dtype)
                    output_formats.append(fmt)
                    output_dtype_set.add(dtype)

            elif param_type == 'aclTensorList' and io_type == 'output':
                if is_absent:
                    output_shapes.append(None)
                    dtype = row.get(f"{param_name}.dtype", 'float32')
                    if pd.isna(dtype):
                        dtype = 'float32'
                    dtype = normalize_dtype(dtype) or dtype
                    fmt = row.get(f"{param_name}.format", 'ND')
                    if pd.isna(fmt):
                        fmt = 'ND'
                    output_dtypes.append((dtype,))
                    output_formats.append((fmt,))
                    output_dtype_set.add(dtype)
                else:
                    shape_list = parse_list_value(row.get(f"{param_name}.shape_list", '[]'))
                    dtype = row.get(f"{param_name}.dtype", 'float32')
                    dtype = normalize_dtype(dtype) or dtype
                    fmt = row.get(f"{param_name}.format", 'ND')
                    output_shapes.append(shape_list)
                    length = len(shape_list)
                    raw_dtype_list = row.get(f"{param_name}.dtype_list")
                    if isinstance(raw_dtype_list, list) and len(raw_dtype_list) == length:
                        dtype_list = [normalize_dtype(d) or dtype for d in raw_dtype_list]
                    else:
                        dtype_list = [dtype] * length
                    format_list = [fmt] * length
                    output_dtypes.append(tuple(dtype_list))
                    output_formats.append(tuple(format_list))
                    for d in dtype_list:
                        output_dtype_set.add(d)

            elif param_type == 'aclScalar':
                if not is_absent:
                    value = row.get(f"{param_name}.value", '')
                    if _is_valid_value(value):
                        attrs_dict[param_name] = format_aclnn_attr_value(value, param_type)

            elif param_type in ARRAY_TYPES:
                if not is_absent:
                    value = row.get(f"{param_name}.value", '')
                    if isinstance(value, (list, tuple, np.ndarray)) and len(value) == 0:
                        attrs_dict[param_name] = []
                    elif _is_valid_value(value):
                        attrs_dict[param_name] = format_aclnn_attr_value(value, param_type)

            elif param_type in ['int4_t', 'int8_t', 'int16_t', 'int32_t', 'int64_t',
                                'uint1_t', 'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t',
                                'int4', 'int8', 'int16', 'int32', 'int64',
                                'uint1', 'uint8', 'uint16', 'uint32', 'uint64',
                                'float', 'double', 'float16', 'bfloat16', 'float32', 'bool', 'char', 'char*', 'string']:
                if not is_absent:
                    value = row.get(f"{param_name}.value", '')
                    if _is_valid_value(value):
                        attrs_dict[param_name] = format_aclnn_attr_value(value, param_type)

            elif param_type == 'aclDataType':
                if not is_absent:
                    value = row.get(f"{param_name}.value", '')
                    if _is_valid_value(value):
                        normalized = normalize_dtype(str(value))
                        if normalized and normalized in ACL_DTYPE_ENUM_MAP:
                            attrs_dict[param_name] = ACL_DTYPE_ENUM_MAP[normalized]
                        else:
                            attrs_dict[param_name] = format_aclnn_attr_value(value, param_type)

        precision_info = _compute_precision_info(output_dtypes, output_dtype_set)

        case = {
            'testcase_name': f"{aclnn_name}_{case_level}_{idx+1:03d}",
            'network_name': 'UNKNOWN',
            'op_name': aclnn_name,
            'input_shapes': format_aclnn_shapes(input_shapes),
            'input_dtypes': format_aclnn_dtypes(input_dtypes),
            'input_formats': format_aclnn_formats(input_formats),
            'output_shapes': format_aclnn_shapes(output_shapes),
            'output_dtypes': format_aclnn_dtypes(output_dtypes),
            'output_formats': format_aclnn_formats(output_formats),
            'input_ori_shapes': format_aclnn_shapes(input_shapes),
            'input_ori_formats': format_aclnn_formats(input_formats),
            'output_ori_shapes': format_aclnn_shapes(output_shapes),
            'output_ori_formats': format_aclnn_formats(output_formats),
            'attributes': format_aclnn_attributes(attrs_dict),
            'input_data_ranges': format_aclnn_ranges(input_ranges),
            'precision_tolerances': precision_info['precision_tolerances'],
            'absolute_precision': precision_info['absolute_precision'],
            'output_inplace_indexes': format_aclnn_tuple(output_inplace_indexes),
            'output_shape_unknown_indexes': '()',
            'is_enabled': True,
            'remark': '',
            'soc_series': '',
            'priority': 0,
            'dump_file_prefix': '',
            'manual_input_binaries': '()',
            'manual_golden_binaries': '()',
        }
        cases.append(case)

    return pd.DataFrame(cases)[ACLNN_KERNEL_COLUMNS]


def _convert_cases_to_aclnn_kernel(cases, param_def, aclnn_name, level):
    rows = []
    for case in cases:
        row = {k: v for k, v in case.items() if not k.startswith('_')}
        rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return convert_to_aclnn_kernel_format(df, param_def, aclnn_name, level)


def _compute_precision_info(output_dtypes, output_dtype_set):
    if not output_dtype_set:
        return {"precision_tolerances": "", "absolute_precision": ""}
    all_integer = all(get_dtype_category(d) == 'integer' for d in output_dtype_set if d is not None and not isinstance(d, (tuple, list)))
    if all_integer:
        tol_pairs = []
        for d in output_dtypes:
            if isinstance(d, (tuple, list)):
                tol_pairs.append("(0,0)")
            else:
                tol_pairs.append("(0,0)")
        return {"precision_tolerances": "(" + ",".join(tol_pairs) + ",)", "absolute_precision": 0.0}
    if len(output_dtype_set) == 1:
        dtype = list(output_dtype_set)[0]
        if isinstance(dtype, (tuple, list)):
            dtype = dtype[0] if dtype else 'float32'
        return _get_precision_for_dtype(dtype)
    tol_pairs = []
    for d in output_dtypes:
        if isinstance(d, (tuple, list)):
            inner = ",".join("(0,0)" for _ in d)
            tol_pairs.append(f"({inner},)")
        elif d is None:
            tol_pairs.append("(0,0)")
        else:
            cat = get_dtype_category(d)
            if cat == 'integer':
                tol_pairs.append("(0,0)")
            else:
                tol_pairs.append("(0.001,0.001)")
    return {"precision_tolerances": "(" + ",".join(tol_pairs) + ",)", "absolute_precision": 1e-08}


# ==================== Kernel 用例校验与修复 ====================

def _validate_aclnn_cases(df, verbose=False):
    valid_mask = pd.Series([True] * len(df), index=df.index)
    detail_counts = {}
    checks = {
        'input_shapes': ['nan'],
        'input_dtypes': ['nan', 'None'],
        'input_formats': ['nan', 'None'],
        'output_shapes': ['nan'],
        'output_dtypes': ['nan', 'None'],
        'output_formats': ['nan', 'None'],
    }
    for col, forbidden in checks.items():
        if col not in df.columns:
            continue
        for token in forbidden:
            if token == 'nan':
                match_str = "'nan'"
            else:
                match_str = token
            invalid = df[col].astype(str).str.contains(re.escape(match_str), regex=True, na=False)
            count = invalid.sum()
            if count > 0:
                detail_counts[f"{col}含{token}"] = int(count)
                valid_mask = valid_mask & ~invalid
    valid_df = df[valid_mask].reset_index(drop=True)
    invalid_count = int((~valid_mask).sum())
    return valid_df, invalid_count, ''


def _aclnn_self_check_and_repair(case_df, engine, factors, param_def,
                                  aclnn_name, level, seed=None, verbose=False):
    max_rounds = 3
    for round_idx in range(max_rounds):
        valid_df, invalid_count, details = _validate_aclnn_cases(case_df, verbose)
        if invalid_count == 0:
            return valid_df
        base_seed = (seed or 0) + round_idx * 1000
        repaired = _repair_invalid_aclnn_cases(engine, factors, param_def, aclnn_name, level, invalid_count, base_seed, verbose)
        if len(repaired) > 0:
            case_df = pd.concat([valid_df, repaired], ignore_index=True)
        else:
            case_df = valid_df
    case_df, final_invalid, _ = _validate_aclnn_cases(case_df, verbose=False)
    if verbose and final_invalid > 0:
        print(f"[WARN] 自检修复达上限，保留 {len(case_df)} 条合法用例")
    return case_df


def _repair_invalid_aclnn_cases(engine, factors, param_def, aclnn_name, level,
                                dropped_count, base_seed, verbose=False):
    if dropped_count <= 0 or engine is None:
        return pd.DataFrame()
    key_anchors = {}
    _STATIC_ANCHOR_RE = re.compile(r'\.value_range_(?:int|uint|float|bfloat|bool|string)')
    for fn in engine.anchors:
        if _STATIC_ANCHOR_RE.search(fn):
            continue
        domain = engine.get_factor_domain(fn)
        if domain and len(domain) > 1:
            key_anchors[fn] = domain
    repaired = []
    for i in range(dropped_count * 3):
        if len(repaired) >= dropped_count:
            break
        seed = base_seed + i + 1
        random.seed(seed)
        partial = {}
        for fn, domain in key_anchors.items():
            partial[fn] = random.choice(domain)
        try:
            case = engine.solve_one(partial)
        except Exception:
            continue
        if case is None:
            continue
        case['_function'] = 'repair'
        case['_category'] = 'repair'
        repaired.append(case)
    if not repaired:
        return pd.DataFrame()
    repaired_df = _convert_cases_to_aclnn_kernel(repaired, param_def, aclnn_name, level)
    repaired_df, invalid_count, _ = _validate_aclnn_cases(repaired_df, verbose=False)
    return repaired_df