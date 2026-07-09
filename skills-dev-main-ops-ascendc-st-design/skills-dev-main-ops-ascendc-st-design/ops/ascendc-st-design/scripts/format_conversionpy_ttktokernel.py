#!/usr/bin/env python3
"""
kernel CSV -> GEIR xlsx 转换脚本

功能：
1. 读取 kernel 模式生成的 CSV 文件（26列 TTK kernel 格式）
2. 转换为 GEIR xlsx 格式（按 geir/ 目录下已有 xlsx 的列规则提取）
3. 支持多个 CSV 输入，每个 CSV 存放在各自页签(sheet)中
4. 可选指定算子 MD 文档用于辅助 scalar/buildins 属性分类

kernel CSV 26列：
    testcase_name, network_name, op_name, input_shapes, input_dtypes, input_formats,
    output_shapes, output_dtypes, output_formats, input_ori_shapes, input_ori_formats,
    output_ori_shapes, output_ori_formats, attributes, input_data_ranges,
    precision_tolerances, absolute_precision, output_inplace_indexes,
    output_shape_unknown_indexes, is_enabled, remark, soc_series, priority,
    dump_file_prefix, manual_input_binaries, manual_golden_binaries

GEIR xlsx 目标列（从 geir/*.xlsx 提取的通用规则）：
    aclnn_name, case_name, bin_dir, genetic, precision_mode, precision_tolerance, red_range,
    input_tensor_shape, input_tensor_range, input_tensor_dtype, input_tensor_format,
    input_tensor_type, input_tensor_index, output_tensor_shape, output_tensor_range,
    output_tensor_dtype, output_tensor_format, output_tensor_type,
    attr_name, attr_type, attr_dtype, attr_value  (attr_name.1, attr_type.1, ...)

使用方式：
    python format_conversionpy_ttktokernel.py csv1.csv csv2.csv ... --output output.xlsx
    python format_conversionpy_ttktokernel.py testcases_dir/ --output output.xlsx --merge
    python format_conversionpy_ttktokernel.py csv1.csv --output output.xlsx --md-path aclnnAdds.md
"""

import argparse
import sys
import json
import re
import math
import pandas as pd
import numpy as np
from pathlib import Path
from ast import literal_eval
from typing import Dict, List, Any, Tuple, Optional, Set
import glob


DTYPE_MAPPING = {
    'float32': 'fp32', 'float': 'fp32',
    'float16': 'fp16',
    'float64': 'fp64', 'double': 'fp64',
    'bfloat16': 'bf16',
    'int32': 'int32', 'int64': 'int64',
    'int16': 'int16', 'int8': 'int8',
    'uint8': 'uint8', 'uint16': 'uint16',
    'uint32': 'uint32', 'uint64': 'uint64',
    'bool': 'bool',
    'complex32': 'complex32', 'complex64': 'complex64', 'complex128': 'complex128',
    'hifloat4': 'hifloat4', 'hifloat4_scale': 'hifloat4_scale',
}

DTYPE_TO_C_TYPE = {
    'float': 'float', 'float16': 'float16', 'bfloat16': 'bfloat16',
    'double': 'double',
    'int8': 'int8_t', 'int16': 'int16_t', 'int32': 'int32_t', 'int64': 'int64_t',
    'uint8': 'uint8_t', 'uint16': 'uint16_t', 'uint32': 'uint32_t', 'uint64': 'uint64_t',
    'bool': 'bool', 'string': 'string',
}

C_TYPE_TO_ATTR_DTYPE = {
    'float': 'float', 'float16': 'float16', 'bfloat16': 'bfloat16',
    'double': 'double',
    'int8_t': 'int8_t', 'int16_t': 'int16_t', 'int32_t': 'int32_t', 'int64_t': 'int64_t',
    'uint8_t': 'uint8_t', 'uint16_t': 'uint16_t', 'uint32_t': 'uint32_t', 'uint64_t': 'uint64_t',
    'bool': 'bool', 'string': 'string',
}

SCALAR_PARAM_KEYWORDS = [
    'alpha', 'beta', 'gamma', 'value', 'scale', 'offset', 'fill_value',
    'min', 'max', 'threshold', 'tol', 'eps', 'delta', 'scalar',
    'weight', 'bias_scalar', 'momentum', 'damping', 'lr', 'learning_rate',
]

BUILDIN_PARAM_KEYWORDS = [
    'keepdim', 'keepdims', 'keep_dim', 'dim', 'axis', 'axes', 'dims',
    'mode', 'method', 'format', 'layout', 'dtype', 'data_type',
    'round_mode', 'reduction', 'padding_mode', 'sort', 'descending',
    'stable', 'exclusive', 'reverse', 'align_corners', 'ceil_mode',
    'minlength', 'maxlength', 'size', 'count', 'num',
    'n', 'N', 'sorted', 'largest',
]

ATTR_TYPE_SCALAR_KEYWORDS = [
    'alpha', 'beta', 'gamma', 'value', 'scale', 'offset', 'fill_value',
    'min', 'max', 'threshold', 'tol', 'eps', 'delta', 'scalar',
    'weight', 'bias_scalar', 'momentum', 'damping', 'lr',
]

FIXED_COLUMNS = [
    'aclnn_name', 'case_name', 'bin_dir', 'genetic',
    'precision_mode', 'precision_tolerance', 'red_range',
    'input_tensor_shape', 'input_tensor_range', 'input_tensor_dtype',
    'input_tensor_format', 'input_tensor_type', 'input_tensor_index',
    'output_tensor_shape', 'output_tensor_range', 'output_tensor_dtype',
    'output_tensor_format', 'output_tensor_type',
]


def convert_dtype(dtype_str: str) -> str:
    return DTYPE_MAPPING.get(dtype_str, dtype_str)


def infer_attr_type(attr_name: str, attr_dtype: str, attr_value: Any,
                    scalar_params_from_md: Set[str]) -> str:
    if attr_name in scalar_params_from_md:
        return 'scalar'
    if attr_name in ATTR_TYPE_SCALAR_KEYWORDS:
        dtype_lower = (attr_dtype or '').lower()
        if dtype_lower in ('float', 'fp32', 'fp16', 'bf16', 'fp64', 'double', 'bfloat16', 'float16', 'float32', 'float64'):
            return 'scalar'
    if isinstance(attr_value, list):
        return 'list_array'
    if isinstance(attr_value, bool):
        return 'buildins'
    dtype_lower = (attr_dtype or '').lower()
    if dtype_lower in ('string', 'acldatatype'):
        return 'data_type' if dtype_lower == 'acldatatype' else 'buildins'
    if dtype_lower in ('list', 'listint'):
        return 'list_array'
    return 'buildins'


def infer_attr_dtype_from_value(attr_name: str, attr_value: Any) -> str:
    if isinstance(attr_value, bool):
        return 'bool'
    if isinstance(attr_value, float):
        return 'float'
    if isinstance(attr_value, int):
        if attr_name in ('n', 'N', 'num', 'size', 'count', 'dim', 'axis', 'axes'):
            return 'int64_t'
        return 'int64_t'
    if isinstance(attr_value, list):
        if all(isinstance(v, int) for v in attr_value):
            return 'list'
        if all(isinstance(v, float) for v in attr_value):
            return 'list'
        return 'list'
    if isinstance(attr_value, str):
        return 'string'
    return 'int64_t'


def parse_ttk_tuple_field(value: str) -> list:
    if pd.isna(value) or value == '' or value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    s = str(value).strip()
    if not s:
        return []
    s = _normalize_python_literals(s)
    try:
        result = literal_eval(s)
        if isinstance(result, (list, tuple)):
            return list(result)
        return [result]
    except (ValueError, SyntaxError):
        return _regex_parse_tuple(s)


def _normalize_python_literals(s: str) -> str:
    s = re.sub(r'float\s*\(\s*"inf"\s*\)', '1e308', s)
    s = re.sub(r'float\s*\(\s*"-inf"\s*\)', '-1e308', s)
    s = re.sub(r'float\s*\(\s*"nan"\s*\)', 'None', s)
    s = re.sub(r'float\s*\(\s*\'inf\'\s*\)', '1e308', s)
    s = re.sub(r'float\s*\(\s*\'-inf\'\s*\)', '-1e308', s)
    s = re.sub(r'float\s*\(\s*\'nan\'\s*\)', 'None', s)
    return s


def _restore_special_floats(val):
    if isinstance(val, (list, tuple)):
        return [_restore_special_floats(v) for v in val]
    if isinstance(val, float):
        if math.isinf(val):
            return val
        try:
            if val >= 1e308 or val <= -1e308:
                return float('inf') if val > 0 else float('-inf')
        except (OverflowError, ValueError):
            return float('inf') if val > 0 else float('-inf')
    if val is None:
        return float('nan')
    return val


def _regex_parse_tuple(s: str) -> list:
    inner = s.strip()
    if inner.startswith('(') and inner.endswith(',)'):
        inner = inner[1:-2].strip()
    elif inner.startswith('(') and inner.endswith(')'):
        inner = inner[1:-1].strip()
    elif inner.startswith('((') and inner.endswith('))'):
        inner = inner[2:-2].strip()

    if not inner:
        return []

    if inner.startswith('(') or inner.startswith('['):
        try:
            result = literal_eval(inner)
            return list(result) if isinstance(result, (list, tuple)) else [result]
        except:
            pass

    elements = []
    depth = 0
    current = ''
    for ch in inner:
        if ch in ('(', '['):
            depth += 1
            current += ch
        elif ch in (')', ']'):
            depth -= 1
            current += ch
        elif ch == ',' and depth == 0:
            el = current.strip()
            if el:
                elements.append(el)
            current = ''
        else:
            current += ch
    el = current.strip()
    if el:
        elements.append(el)

    result = []
    for e in elements:
        e = e.strip()
        if not e:
            continue
        try:
            parsed = literal_eval(e)
            result.append(parsed)
        except:
            if e.startswith("'") and e.endswith("'"):
                result.append(e[1:-1])
            elif e.startswith('"') and e.endswith('"'):
                result.append(e[1:-1])
            else:
                result.append(e)
    return result


def parse_attributes_field(value: str) -> Dict[str, Any]:
    if pd.isna(value) or value is None or value == '':
        return {}
    if isinstance(value, dict):
        return value
    s = str(value).strip()
    if s.startswith('{') and s.endswith('}'):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return _smart_parse_attributes(s)
    return _smart_parse_attributes(s)


def _smart_parse_attributes(s: str) -> Dict[str, Any]:
    result = {}
    s = s.strip()
    if s.startswith('{'):
        s = s[1:]
    if s.endswith('}'):
        s = s[:-1]
    key_val_pattern = r"'([^']+)'\s*:\s*([^,}]+)"
    for m in re.finditer(key_val_pattern, s):
        key = m.group(1)
        val_str = m.group(2).strip()
        try:
            val = literal_eval(val_str)
        except:
            val = val_str
        result[key] = val
    return result


def parse_aclnn_md_for_scalar_params(md_path: Optional[Path]) -> Set[str]:
    if md_path is None or not md_path.exists():
        return set()
    try:
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()
        scalar_params = set()
        pattern = r'const\s+aclScalar\s*\*\s*(\w+)'
        matches = re.findall(pattern, content)
        scalar_params.update(matches)
        pattern2 = r'aclScalar\s*\*\s*(\w+)'
        matches2 = re.findall(pattern2, content)
        scalar_params.update(matches2)
        return scalar_params
    except Exception:
        return set()


def _format_number(x):
    if isinstance(x, float):
        if x == float('inf'):
            return "'inf'"
        if x == float('-inf'):
            return "'-inf'"
        if math.isnan(x):
            return "'nan'"
    if isinstance(x, (list, tuple)):
        return [_format_number(v) for v in x]
    return x


def format_shape_output(shapes: list) -> str:
    if not shapes:
        return ''
    parts = []
    for s in shapes:
        if isinstance(s, (list, tuple)):
            parts.append(str(list(s)))
        else:
            parts.append(str([s]))
    return '[' + ', '.join(parts) + ']'


def format_range_output(ranges: list) -> str:
    if not ranges:
        return ''
    parts = []
    for r in ranges:
        if r is None:
            parts.append('[None]')
        elif isinstance(r, (list, tuple)):
            formatted = []
            for v in r:
                fv = _format_number(v)
                if isinstance(fv, str) and fv.startswith("'") and fv.endswith("'"):
                    formatted.append(fv)
                elif isinstance(fv, str):
                    formatted.append(f"'{fv}'")
                else:
                    formatted.append(str(fv))
            parts.append('[' + ', '.join(formatted) + ']')
        else:
            fv = _format_number(r)
            if isinstance(fv, str) and fv.startswith("'") and fv.endswith("'"):
                parts.append('[' + fv + ']')
            else:
                parts.append('[' + str(fv) + ']')
    return '[' + ', '.join(parts) + ']'


def format_dtype_output(dtypes: list) -> str:
    if not dtypes:
        return ''
    converted = [convert_dtype(d) for d in dtypes]
    return '[' + ', '.join(f"'{d}'" for d in converted) + ']'


def format_format_output(formats: list) -> str:
    if not formats:
        return "['ND']"
    lower = [f.lower() for f in formats]
    return '[' + ', '.join(f"'{f}'" for f in lower) + ']'


def format_type_output(types: list) -> str:
    if not types:
        return "['tensor']"
    return '[' + ', '.join(f"'{t}'" for t in types) + ']'


def format_attr_value_output(attr_value: Any) -> str:
    if attr_value is None:
        return ''
    if isinstance(attr_value, bool):
        return 'True' if attr_value else 'False'
    if isinstance(attr_value, (int, float)):
        return str(attr_value)
    if isinstance(attr_value, list):
        formatted = [str(_format_number(v)) if not isinstance(v, (list, tuple)) else str(list(v)) for v in attr_value]
        return '[' + ', '.join(formatted) + ']'
    if isinstance(attr_value, str):
        return attr_value
    return str(attr_value)


def format_tensor_index_output(indices: list) -> str:
    if not indices:
        return '[0]'
    return '[' + ', '.join(str(i) for i in indices) + ']'


def parse_kernel_shapes(raw: str) -> Tuple[list, list]:
    parsed = parse_ttk_tuple_field(raw)
    if not parsed:
        return [], []
    if isinstance(parsed[0], (list, tuple)) and len(parsed[0]) > 0:
        if isinstance(parsed[0][0], (list, tuple)):
            input_shapes = [list(s) for s in parsed[0]]
            if len(parsed) > 1 and isinstance(parsed[1], (list, tuple)):
                output_shapes = [list(s) for s in parsed[1]]
            else:
                output_shapes = []
            return input_shapes, output_shapes
    input_shapes = [list(s) if isinstance(s, (list, tuple)) else [s] for s in parsed]
    output_shapes = []
    return input_shapes, output_shapes


def parse_kernel_dtypes(raw: str) -> Tuple[list, list]:
    parsed = parse_ttk_tuple_field(raw)
    if not parsed:
        return [], []
    if isinstance(parsed[0], (list, tuple)) and len(parsed[0]) > 0:
        if isinstance(parsed[0][0], str):
            input_dtypes = list(parsed[0])
            if len(parsed) > 1 and isinstance(parsed[1], (list, tuple)):
                output_dtypes = list(parsed[1])
            else:
                output_dtypes = []
            return input_dtypes, output_dtypes
    input_dtypes = [str(d) for d in parsed]
    output_dtypes = []
    return input_dtypes, output_dtypes


def convert_kernel_csv_to_geir(df_kernel: pd.DataFrame, op_name: str,
                               scalar_params_from_md: Set[str],
                               verbose: bool = False) -> pd.DataFrame:
    cases = []
    max_attrs = 0

    for idx, row in df_kernel.iterrows():
        case = {}

        case['aclnn_name'] = op_name
        case['case_name'] = row.get('testcase_name', f'{op_name}_case_{idx}')
        case['bin_dir'] = ''
        case['genetic'] = None

        if pd.notna(row.get('absolute_precision')) and row.get('absolute_precision') != '':
            case['precision_mode'] = '1'
            ap = row.get('absolute_precision')
            try:
                ap_val = float(ap)
                case['precision_tolerance'] = f'(({ap_val},{ap_val},999999,{ap_val},0),)'
            except:
                case['precision_tolerance'] = '((0.001,0.001,999999,0.001,0),)'
        elif pd.notna(row.get('precision_tolerances')) and row.get('precision_tolerances') != '':
            case['precision_mode'] = '0'
            pt_raw = row.get('precision_tolerances', '')
            if pd.notna(pt_raw) and pt_raw != '':
                parsed_pt = parse_ttk_tuple_field(str(pt_raw))
                if parsed_pt and isinstance(parsed_pt[0], (list, tuple)):
                    case['precision_tolerance'] = '(' + str(tuple(parsed_pt[0])) + ',)'
                else:
                    case['precision_tolerance'] = '((0.001,0.001,999999,0.001,0),)'
            else:
                case['precision_tolerance'] = '((0.001,0.001,999999,0.001,0),)'
        else:
            case['precision_mode'] = '0'
            case['precision_tolerance'] = '((0.001,0.001,999999,0.001,0),)'

        case['red_range'] = None

        input_shapes_raw = str(row.get('input_shapes', ''))
        input_dtypes_raw = str(row.get('input_dtypes', ''))
        input_formats_raw = str(row.get('input_formats', ''))
        output_shapes_raw = str(row.get('output_shapes', ''))
        output_dtypes_raw = str(row.get('output_dtypes', ''))
        output_formats_raw = str(row.get('output_formats', ''))
        input_ranges_raw = str(row.get('input_data_ranges', ''))

        all_shapes_parsed = parse_ttk_tuple_field(input_shapes_raw)
        all_dtypes_parsed = parse_ttk_tuple_field(input_dtypes_raw)
        all_formats_parsed = parse_ttk_tuple_field(input_formats_raw)
        out_shapes_parsed = parse_ttk_tuple_field(output_shapes_raw)
        out_dtypes_parsed = parse_ttk_tuple_field(output_dtypes_raw)
        out_formats_parsed = parse_ttk_tuple_field(output_formats_raw)
        all_ranges_parsed = parse_ttk_tuple_field(input_ranges_raw)

        input_parsed_items = _parse_input_items(all_shapes_parsed, all_dtypes_parsed, all_formats_parsed, all_ranges_parsed)

        shape_parts = []
        dtype_parts = []
        format_parts = []
        range_parts = []
        type_parts = []
        dynamic_shape_parts = []
        index_parts = []
        input_index_counter = 0

        for item_idx, item in enumerate(input_parsed_items):
            is_tl = item['is_tensor_list']
            shapes = item['shapes']
            dtypes = item['dtypes']
            fmts = item['formats']
            rngs = item['ranges']

            if is_tl:
                type_parts.append('tensor_list')
                inner_shapes = '[' + ','.join(str(list(s)) for s in shapes) + ']'
                shape_parts.append(inner_shapes)
                dtype_parts.append('[' + ','.join(f"'{convert_dtype(d)}'" for d in dtypes) + ']')
                fmts_lower = [f.lower() for f in fmts]
                format_parts.append('[' + ','.join(f"'{f}'" for f in fmts_lower) + ']')
                range_inner = '[' + ','.join(_format_range_item(r) for r in rngs) + ']'
                range_parts.append(range_inner)
                index_parts.append(str(input_index_counter))
                input_index_counter += 1
                ds_inner = _build_dynamic_shape_tensor_list(shapes, idx, item_idx)
                dynamic_shape_parts.append(ds_inner)
            else:
                type_parts.append('tensor')
                shape_parts.append(str(list(shapes[0])))
                dtype_parts.append(f"'{convert_dtype(dtypes[0])}'")
                format_parts.append(f"'{fmts[0].lower()}'")
                range_parts.append(_format_range_item(rngs[0]))
                index_parts.append(str(input_index_counter))
                input_index_counter += 1
                ds_val = _build_dynamic_shape_single(shapes[0], idx)
                dynamic_shape_parts.append(ds_val)

        case['input_tensor_shape'] = '[' + ','.join(shape_parts) + ']'
        case['input_tensor_dtype'] = '[' + ','.join(dtype_parts) + ']'
        case['input_tensor_format'] = '[' + ','.join(format_parts) + ']'
        case['input_tensor_type'] = '[' + ','.join(f"'{t}'" for t in type_parts) + ']'
        case['input_tensor_index'] = '[' + ','.join(index_parts) + ']'
        case['input_tensor_range'] = '[' + ','.join(range_parts) + ']'

        all_dynamic_shape_parts = dynamic_shape_parts

        output_shapes = []
        output_dtypes = []
        output_formats = []
        output_types = []

        if out_shapes_parsed and isinstance(out_shapes_parsed[0], (list, tuple)):
            if out_shapes_parsed[0] and isinstance(out_shapes_parsed[0][0], (list, tuple)):
                for s in out_shapes_parsed[0]:
                    output_shapes.append(list(s) if isinstance(s, (list, tuple)) else [s])
            else:
                for s in out_shapes_parsed:
                    output_shapes.append(list(s) if isinstance(s, (list, tuple)) else [s])
        else:
            for s in out_shapes_parsed:
                output_shapes.append([s] if not isinstance(s, (list, tuple)) else list(s))

        if out_dtypes_parsed and isinstance(out_dtypes_parsed[0], (list, tuple)):
            if out_dtypes_parsed[0] and isinstance(out_dtypes_parsed[0][0], str):
                output_dtypes = list(out_dtypes_parsed[0])
            else:
                output_dtypes = [str(d) for d in out_dtypes_parsed]
        else:
            output_dtypes = [str(d) for d in out_dtypes_parsed]

        if out_formats_parsed and isinstance(out_formats_parsed[0], (list, tuple)):
            if out_formats_parsed[0] and isinstance(out_formats_parsed[0][0], str):
                output_formats = list(out_formats_parsed[0])
            else:
                output_formats = [str(f) for f in out_formats_parsed]
        else:
            output_formats = [str(f) for f in out_formats_parsed]

        output_types = ['tensor'] * len(output_shapes)
        output_ranges = [None] * len(output_shapes)

        case['output_tensor_shape'] = format_shape_output(output_shapes)
        case['output_tensor_range'] = format_range_output(output_ranges)
        case['output_tensor_dtype'] = format_dtype_output(output_dtypes)
        case['output_tensor_format'] = format_format_output(output_formats)
        case['output_tensor_type'] = format_type_output(output_types)

        attributes_raw = str(row.get('attributes', ''))
        attributes = parse_attributes_field(attributes_raw)

        attr_count = 0
        for attr_name, attr_value in attributes.items():
            attr_suffix = '' if attr_count == 0 else f'.{attr_count}'

            attr_type = infer_attr_type(attr_name, '', attr_value, scalar_params_from_md)

            if attr_type == 'scalar':
                attr_dtype_str = 'float'
                if isinstance(attr_value, int) and not isinstance(attr_value, bool):
                    attr_dtype_str = 'int64_t'
                elif isinstance(attr_value, bool):
                    attr_dtype_str = 'bool'
                elif isinstance(attr_value, list):
                    attr_dtype_str = 'list'
            elif attr_type == 'list_array':
                attr_dtype_str = 'list'
            elif attr_type == 'data_type':
                attr_dtype_str = 'string'
            else:
                attr_dtype_str = infer_attr_dtype_from_value(attr_name, attr_value)

            if attr_name.lower() in ('n',) or attr_name in ('N',):
                attr_type = 'buildins'
                attr_dtype_str = 'int64_t'

            case[f'attr_name{attr_suffix}'] = attr_name
            case[f'attr_type{attr_suffix}'] = attr_type
            case[f'attr_dtype{attr_suffix}'] = attr_dtype_str
            case[f'attr_value{attr_suffix}'] = format_attr_value_output(attr_value)
            attr_count += 1

        dynamic_shape_val = '[' + ','.join(all_dynamic_shape_parts) + ']'

        dynamic_shape_suffix = '' if attr_count == 0 else f'.{attr_count}'
        case[f'attr_name{dynamic_shape_suffix}'] = 'dynamic_shape'
        case[f'attr_type{dynamic_shape_suffix}'] = 'list_array'
        case[f'attr_dtype{dynamic_shape_suffix}'] = 'list'
        case[f'attr_value{dynamic_shape_suffix}'] = dynamic_shape_val
        attr_count += 1

        max_attrs = max(max_attrs, attr_count)
        cases.append(case)

    all_columns = list(FIXED_COLUMNS)
    for i in range(max_attrs):
        suffix = '' if i == 0 else f'.{i}'
        all_columns.extend([
            f'attr_name{suffix}',
            f'attr_type{suffix}',
            f'attr_dtype{suffix}',
            f'attr_value{suffix}',
        ])

    for case in cases:
        for col in all_columns:
            if col not in case:
                case[col] = None

    df_result = pd.DataFrame(cases, columns=all_columns)
    return df_result


def _parse_input_items(all_shapes_parsed, all_dtypes_parsed, all_formats_parsed, all_ranges_parsed):
    if not all_shapes_parsed:
        return []

    raw_shapes = list(all_shapes_parsed)

    items = []
    for i, elem in enumerate(raw_shapes):
        if isinstance(elem, (list, tuple)) and len(elem) > 0 and isinstance(elem[0], (list, tuple)):
            shapes = [list(s) if isinstance(s, (list, tuple)) else [s] for s in elem]
            dtypes_raw = _get_full_inner_list(all_dtypes_parsed)
            if isinstance(dtypes_raw, (list, tuple)):
                dtypes = [str(d) for d in dtypes_raw]
            elif dtypes_raw is not None:
                dtypes = [str(dtypes_raw)]
            else:
                dtypes = [str(all_dtypes_parsed[0]) if all_dtypes_parsed else 'float32'] * len(shapes)
            formats_raw = _get_full_inner_list(all_formats_parsed)
            if isinstance(formats_raw, (list, tuple)):
                formats = [str(f) for f in formats_raw]
            elif formats_raw is not None:
                formats = [str(formats_raw)] * len(shapes)
            else:
                formats = ['ND'] * len(shapes)
            ranges_raw = _get_full_inner_list(all_ranges_parsed)
            if isinstance(ranges_raw, (list, tuple)) and len(ranges_raw) > 0 and isinstance(ranges_raw[0], (list, tuple)):
                ranges = [_restore_special_floats(list(r)) if isinstance(r, (list, tuple)) else _restore_special_floats(r) for r in ranges_raw]
            elif isinstance(ranges_raw, (list, tuple)):
                ranges = [_restore_special_floats(list(ranges_raw))] * len(shapes)
            else:
                ranges = [[-1, 1]] * len(shapes)
            items.append({'is_tensor_list': True, 'shapes': shapes, 'dtypes': dtypes, 'formats': formats, 'ranges': ranges})
        else:
            shapes = [list(elem) if isinstance(elem, (list, tuple)) else [elem]]
            dtypes_raw = _get_nested_list_elem(all_dtypes_parsed, i)
            dtype_val = str(dtypes_raw) if dtypes_raw is not None else (str(all_dtypes_parsed[0]) if all_dtypes_parsed else 'float32')
            formats_raw = _get_nested_list_elem(all_formats_parsed, i)
            format_val = str(formats_raw) if formats_raw is not None else 'ND'
            ranges_raw = _get_nested_list_elem(all_ranges_parsed, i)
            if isinstance(ranges_raw, (list, tuple)):
                range_val = _restore_special_floats(list(ranges_raw))
            elif ranges_raw is not None:
                range_val = _restore_special_floats(ranges_raw)
            else:
                range_val = [-1, 1]
            items.append({'is_tensor_list': False, 'shapes': shapes, 'dtypes': [dtype_val], 'formats': [format_val], 'ranges': [range_val]})

    return items


def _get_nested_list_elem(parsed_list, index):
    if not parsed_list:
        return None
    if isinstance(parsed_list, (list, tuple)) and len(parsed_list) == 1 and isinstance(parsed_list[0], (list, tuple)):
        inner = parsed_list[0]
        if index < len(inner):
            return inner[index]
        return None
    if isinstance(parsed_list, (list, tuple)):
        if index < len(parsed_list):
            return parsed_list[index]
        return None
    return None


def _get_full_inner_list(parsed_list):
    if not parsed_list:
        return None
    if isinstance(parsed_list, (list, tuple)) and len(parsed_list) == 1 and isinstance(parsed_list[0], (list, tuple)):
        return parsed_list[0]
    if isinstance(parsed_list, (list, tuple)):
        return parsed_list
    return None


def _format_range_item(r):
    if r is None:
        return '[None]'
    if isinstance(r, (list, tuple)):
        formatted = []
        for v in r:
            fv = _format_number(v)
            if isinstance(fv, str) and fv.startswith("'") and fv.endswith("'"):
                formatted.append(fv)
            elif isinstance(fv, str):
                formatted.append(f"'{fv}'")
            else:
                formatted.append(str(fv))
        return '[' + ', '.join(formatted) + ']'
    fv = _format_number(r)
    if isinstance(fv, str) and fv.startswith("'") and fv.endswith("'"):
        return '[' + fv + ']'
    return '[' + str(fv) + ']'


def _build_dynamic_shape_single(shape: list, case_idx: int) -> str:
    NUM_PATTERNS = 4
    STRIDE = 3
    pat_idx = case_idx % NUM_PATTERNS

    if not shape or pat_idx == 0:
        result = [-2]
    elif pat_idx == 1:
        result = [-1] * len(shape)
    elif pat_idx == 2:
        result = list(shape)
    else:
        mixed = []
        for di, d in enumerate(shape):
            if di % 3 == 0 and d in (0, 1):
                mixed.append(d)
            else:
                mixed.append(-1)
        result = mixed
    return str(result)


def _build_dynamic_shape_tensor_list(shapes: list, case_idx: int, item_idx: int) -> str:
    NUM_PATTERNS = 4
    STRIDE = 3
    inner_parts = []
    for t_idx, s in enumerate(shapes):
        pat_idx = (case_idx + t_idx * STRIDE + item_idx) % NUM_PATTERNS
        if not s or pat_idx == 0:
            inner_parts.append(str([-2]))
        elif pat_idx == 1:
            inner_parts.append(str([-1] * len(s)))
        elif pat_idx == 2:
            inner_parts.append(str(list(s)))
        else:
            mixed = []
            for di, d in enumerate(s):
                if di % 3 == 0 and d in (0, 1):
                    mixed.append(d)
                else:
                    mixed.append(-1)
            inner_parts.append(str(mixed))
    return '[' + ','.join(inner_parts) + ']'


def extract_op_name_from_csv(df: pd.DataFrame, csv_path: Path) -> str:
    if 'op_name' in df.columns:
        vals = df['op_name'].dropna().unique()
        if len(vals) > 0:
            return str(vals[0])
    name = csv_path.stem
    for level in ('_l0_functional', '_l1_functional', '_l2_exception'):
        name = name.replace(level, '')
    name = name.replace('aclnn', '')
    if name:
        return name
    return 'UnknownOp'


def extract_sheet_name_from_csv(csv_path: Path) -> str:
    stem = csv_path.stem
    if '_l0_functional' in stem:
        return 'level0'
    if '_l1_functional' in stem:
        return 'level1'
    if '_l2_exception' in stem:
        return 'error'
    return stem


def process_single_csv(csv_path: Path, output_xlsx: Path,
                       md_path: Optional[Path] = None,
                       sheet_name: Optional[str] = None,
                       op_name: Optional[str] = None,
                       verbose: bool = False) -> None:
    df_kernel = pd.read_csv(csv_path)
    if op_name is None:
        op_name = extract_op_name_from_csv(df_kernel, csv_path)
    if sheet_name is None:
        sheet_name = extract_sheet_name_from_csv(csv_path)

    scalar_params_from_md = parse_aclnn_md_for_scalar_params(md_path)

    df_geir = convert_kernel_csv_to_geir(df_kernel, op_name, scalar_params_from_md, verbose)

    if verbose:
        print(f"[INFO] 转换完成: {csv_path} -> {output_xlsx} (sheet={sheet_name}, {len(df_geir)}行)")

    try:
        with pd.ExcelWriter(output_xlsx, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
            df_geir.to_excel(writer, sheet_name=sheet_name[:31], index=False)
    except FileNotFoundError:
        with pd.ExcelWriter(output_xlsx, engine='openpyxl') as writer:
            df_geir.to_excel(writer, sheet_name=sheet_name[:31], index=False)

    if verbose:
        print(f"[INFO] 写入完成: {output_xlsx} sheet={sheet_name[:31]}")


def process_merge_mode(testcases_dir: Path, output_xlsx: Path,
                       md_path: Optional[Path] = None,
                       op_name: Optional[str] = None,
                       verbose: bool = False) -> None:
    csv_pattern = str(testcases_dir / '*.csv')
    csv_files = sorted(glob.glob(csv_pattern))

    if not csv_files:
        print(f"[ERROR] 未找到CSV文件: {testcases_dir}")
        sys.exit(1)

    if verbose:
        print(f"[INFO] 找到 {len(csv_files)} 个CSV文件")

    scalar_params_from_md = parse_aclnn_md_for_scalar_params(md_path)

    dfs_list = []
    for csv_path in csv_files:
        csv_p = Path(csv_path)
        df_kernel = pd.read_csv(csv_p)

        local_op_name = op_name
        if local_op_name is None:
            local_op_name = extract_op_name_from_csv(df_kernel, csv_p)

        sheet_name = extract_sheet_name_from_csv(csv_p)

        df_geir = convert_kernel_csv_to_geir(df_kernel, local_op_name, scalar_params_from_md, verbose)
        dfs_list.append((sheet_name[:31], df_geir))

        if verbose:
            print(f"[INFO] 转换: {csv_p.name} -> sheet={sheet_name[:31]} ({len(df_geir)}行)")

    with pd.ExcelWriter(output_xlsx, engine='openpyxl') as writer:
        for sheet_name, df in dfs_list:
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    if verbose:
        print(f"[INFO] 合并写入完成: {output_xlsx} ({len(dfs_list)}个页签)")


def main():
    parser = argparse.ArgumentParser(
        description='kernel CSV -> GEIR xlsx 转换脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('input', nargs='+',
                        help='输入CSV文件路径(可多个) 或目录(需配合--merge)')
    parser.add_argument('--output', '-o', required=True,
                        help='输出xlsx文件路径')
    parser.add_argument('--merge', action='store_true',
                        help='合并模式: 输入为目录，自动扫描所有CSV并合并到多页签xlsx')
    parser.add_argument('--md-path',
                        help='算子MD文档路径(用于识别aclScalar参数)')
    parser.add_argument('--op-name',
                        help='算子名称(自动从CSV提取时无需指定)')
    parser.add_argument('--verbose', '-v', action='store_true')

    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    md_path = Path(args.md_path) if args.md_path else None

    if args.merge:
        for inp in args.input:
            inp_dir = Path(inp)
            if not inp_dir.is_dir():
                print(f"[ERROR] --merge模式下输入必须是目录: {inp}")
                sys.exit(1)
            process_merge_mode(inp_dir, output_path, md_path, args.op_name, args.verbose)
    else:
        for inp in args.input:
            csv_path = Path(inp)
            if not csv_path.is_file():
                print(f"[ERROR] CSV文件不存在: {inp}")
                sys.exit(1)
            process_single_csv(csv_path, output_path, md_path, op_name=args.op_name, verbose=args.verbose)


if __name__ == '__main__':
    main()