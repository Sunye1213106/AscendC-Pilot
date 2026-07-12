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
TTK CSV格式转换为ACLNN Excel格式脚本

功能：
1. 单文件模式：转换单个CSV文件到Excel（支持L0/L1/L2级别）
2. 合并模式：读取目录下所有L0/L1/L2 CSV文件，合并到一个L3 Excel的多sheet（推荐）
3. 输出符合aclnn_operator_test_case_skill.md规范的Excel文件

级别说明：
    L0: 门槛用例（核心功能直通）
    L1: 功能/精度用例（参数组合测试）
    L2: 异常用例（边界和错误场景）
    L3: 合并输出（包含L0+L1+L2，aclnnfuzz框架使用）

推荐使用方式：
    python format_conversionpy_ttktoaclnn.py testcases_dir/ output.xlsx --merge --aclnn-name aclnnAddr

TTK CSV字段：
    testcase_name, api_name, tensor_view_shapes, tensor_dtypes, scalar_dtypes,
    attributes, output_tensor_indexes, precision_tolerances, absolute_precision,
    input_data_ranges, scalar_data_ranges, tensor_list_distribution

ACLNN Excel字段：
    aclnn_name, case_name, bin_dir, genetic, precision_mode, precision_tolerance, red_range,
    input_tensor_shape, input_tensor_range, input_tensor_dtype, input_tensor_format,
    input_tensor_type, input_tensor_index, output_tensor_shape, output_tensor_range,
    output_tensor_dtype, output_tensor_format, output_tensor_type,
    attr_name, attr_type, attr_dtype, attr_value（可能有多个编号）
"""

import argparse
import sys
import json
import re
import pandas as pd
from pathlib import Path
from ast import literal_eval
from typing import Dict, List, Any, Tuple, Optional, Set
import glob


DTYPE_MAPPING = {
    'float32': 'fp32',
    'float': 'fp32',
    'float16': 'fp16',
    'float64': 'fp64',
    'double': 'fp64',
    'bfloat16': 'bf16',
    'int32': 'int32',
    'int64': 'int64',
    'int16': 'int16',
    'int8': 'int8',
    'uint8': 'uint8',
    'uint16': 'uint16',
    'uint32': 'uint32',
    'uint64': 'uint64',
    'bool': 'bool',
    'complex32': 'complex32',
    'complex64': 'complex64',
    'complex128': 'complex128',
    'hifloat4': 'hifloat4',
    'hifloat4_scale': 'hifloat4_scale',
}

COMPLEX_DTYPES = {'complex32', 'complex64', 'complex128'}

BOOL_TO_INT_WHITELIST = {
    'aclnnSoftplus',
}

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

ACL_DTYPE_ENUM_TO_STR = {v: k for k, v in ACL_DTYPE_ENUM_MAP.items()}

C_TYPE_TO_DTYPE = {
    'int8_t': 'int8_t', 'int16_t': 'int16_t', 'int32_t': 'int32_t', 'int64_t': 'int64_t',
    'uint8_t': 'uint8_t', 'uint16_t': 'uint16_t', 'uint32_t': 'uint32_t', 'uint64_t': 'uint64_t',
    'int8': 'int8_t', 'int16': 'int16_t', 'int32': 'int32_t', 'int64': 'int64_t',
    'uint8': 'uint8_t', 'uint16': 'uint16_t', 'uint32': 'uint32_t', 'uint64': 'uint64_t',
    'float': 'float', 'float16': 'float16', 'bfloat16': 'bfloat16',
    'double': 'double', 'bool': 'bool', 'string': 'string',
    'char': 'string', 'aclDataType': 'int32_t',
}

BUILDIN_C_TYPE_NORM = {
    'int8': 'int8_t', 'int16': 'int16_t', 'int32': 'int32_t', 'int64': 'int64_t',
    'uint8': 'uint8_t', 'uint16': 'uint16_t', 'uint32': 'uint32_t', 'uint64': 'uint64_t',
    'float': 'float', 'float16': 'float16', 'bfloat16': 'bfloat16',
    'double': 'double', 'bool': 'bool', 'string': 'string',
}

ATTR_TYPE_MAPPING = {
    'float': 'scalar',
    'float16': 'scalar',
    'bfloat16': 'scalar',
    'float32': 'scalar',
    'float64': 'scalar',
    'double': 'scalar',
    'int': 'buildins',
    'int8': 'buildins',
    'int16': 'buildins',
    'int32': 'buildins',
    'int64': 'buildins',
    'int8_t': 'buildins',
    'int16_t': 'buildins',
    'int32_t': 'buildins',
    'int64_t': 'buildins',
    'uint8': 'buildins',
    'uint16': 'buildins',
    'uint32': 'buildins',
    'uint64': 'buildins',
    'bool': 'buildins',
    'string': 'buildins',
}

SCALAR_PARAM_KEYWORDS = [
    'alpha', 'beta', 'gamma', 'value', 'scale', 'offset', 'fill_value',
    'min', 'max', 'threshold', 'tol', 'eps', 'delta', 'scalar',
    'weight', 'bias_scalar', 'momentum', 'damping', 'lr', 'learning_rate',
    'grad_scalar', 'output_scalar', 'input_scalar'
]

BUILDIN_PARAM_KEYWORDS = [
    'keepdim', 'keepdims', 'keep_dim', 'dim', 'axis', 'axes', 'dims',
    'mode', 'method', 'format', 'layout', 'dtype', 'data_type',
    'round_mode', 'reduction', 'padding_mode', 'sort', 'descending',
    'stable', 'exclusive', 'reverse', 'align_corners', 'ceil_mode',
    'minlength', 'maxlength', 'size', 'count', 'num'
]


def parse_aclnn_md_for_inplace_params(md_path: Optional[Path]) -> Tuple[Set[str], List[str]]:
    """
    从aclnn算子的md文档中解析出既是输入又是输出的in-place tensor参数名，
    以及所有aclTensor参数的有序列表（按函数原型中的参数顺序排列）

    Args:
        md_path: md文档路径，如果为None则返回空集合和空列表

    Returns:
        (inplace_params, tensor_param_order) tuple
        inplace_params: in-place参数名集合（"输入/输出"标注的tensor参数）
        tensor_param_order: 所有aclTensor参数名的有序列表（按函数原型参数顺序）

    解析逻辑：
    1. 从GetWorkspaceSize参数表中提取所有aclTensor*参数的名称和"输入/输出"列
    2. "输入/输出"列值为"输入/输出"的参数为in-place参数
    3. 按函数原型中参数出现的顺序返回tensor参数名列表

    示例：
        md文档中有参数表行：
        | varRef | 输入/输出 | ... | aclTensor | ...
        | indices | 输入 | ... | const aclTensor* | ...

        返回：({'varRef'}, ['varRef', 'indices', 'updates'])
    """
    if md_path is None or not md_path.exists():
        return set(), []

    try:
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()

        inplace_params = set()
        tensor_param_order = []

        ws_pattern = r'aclnn\w+GetWorkspaceSize\s*\((.*?)\)'
        ws_match = re.search(ws_pattern, content, re.DOTALL)
        if not ws_match:
            return set(), []

        proto_body = ws_match.group(1)

        ptr_pattern = r'(?:const\s+)?aclTensor\s*\*\s*(\w+)'
        for line in proto_body.split('\n'):
            line = line.strip().rstrip(',').strip()
            if not line:
                continue
            m = re.search(ptr_pattern, line)
            if m:
                param_name = m.group(1)
                if param_name not in ('workspaceSize', 'executor'):
                    tensor_param_order.append(param_name)

        table_pattern = r'\|\s*(\w+)\s*\|\s*输入/输出\s*\|'
        for m in re.finditer(table_pattern, content):
            param_name = m.group(1)
            if param_name in tensor_param_order or not tensor_param_order:
                inplace_params.add(param_name)

        html_row_pattern = re.compile(r'<tr[^>]*>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>', re.DOTALL)
        for m in html_row_pattern.finditer(content):
            col1 = m.group(1).strip()
            col2 = m.group(2).strip()
            param_name = re.sub(r'[（\(].*?[）\)]', '', col1).strip()
            param_name = re.sub(r'[^a-zA-Z0-9_]', '', param_name)
            if col2 == '输入/输出' and param_name in tensor_param_order:
                inplace_params.add(param_name)

        return inplace_params, tensor_param_order
    except Exception:
        return set(), []


def parse_aclnn_md_for_scalar_params(md_path: Optional[Path]) -> Set[str]:
    """
    从aclnn算子的md文档中解析出aclScalar类型的参数名
    
    Args:
        md_path: md文档路径，如果为None则返回空集合
    
    Returns:
        aclScalar类型参数名的集合，例如 {'other', 'alpha'}
    
    解析逻辑：
    1. 找到aclnnXXXGetWorkspaceSize函数原型代码块
    2. 提取 const aclScalar* param_name 格式的参数
    3. 返回这些参数名（去掉指针符号和const修饰）
    
    示例：
        md文档中有：
        const aclScalar* other,
        const aclScalar* alpha,
        
        解析返回：{'other', 'alpha'}
    """
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


def parse_aclnn_md_for_buildins_params(md_path: Optional[Path]) -> Tuple[Dict[str, str], Set[str]]:
    """
    从aclnn算子的md文档中解析出buildins类型参数的 {参数名: dtype} 映射
    解析GetWorkspaceSize函数原型中的原生标量参数（int8_t, int32_t, bool等），
    提取其参数名和C类型，转换为标准dtype字符串。
    同时识别aclDataType类型的参数，返回其参数名集合。
    Args:
        md_path: md文档路径
    Returns:
        (buildins_params, data_type_params) tuple
        buildins_params: 参数名到dtype字符串的映射，例如 {'cubeMathType': 'int8', 'batchSplitFactor': 'int32'}
        data_type_params: aclDataType类型参数名集合，例如 {'probDataType'}
    解析逻辑：
    1. 定位GetWorkspaceSize函数原型代码块
    2. 逐行匹配非指针、非aclXxx类型的原生标量参数声明
    3. 通过C_TYPE_TO_DTYPE将C类型名映射为标准dtype
    4. 对aclDataType类型参数，单独记录为data_type_params
    """
    if md_path is None or not md_path.exists():
        return {}, set()
    try:
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()
        buildins_params = {}
        data_type_params = set()
        ws_pattern = r'aclnn\w+GetWorkspaceSize\s*\((.*?)\)'
        ws_match = re.search(ws_pattern, content, re.DOTALL)
        if not ws_match:
            return {}, set()
        proto_body = ws_match.group(1)
        raw_type_pattern = r'(?:(?:const)\s+)?(\w+_t|\w+)\s+(\w+)'
        char_star_pattern = r'char\s+\*\s*(\w+)|char\s*\*\s+(\w+)'
        for line in proto_body.split('\n'):
            line = line.strip().rstrip(',').strip()
            if not line:
                continue
            char_m = re.search(char_star_pattern, line)
            if char_m:
                param_name = char_m.group(1) or char_m.group(2)
                buildins_params[param_name] = 'string'
                continue
            if '*' in line:
                continue
            m = re.match(raw_type_pattern, line)
            if not m:
                continue
            c_type = m.group(1)
            param_name = m.group(2)
            if c_type == 'void' or c_type == 'aclnnStatus':
                continue
            if c_type == 'aclDataType':
                data_type_params.add(param_name)
                buildins_params[param_name] = 'int32_t'
                continue
            if c_type.startswith('acl'):
                continue
            dtype = C_TYPE_TO_DTYPE.get(c_type)
            if dtype:
                buildins_params[param_name] = dtype
        return buildins_params, data_type_params
    except Exception:
        return {}, set()


def find_aclnn_md_path(aclnn_name: str, input_path: Optional[Path] = None, 
                        md_path_arg: Optional[str] = None) -> Optional[Path]:
    """
    根据算子名称搜索对应的md文档路径（通用搜索策略）
    
    Args:
        aclnn_name: 算子名称，如 'aclnnAdds'
        input_path: 输入CSV或testcases目录路径（用于推断搜索位置）
        md_path_arg: 用户通过--md-path指定的路径
    
    Returns:
        找到的md文档路径，如果未找到则返回None
    
    搜索策略（按优先级）：
    1. 用户指定路径（--md-path参数）
    2. input_path同级docs目录：{input_parent}/docs/{aclnn_name}.md
    3. input_path上级inputs目录：inputs/{aclnn_name}/docs/{aclnn_name}.md
    4. 当前工作目录下的docs子目录
    5. 脚本同级目录下的aclnn-md-file目录（ops-math-master/ops-nn-master/ops-cv-master等）
    6. 当前工作目录及其子目录递归搜索
    """
    if md_path_arg:
        md_path = Path(md_path_arg)
        if md_path.exists():
            return md_path
    
    search_candidates = []
    
    if input_path:
        input_parent = input_path.parent if input_path.is_file() else input_path
        search_candidates.append(input_parent / "docs" / f"{aclnn_name}.md")
        
        for p in input_path.parents:
            if p.name == "inputs":
                search_candidates.append(p / aclnn_name / "docs" / f"{aclnn_name}.md")
                break
            if p.name == "tests":
                search_candidates.append(p.parent / "docs" / f"{aclnn_name}.md")
    
    script_dir = Path(__file__).parent
    cwd = Path.cwd()
    
    search_candidates.append(cwd / "docs" / f"{aclnn_name}.md")
    
    aclnn_md_dirs = [
        script_dir.parent / "aclnn-md-file" / "ops-math-master",
        script_dir.parent / "aclnn-md-file" / "ops-nn-master",
        script_dir.parent / "aclnn-md-file" / "ops-cv-master",
        script_dir.parent / "aclnn-md-file" / "ops-transformer-master",
        cwd / "aclnn-md-file" / "ops-math-master",
        cwd / "aclnn-md-file" / "ops-nn-master",
        cwd / "aclnn-md-file" / "ops-cv-master",
        cwd / "aclnn-md-file" / "ops-transformer-master",
    ]
    
    fuzzy_dirs = set()
    for candidate in search_candidates:
        if candidate.exists():
            return candidate
        if candidate.parent.exists():
            fuzzy_dirs.add(candidate.parent)

    for base_dir in aclnn_md_dirs:
        if base_dir.exists():
            for md_file in base_dir.rglob(f"{aclnn_name}*.md"):
                if md_file.name.startswith(aclnn_name) or aclnn_name in md_file.name:
                    return md_file
            fuzzy_dirs.add(base_dir)
    
    for fuzzy_dir in sorted(fuzzy_dirs, key=lambda d: len(str(d))):
        for md_file in fuzzy_dir.glob(f"*{aclnn_name}*.md"):
            return md_file
    
    for md_file in cwd.rglob(f"{aclnn_name}*.md"):
        if aclnn_name.lower() in md_file.name.lower():
            return md_file
    
    return None


def parse_complex_value(value: Any) -> Optional[List[float]]:
    """
    解析复数格式的值，返回[实部, 虚部]列表
    
    Args:
        value: 可能是复数格式的值，支持以下格式：
            - Python complex对象：complex(1, 2) 或 1+2j
            - 字符串格式："1+2j", "(1+2j)", "1-2j", "2j", "-2j"
            - JSON字符串中的带引号格式：'"(-0.1+-0.2j)"'
            - 非标准格式："(real+-imagj)" -> 处理为 "(real-imagj)"
    
    Returns:
        [实部, 虚部]列表，如果不是复数格式则返回None
    
    Examples:
        >>> parse_complex_value(1+2j)
        [1.0, 2.0]
        >>> parse_complex_value("(0.37051804886562745-0.3365608154285282j)")
        [0.37051804886562745, -0.3365608154285282]
        >>> parse_complex_value('"(-0.1492865311779572+-0.7749825991256941j)"')
        [-0.1492865311779572, -0.7749825991256941]
        >>> parse_complex_value("2j")
        [0.0, 2.0]
        >>> parse_complex_value(123)
        None
    """
    if isinstance(value, complex):
        return [value.real, value.imag]
    
    if not isinstance(value, str):
        return None
    
    value_str = value.strip()
    
    if not value_str:
        return None
    
    import re
    
    if 'j' not in value_str.lower():
        return None
    
    if value_str.startswith('"') and value_str.endswith('"'):
        value_str = value_str[1:-1].strip()
    elif value_str.startswith("'") and value_str.endswith("'"):
        value_str = value_str[1:-1].strip()
    
    if not value_str or 'j' not in value_str.lower():
        return None
    
    value_str = re.sub(r'\+-', '-', value_str)
    
    try:
        cleaned_for_complex = value_str
        if cleaned_for_complex.startswith('(') and cleaned_for_complex.endswith(')'):
            cleaned_for_complex = cleaned_for_complex[1:-1]
        parsed = complex(cleaned_for_complex)
        return [parsed.real, parsed.imag]
    except ValueError:
        pass
    
    pattern_with_parens = r'^\s*\(\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*([-+])\s*(\d*\.?\d+(?:[eE][-+]?\d+)?)j\s*\)\s*$'
    pattern_no_parens = r'^\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*([-+])\s*(\d*\.?\d+(?:[eE][-+]?\d+)?)j\s*$'
    pattern_pure_imag = r'^\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)j\s*$'
    
    match = re.match(pattern_with_parens, value_str)
    if match:
        real_part = float(match.group(1))
        sign = match.group(2)
        imag_part = float(match.group(3))
        if sign == '-':
            imag_part = -imag_part
        return [real_part, imag_part]
    
    match = re.match(pattern_no_parens, value_str)
    if match:
        real_part = float(match.group(1))
        sign = match.group(2)
        imag_part = float(match.group(3))
        if sign == '-':
            imag_part = -imag_part
        return [real_part, imag_part]
    
    match = re.match(pattern_pure_imag, value_str)
    if match:
        imag_str = match.group(1)
        if imag_str == '' or imag_str == '+':
            imag_part = 1.0
        elif imag_str == '-':
            imag_part = -1.0
        else:
            imag_part = float(imag_str)
        return [0.0, imag_part]
    
    return None


def format_complex_value(value: Any) -> str:
    """
    格式化复数值为[实部, 虚部]格式
    
    Args:
        value: 复数格式的值
    
    Returns:
        格式化后的字符串，如"[0.37051804886562745,-0.3365608154285282]"
    """
    parsed = parse_complex_value(value)
    if parsed is not None:
        return f"[{parsed[0]},{parsed[1]}]"
    return str(value)


def main():
    parser = argparse.ArgumentParser(
        description='TTK CSV格式转换为ACLNN Excel格式',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
    # 单文件模式：转换单个CSV文件
    python format_conversionpy_ttktoaclnn.py ttk_cases.csv output_dir/ --level L0
    python format_conversionpy_ttktoaclnn.py ttk_cases.csv output.xlsx --aclnn-name aclnnAbs --level L1
    
    # 合并模式：读取目录下所有L0/L1/L2 CSV，合并到一个L3 Excel的多sheet（推荐）
    python format_conversionpy_ttktoaclnn.py testcases_dir/ output.xlsx --merge --aclnn-name aclnnAddr
    python format_conversionpy_ttktoaclnn.py testcases_dir/ output_dir/ --merge --verbose
        '''
    )
    
    parser.add_argument('input', help='输入CSV文件路径或testcases目录路径（配合--merge使用）')
    parser.add_argument('output', help='输出Excel文件路径或输出目录')
    parser.add_argument('--merge', action='store_true', 
                        help='合并模式：读取目录下所有l0/l1/l2 CSV文件，合并到一个l3 Excel（推荐方式）')
    parser.add_argument('--level', default='l0', 
                        help='用例级别（单文件模式使用，支持l0/l1/l2，默认l0）。l3为合并模式输出结果。')
    parser.add_argument('--aclnn-name', help='算子名称（默认从CSV中提取api_name字段）')
    parser.add_argument('--bin-dir', default='', help='二进制文件存放目录')
    parser.add_argument('--md-path', help='算子md文档路径（用于解析aclScalar参数类型）')
    parser.add_argument('--verbose', action='store_true', help='详细输出模式')
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    
    if args.merge:
        process_merged_mode(input_path, args.output, args.aclnn_name, args.bin_dir, args.md_path, args.verbose)
    else:
        level = args.level.upper()
        if level == 'L3':
            print("[WARN] L3为合并模式输出结果，单文件模式不支持L3。请使用 --merge 参数或指定 L0/L1/L2")
            print("[INFO] 已自动切换为 L0 级别")
            level = 'L0'
        process_single_mode(input_path, args.output, level, args.aclnn_name, args.bin_dir, args.md_path, args.verbose)


def process_single_mode(input_csv: Path, output: str, level: str, 
                        aclnn_name: Optional[str], bin_dir: str, md_path: Optional[str], verbose: bool):
    df_ttk = pd.read_csv(input_csv)
    
    if verbose:
        print(f"[INFO] 加载TTK CSV: {input_csv} ({len(df_ttk)}条用例)")
    
    if not aclnn_name:
        if 'api_name' in df_ttk.columns:
            aclnn_name = df_ttk['api_name'].iloc[0]
        else:
            aclnn_name = 'UnknownOperator'
    
    md_file_path = find_aclnn_md_path(aclnn_name, input_csv, md_path)
    scalar_params_from_md = parse_aclnn_md_for_scalar_params(md_file_path)
    buildins_params_from_md, data_type_params_from_md = parse_aclnn_md_for_buildins_params(md_file_path)
    inplace_params_from_md, tensor_param_order_from_md = parse_aclnn_md_for_inplace_params(md_file_path)
    
    if verbose:
        print(f"[INFO] 算子名称: {aclnn_name}")
        print(f"[INFO] 用例级别: {level}")
        if md_file_path:
            print(f"[INFO] md文档路径: {md_file_path}")
            print(f"[INFO] 解析到aclScalar参数: {sorted(scalar_params_from_md)}")
            print(f"[INFO] 解析到buildins参数类型: {buildins_params_from_md}")
            print(f"[INFO] 解析到data_type参数: {sorted(data_type_params_from_md)}")
            print(f"[INFO] 解析到in-place参数: {sorted(inplace_params_from_md)}")
            print(f"[INFO] 解析到tensor参数顺序: {tensor_param_order_from_md}")
    
    df_aclnn = convert_ttk_to_aclnn(df_ttk, aclnn_name, bin_dir, verbose, scalar_params_from_md, buildins_params_from_md, data_type_params_from_md, inplace_params_from_md, tensor_param_order_from_md)
    
    output_path = resolve_output_path(output, aclnn_name, level)
    
    save_aclnn_excel(df_aclnn, output_path, verbose)


def process_merged_mode(testcases_dir: Path, output: str, 
                        aclnn_name: Optional[str], bin_dir: str, md_path: Optional[str], verbose: bool):
    csv_files = find_ttk_csv_files(testcases_dir, verbose)
    
    if not csv_files:
        print(f"[ERROR] 未找到任何TTK CSV文件: {testcases_dir}")
        return
    
    if not aclnn_name:
        first_csv = csv_files[0]['path']
        df_sample = pd.read_csv(first_csv, nrows=1)
        if 'api_name' in df_sample.columns:
            aclnn_name = df_sample['api_name'].iloc[0]
        else:
            aclnn_name = 'UnknownOperator'
    
    md_file_path = find_aclnn_md_path(aclnn_name, testcases_dir, md_path)
    scalar_params_from_md = parse_aclnn_md_for_scalar_params(md_file_path)
    buildins_params_from_md, data_type_params_from_md = parse_aclnn_md_for_buildins_params(md_file_path)
    inplace_params_from_md, tensor_param_order_from_md = parse_aclnn_md_for_inplace_params(md_file_path)
    
    if verbose:
        print(f"[INFO] 算子名称: {aclnn_name}")
        print(f"[INFO] 找到 {len(csv_files)} 个CSV文件")
        if md_file_path:
            print(f"[INFO] md文档路径: {md_file_path}")
            print(f"[INFO] 解析到aclScalar参数: {sorted(scalar_params_from_md)}")
            print(f"[INFO] 解析到buildins参数类型: {buildins_params_from_md}")
            print(f"[INFO] 解析到data_type参数: {sorted(data_type_params_from_md)}")
            print(f"[INFO] 解析到in-place参数: {sorted(inplace_params_from_md)}")
            print(f"[INFO] 解析到tensor参数顺序: {tensor_param_order_from_md}")
    
    dfs_aclnn = []
    for csv_info in csv_files:
        csv_path = csv_info['path']
        
        df_ttk = pd.read_csv(csv_path)
        
        if verbose:
            print(f"[INFO] 处理 {csv_path.name} ({csv_info['level']}, {len(df_ttk)}条用例)")
        
        df_aclnn = convert_ttk_to_aclnn(df_ttk, aclnn_name, bin_dir, verbose=False, 
                                        scalar_params_from_md=scalar_params_from_md,
                                        buildins_params_from_md=buildins_params_from_md,
                                        data_type_params_from_md=data_type_params_from_md,
                                        inplace_params_from_md=inplace_params_from_md,
                                        tensor_param_order_from_md=tensor_param_order_from_md)
        
        dfs_aclnn.append({
            'df': df_aclnn,
            'level': csv_info['level'],
            'is_standard': csv_info['is_standard'],
            'sheet_name': csv_info['sheet_name'],
            'filename': csv_info['filename']
        })
    
    output_path = Path(output)
    if output_path.suffix != '.xlsx':
        output_path.mkdir(parents=True, exist_ok=True)
        output_path = output_path / f"{aclnn_name}_l3_functional.xlsx"
    
    save_multi_sheet_excel(dfs_aclnn, output_path, aclnn_name, verbose)


def find_ttk_csv_files(testcases_dir: Path, verbose: bool) -> List[Dict]:
    csv_files = []
    standard_patterns = [
        ('L0', '*_l0_functional.csv'),
        ('L1', '*_l1_functional.csv'),
        ('L2', '*_l2_exception.csv'),
        ('L2', '*_l2_functional.csv'),
    ]
    standard_files = set()
    
    for level, pattern in standard_patterns:
        matches = list(testcases_dir.glob(pattern))
        for match in matches:
            csv_files.append({
                'level': level,
                'path': match,
                'is_standard': True,
                'sheet_name': None,
                'filename': match.stem
            })
            standard_files.add(match.name)
            if verbose:
                print(f"[INFO] 发现标准 {level} CSV: {match.name}")
    
    all_csv_files = list(testcases_dir.glob('*.csv'))
    for csv_path in all_csv_files:
        if csv_path.name not in standard_files:
            csv_files.append({
                'level': 'CUSTOM',
                'path': csv_path,
                'is_standard': False,
                'sheet_name': csv_path.stem,
                'filename': csv_path.stem
            })
            if verbose:
                print(f"[INFO] 发现非标准 CSV: {csv_path.name}")
    
    def sort_key(item):
        level = item['level']
        if level == 'L0':
            return (0, item['filename'])
        elif level == 'L1':
            return (1, item['filename'])
        elif level == 'L2':
            return (2, item['filename'])
        else:
            return (3, item['filename'])
    
    csv_files.sort(key=sort_key)
    
    return csv_files


def resolve_output_path(output_arg: str, aclnn_name: str, level: str) -> Path:
    output_path = Path(output_arg)
    
    if output_path.suffix == '.xlsx':
        return output_path
    
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path / f"{aclnn_name}_{level}_functional.xlsx"


def contains_special_value(value: Any) -> bool:
    """
    检查值是否包含特殊值 inf/-inf/nan
    
    Args:
        value: 要检查的值（可以是字符串、数字、列表、字典等）
    
    Returns:
        True 如果包含 inf/-inf/nan，False 否则
    
    检查规则：
    1. 浮点数：检查 math.isinf() 或 math.isnan()
    2. 字符串：检查是否包含 'inf', '-inf', 'nan'（不区分大小写）
    3. 列表/元组：递归检查每个元素
    4. 字典：递归检查每个值
    """
    import math
    
    if value is None:
        return False
    
    if isinstance(value, float):
        if math.isinf(value) or math.isnan(value):
            return True
        return False
    
    if isinstance(value, str):
        value_lower = value.lower().strip()
        special_values = ['inf', '-inf', '+inf', 'nan', 'infinity', '-infinity', '+infinity']
        for special in special_values:
            if special in value_lower:
                return True
        return False
    
    if isinstance(value, (list, tuple)):
        for item in value:
            if contains_special_value(item):
                return True
        return False
    
    if isinstance(value, dict):
        for v in value.values():
            if contains_special_value(v):
                return True
        return False
    
    return False


def check_attributes_has_special_values(attributes: Dict) -> Tuple[bool, List[str]]:
    """
    检查attributes字典中是否有attr_value包含 inf/-inf/nan
    
    Args:
        attributes: 属性字典，格式如 {'other': 32767, 'alpha': nan}
    
    Returns:
        (has_special, attr_names) - 是否包含特殊值，以及包含特殊值的属性名列表
    
    Examples:
        >>> check_attributes_has_special_values({'other': 32767, 'alpha': float('nan')})
        (True, ['alpha'])
        >>> check_attributes_has_special_values({'other': 'inf', 'alpha': 1.5})
        (True, ['other'])
    """
    if not attributes:
        return (False, [])
    
    special_attr_names = []
    for attr_name, attr_value in attributes.items():
        if contains_special_value(attr_value):
            special_attr_names.append(attr_name)
    
    return (len(special_attr_names) > 0, special_attr_names)


def convert_ttk_to_aclnn(df_ttk: pd.DataFrame, aclnn_name: str, 
                          bin_dir: str, verbose: bool,
                          scalar_params_from_md: Optional[Set[str]] = None,
                          buildins_params_from_md: Optional[Dict[str, str]] = None,
                          data_type_params_from_md: Optional[Set[str]] = None,
                          inplace_params_from_md: Optional[Set[str]] = None,
                          tensor_param_order_from_md: Optional[List[str]] = None) -> pd.DataFrame:
    cases = []
    skipped_count = 0
    skipped_reasons = {}
    
    for idx, row in df_ttk.iterrows():
        attributes = parse_attributes_field(row.get('attributes', '{}'))
        has_special, special_attrs = check_attributes_has_special_values(attributes)
        
        if has_special:
            skipped_count += 1
            testcase_name = row.get('testcase_name', f"{aclnn_name}_case_{idx:03d}")
            reason = f"attr_value包含特殊值(inf/-inf/nan): {special_attrs}"
            skipped_reasons[testcase_name] = reason
            continue
        
        case = build_aclnn_case(row, idx, aclnn_name, bin_dir, scalar_params_from_md, buildins_params_from_md, data_type_params_from_md, inplace_params_from_md, tensor_param_order_from_md)
        cases.append(case)
    
    if verbose:
        print(f"[INFO] 转换完成: {len(cases)}条用例")
        if skipped_count > 0:
            print(f"[INFO] 跳过 {skipped_count} 条用例（包含inf/-inf/nan特殊值）")
            if skipped_count <= 10:
                for name, reason in skipped_reasons.items():
                    print(f"  - {name}: {reason}")
    
    return build_aclnn_dataframe(cases)


def _parse_tensor_formats_field(value: str) -> List[str]:
    if pd.isna(value) or value == '' or value == '()':
        return []
    try:
        parsed = parse_ttk_tuple_field(value)
        def _strip_quotes(item):
            if isinstance(item, list):
                return [_strip_quotes(sub) for sub in item]
            if isinstance(item, str):
                return item.strip("'").strip('"')
            return item
        return [_strip_quotes(item) for item in parsed]
    except Exception:
        return []


def _is_none_shape(shape_item):
    return shape_item is None or (isinstance(shape_item, str) and shape_item == 'None')


def build_aclnn_case(row: pd.Series, idx: int, aclnn_name: str, bin_dir: str,
                     scalar_params_from_md: Optional[Set[str]] = None,
                     buildins_params_from_md: Optional[Dict[str, str]] = None,
                     data_type_params_from_md: Optional[Set[str]] = None,
                     inplace_params_from_md: Optional[Set[str]] = None,
                     tensor_param_order_from_md: Optional[List[str]] = None) -> Dict:
    case = create_base_case(row, idx, aclnn_name, bin_dir)
    
    shapes = parse_ttk_tuple_field(row.get('tensor_view_shapes', ''))
    dtypes = parse_ttk_dtype_field(row.get('tensor_dtypes', ''))
    ranges = parse_ttk_tuple_field(row.get('input_data_ranges', ''))
    output_indexes = parse_ttk_tuple_field(row.get('output_tensor_indexes', ''))
    scalar_dtypes = parse_ttk_tuple_str_field(row.get('scalar_dtypes', ''))
    attributes = parse_attributes_field(row.get('attributes', ''))
    tensor_list_dist = parse_ttk_tuple_field(row.get('tensor_list_distribution', ''))
    formats_raw = _parse_tensor_formats_field(row.get('tensor_formats', ''))
    
    has_tensor_list, tensor_list_indices = detect_tensor_list(shapes, dtypes)
    
    original_input_indices = list(range(len(shapes))) if shapes else []
    
    if shapes and any(_is_none_shape(s) for s in shapes) and not has_tensor_list:
        none_flags = [_is_none_shape(s) for s in shapes]
        non_none_indices = [i for i, flag in enumerate(none_flags) if not flag]
        total_original = len(none_flags)
        index_map = {orig_idx: filtered_idx for filtered_idx, orig_idx in enumerate(non_none_indices)}
        
        original_output_indexes_copy = list(output_indexes) if output_indexes else []
        if original_output_indexes_copy:
            original_output_positions = set(int(oi) for oi in original_output_indexes_copy)
        else:
            original_output_positions = {total_original - 1} if total_original > 0 else set()
        
        tail_start_original = total_original - len(original_output_indexes_copy) if original_output_indexes_copy else 0
        inplace_original_indices = [oi for oi in original_output_positions if oi < tail_start_original]
        has_inplace_original = len(inplace_original_indices) > 0
        
        shapes = [shapes[i] for i in non_none_indices]
        if dtypes and len(dtypes) == total_original:
            dtypes = [dtypes[i] for i in non_none_indices]
        if formats_raw and len(formats_raw) == total_original:
            formats_raw = [formats_raw[i] for i in non_none_indices]
        
        if output_indexes:
            output_indexes = [index_map[int(oi)] for oi in output_indexes if int(oi) in index_map]
        
        if ranges:
            if has_inplace_original:
                filtered_ranges = []
                for j in range(len(ranges)):
                    if j < len(non_none_indices) and not none_flags[non_none_indices[j]]:
                        filtered_ranges.append(ranges[j])
                ranges = filtered_ranges
            else:
                original_pure_input_positions = [i for i in range(total_original) if i not in original_output_positions]
                filtered_ranges = []
                for j, input_pos in enumerate(original_pure_input_positions):
                    if j < len(ranges) and not none_flags[input_pos]:
                        filtered_ranges.append(ranges[j])
                ranges = filtered_ranges
        
        original_input_indices = non_none_indices
    
    total_tensors = len(shapes) if shapes else 0
    
    inplace_detected = False
    inplace_input_positions = None
    output_idx_ints = [int(oi) for oi in output_indexes] if output_indexes and len(output_indexes) > 0 else []
    
    md_inplace_indices = []
    md_has_info = False
    if tensor_param_order_from_md and total_tensors > 0:
        md_has_info = True
        if inplace_params_from_md:
            for param_name in inplace_params_from_md:
                if param_name in tensor_param_order_from_md:
                    idx = tensor_param_order_from_md.index(param_name)
                    if idx < total_tensors:
                        md_inplace_indices.append(idx)
    
    if output_idx_ints and total_tensors > 0:
        
        if md_has_info:
            if md_inplace_indices:
                inplace_detected = True
                inplace_output_indices = md_inplace_indices
                pure_output_indices = [oi for oi in output_idx_ints if oi not in md_inplace_indices]
                inplace_input_positions = [i for i in range(total_tensors) if i not in pure_output_indices]
            else:
                if total_tensors == len(output_idx_ints):
                    inplace_detected = False
                else:
                    tail_start = total_tensors - len(output_idx_ints)
                    inplace_output_indices = [oi for oi in output_idx_ints if oi < tail_start]
                    inplace_detected = len(inplace_output_indices) > 0
                    
                    if inplace_detected:
                        pure_output_indices = [oi for oi in output_idx_ints if oi >= tail_start]
                        inplace_input_positions = [i for i in range(total_tensors) if i not in pure_output_indices]
        else:
            if total_tensors == len(output_idx_ints):
                inplace_detected = True
                inplace_output_indices = list(output_idx_ints)
                inplace_input_positions = list(range(total_tensors))
                pure_output_indices = []
            else:
                tail_start = total_tensors - len(output_idx_ints)
                inplace_output_indices = [oi for oi in output_idx_ints if oi < tail_start]
                inplace_detected = len(inplace_output_indices) > 0
                
                if inplace_detected:
                    pure_output_indices = [oi for oi in output_idx_ints if oi >= tail_start]
                    inplace_input_positions = [i for i in range(total_tensors) if i not in pure_output_indices]
    elif md_inplace_indices:
        inplace_detected = True
        pure_output_indices = [oi for oi in range(total_tensors) if oi not in md_inplace_indices and oi >= (total_tensors - 1)]
        inplace_input_positions = [i for i in range(total_tensors) if i not in pure_output_indices]
        inplace_output_indices = md_inplace_indices
    
    if inplace_detected:
        if has_tensor_list:
            input_shapes = [shapes[i] for i in inplace_input_positions] if shapes else []
            output_shapes = [shapes[oi] for oi in output_idx_ints] if shapes else []
            
            input_dtypes = [dtypes[i] for i in inplace_input_positions] if dtypes else []
            output_dtypes = [dtypes[oi] for oi in output_idx_ints] if dtypes else []
            
            input_tensor_list_indices = [inplace_input_positions.index(i) for i in tensor_list_indices if i in inplace_input_positions]
            output_tensor_list_indices_raw = [oi for oi in output_idx_ints if oi in tensor_list_indices]
            is_output_tensor_list = len(output_tensor_list_indices_raw) > 0
            
            input_ranges = [ranges[i] for i in inplace_input_positions if i < len(ranges)] if ranges else []
            input_formats = [formats_raw[i] for i in inplace_input_positions] if formats_raw else []
            output_formats = [formats_raw[oi] for oi in output_idx_ints] if formats_raw else []
            
            num_inputs = len(inplace_input_positions)
            num_outputs = len(output_idx_ints)
        else:
            input_shapes = [shapes[i] for i in inplace_input_positions] if shapes else []
            output_shapes = [shapes[oi] for oi in output_idx_ints] if shapes else []
            
            input_dtypes = [dtypes[i] for i in inplace_input_positions] if dtypes else []
            output_dtypes = [dtypes[oi] for oi in output_idx_ints] if dtypes else []
            
            is_output_tensor_list = False
            
            input_ranges = [ranges[i] for i in inplace_input_positions if i < len(ranges)] if ranges else []
            input_formats = [formats_raw[i] for i in inplace_input_positions] if formats_raw else []
            output_formats = [formats_raw[oi] for oi in output_idx_ints] if formats_raw else []
            
            num_inputs = len(inplace_input_positions)
            num_outputs = len(output_idx_ints)
    else:
        if has_tensor_list:
            if output_indexes and len(output_indexes) > 0:
                num_outputs = len(output_indexes)
                num_inputs = len(shapes) - num_outputs if shapes else 0
            else:
                num_outputs, num_inputs = infer_input_output_count(shapes, dtypes, aclnn_name)
            
            input_shapes = shapes[:num_inputs] if shapes else []
            output_shapes = shapes[num_inputs:] if shapes else []
            
            input_dtypes = dtypes[:num_inputs] if dtypes else []
            output_dtypes = dtypes[num_inputs:] if dtypes else []
            
            input_tensor_list_indices = [i for i in tensor_list_indices if i < num_inputs]
            output_tensor_list_indices = [i - num_inputs for i in tensor_list_indices if i >= num_inputs]
            is_output_tensor_list = len(output_tensor_list_indices) > 0
            
            input_ranges = ranges[:num_inputs] if ranges else []
            input_formats = formats_raw[:num_inputs] if formats_raw else []
            output_formats = formats_raw[num_inputs:] if formats_raw else []
        else:
            if output_indexes and len(output_indexes) > 0:
                num_outputs = len(output_indexes)
                num_inputs = len(shapes) - num_outputs if shapes else 0
            else:
                num_outputs, num_inputs = infer_input_output_count(shapes, dtypes, aclnn_name)
            
            input_shapes = shapes[:num_inputs] if shapes else []
            output_shapes = shapes[num_inputs:] if shapes else []
            
            input_dtypes = dtypes[:num_inputs] if dtypes else []
            output_dtypes = dtypes[num_inputs:] if dtypes else []
            
            is_output_tensor_list = False
            
            input_ranges = ranges[:num_inputs] if ranges else []
            input_formats = formats_raw[:num_inputs] if formats_raw else []
            output_formats = formats_raw[num_inputs:] if formats_raw else []
    
    if inplace_detected and inplace_input_positions:
        actual_input_indices = [original_input_indices[i] for i in inplace_input_positions if i < len(original_input_indices)]
    else:
        actual_input_indices = original_input_indices[:num_inputs] if original_input_indices else None
    
    if has_tensor_list and inplace_detected:
        input_tensor_list_indices_final = input_tensor_list_indices
        output_tensor_list_indices_final = output_tensor_list_indices_raw
    elif has_tensor_list:
        input_tensor_list_indices_final = input_tensor_list_indices
        output_tensor_list_indices_final = output_tensor_list_indices
    else:
        input_tensor_list_indices_final = []
        output_tensor_list_indices_final = []
    add_input_tensor_fields(case, input_shapes, input_ranges, input_dtypes, tensor_list_dist, has_tensor_list, input_formats, actual_input_indices, input_tensor_list_indices_final)
    add_output_tensor_fields(case, output_shapes, output_dtypes, tensor_list_dist, num_inputs, is_output_tensor_list, output_formats, output_tensor_list_indices_final)
    add_precision_fields(case, row)
    add_attribute_fields(case, attributes, scalar_dtypes, scalar_params_from_md, buildins_params_from_md, data_type_params_from_md, aclnn_name)
    
    return case


def infer_input_output_count(shapes: List, dtypes: List[str], aclnn_name: str) -> Tuple[int, int]:
    if not shapes:
        return (0, 0)
    
    num_tensors = len(shapes)
    num_dtypes = len(dtypes) if dtypes else num_tensors
    
    if num_tensors == num_dtypes:
        num_outputs = 1
        num_inputs = num_tensors - num_outputs
    elif num_tensors < num_dtypes:
        num_outputs = 1
        num_inputs = num_tensors - num_outputs
        if num_inputs < 0:
            num_inputs = 0
            num_outputs = num_tensors
    else:
        num_outputs = 1
        num_inputs = num_tensors - num_outputs
    
    return (num_outputs, num_inputs)


def create_base_case(row: pd.Series, idx: int, aclnn_name: str, bin_dir: str) -> Dict:
    testcase_name = row.get('testcase_name', f"{aclnn_name}_case_{idx:03d}")
    
    return {
        'aclnn_name': aclnn_name,
        'case_name': testcase_name,
        'bin_dir': bin_dir,
        'genetic': '',
        'precision_mode': '',
        'precision_tolerance': '',
        'red_range': ''
    }


def convert_special_value(val_str: str) -> Any:
    val_str = val_str.strip()
    if val_str.startswith('float("') and val_str.endswith('")'):
        inner = val_str[7:-2]
        return inner
    if val_str.startswith("'") and val_str.endswith("'"):
        inner = val_str[1:-1]
        if inner in ['nan', 'inf', '-inf', '+0', '-0']:
            return inner
        return val_str
    if val_str in ['+0', '-0']:
        return val_str
    if val_str.lstrip('-').lstrip('+').isdigit():
        return int(val_str)
    try:
        return float(val_str)
    except:
        return val_str

def parse_ttk_tuple_field(value: str) -> List:
    if pd.isna(value) or value == '' or value == '()':
        return []
    
    try:
        cleaned = value.strip()
        
        if not cleaned:
            return []
        
        try:
            fixed_cleaned = _fix_single_element_tuples(cleaned)
            parsed = literal_eval(fixed_cleaned)
            return _convert_parsed_to_list(parsed)
        except:
            pass
        
        if cleaned.startswith('(') and cleaned.endswith(',)'):
            cleaned = cleaned[1:-2]
        elif cleaned.startswith('(') and cleaned.endswith(')'):
            cleaned = cleaned[1:-1]
        
        if not cleaned:
            return []
        
        parts = split_tuple_parts(cleaned)
        
        result = []
        for part in parts:
            part = part.strip()
            if part.startswith('(') and part.endswith(',)'):
                inner = part[1:-2]
                sub_parts = split_tuple_parts(inner)
                inner_result = []
                for sp in sub_parts:
                    sp = sp.strip()
                    if sp.startswith('(') and sp.endswith(',)'):
                        inner_items = [convert_special_value(x.strip()) for x in sp[1:-2].split(',') if x.strip()]
                        inner_result.append(inner_items)
                    elif sp.startswith('(') and sp.endswith(')'):
                        inner_items = [convert_special_value(x.strip()) for x in sp[1:-1].split(',') if x.strip()]
                        inner_result.append(inner_items)
                    else:
                        inner_result.append(convert_special_value(sp))
                result.append(inner_result)
            elif part.startswith('(') and part.endswith(')'):
                inner = part[1:-1]
                sub_parts = split_tuple_parts(inner)
                if len(sub_parts) > 1 or (len(sub_parts) == 1 and sub_parts[0].strip().startswith('(')):
                    inner_result = []
                    for sp in sub_parts:
                        sp = sp.strip()
                        if sp.startswith('(') and sp.endswith(',)'):
                            inner_items = [convert_special_value(x.strip()) for x in sp[1:-2].split(',') if x.strip()]
                            inner_result.append(inner_items)
                        elif sp.startswith('(') and sp.endswith(')'):
                            inner_items = [convert_special_value(x.strip()) for x in sp[1:-1].split(',') if x.strip()]
                            inner_result.append(inner_items)
                        else:
                            inner_result.append(convert_special_value(sp))
                    result.append(inner_result)
                else:
                    items = [convert_special_value(x.strip()) for x in inner.split(',') if x.strip()]
                    result.append(items)
            elif part.startswith('[') and part.endswith(']'):
                try:
                    parsed = literal_eval(part)
                    if isinstance(parsed, list):
                        parsed = [convert_special_value(str(x)) if isinstance(x, str) else x for x in parsed]
                    result.append(parsed)
                except:
                    items = [convert_special_value(x) for x in part[1:-1].split(',') if x.strip()]
                    result.append(items)
            elif part.lstrip('-').lstrip('+').isdigit():
                result.append(int(part))
            else:
                try:
                    parsed = literal_eval(part)
                    if isinstance(parsed, str) and parsed in ['nan', 'inf', '-inf', '+0', '-0']:
                        result.append(parsed)
                    elif isinstance(parsed, (tuple, list)):
                        result.append(_convert_parsed_to_list(parsed))
                    else:
                        result.append(parsed)
                except:
                    result.append(convert_special_value(part))
        
        return result
    except Exception as e:
        return []


def _fix_single_element_tuples(s: str) -> str:
    """
    修复单元素括号格式：(value) -> (value,)
    只处理嵌套在tuple中的单元素括号，不影响原有的多元素tuple
    
    例如：
    ((3),(3),(3)) -> ((3,),(3,),(3,))  # 三个单元素shape
    ((1,2),(3,4)) -> ((1,2),(3,4))      # 不变，因为内部已经是多元素
    (3,3,3) -> (3,3,3)                  # 不变，因为是单层tuple
    """
    def find_matching_paren(s: str, start: int) -> int:
        depth = 1
        i = start + 1
        while i < len(s) and depth > 0:
            if s[i] == '(':
                depth += 1
            elif s[i] == ')':
                depth -= 1
            i += 1
        return i - 1 if depth == 0 else -1
    
    def process_nested(content: str) -> str:
        if not content or '(' not in content:
            return content
        
        result = []
        i = 0
        while i < len(content):
            if content[i] == '(':
                end = find_matching_paren(content, i)
                if end == -1:
                    result.append(content[i:])
                    break
                inner = content[i+1:end]
                if inner and '(' in inner:
                    inner = process_nested(inner)
                if ',' not in inner:
                    result.append('(' + inner + ',)')
                else:
                    result.append('(' + inner + ')')
                i = end + 1
            else:
                result.append(content[i])
                i += 1
        return ''.join(result)
    
    if '(' not in s:
        return s
    
    result = []
    i = 0
    while i < len(s):
        if s[i] == '(':
            end = find_matching_paren(s, i)
            if end == -1:
                result.append(s[i:])
                break
            inner = s[i+1:end]
            if inner and '(' in inner:
                inner = process_nested(inner)
            if ',' not in inner:
                result.append('(' + inner + ',)')
            else:
                result.append('(' + inner + ')')
            i = end + 1
        else:
            result.append(s[i])
            i += 1
    return ''.join(result)
    if isinstance(obj, tuple):
        return [_convert_parsed_to_list(item) for item in obj]
    elif isinstance(obj, list):
        return [_convert_parsed_to_list(item) for item in obj]
    elif isinstance(obj, str):
        if obj in ['nan', 'inf', '-inf', '+0', '-0']:
            return obj
        try:
            return int(obj)
        except:
            try:
                return float(obj)
            except:
                return obj
    else:
        return obj


def parse_ttk_tuple_str_field(value: str) -> List[str]:
    if pd.isna(value) or value == '' or value == '()':
        return []
    
    try:
        cleaned = value.strip()
        if cleaned.startswith('(') and cleaned.endswith(',)'):
            cleaned = cleaned[1:-2]
        elif cleaned.startswith('(') and cleaned.endswith(')'):
            cleaned = cleaned[1:-1]
        
        if not cleaned:
            return []
        
        pattern = r"'([^']+)'"
        matches = re.findall(pattern, cleaned)
        
        if matches:
            return list(matches)
        
        parts = [p.strip().strip("'").strip('"') for p in cleaned.split(',') if p.strip()]
        return parts
    except Exception:
        return []


def parse_ttk_dtype_field(value: str) -> List:
    if pd.isna(value) or value == '' or value == '()':
        return []
    
    try:
        cleaned = value.strip()
        if cleaned.startswith('(') and cleaned.endswith(',)'):
            cleaned = cleaned[1:-2]
        elif cleaned.startswith('(') and cleaned.endswith(')'):
            cleaned = cleaned[1:-1]
        
        if not cleaned:
            return []
        
        parts = split_tuple_parts(cleaned)
        
        result = []
        for part in parts:
            part = part.strip()
            if part.startswith('(') and part.endswith(',)'):
                inner = part[1:-2]
                matches = re.findall(r"'([^']+)'", inner)
                result.append(list(matches))
            elif part.startswith('(') and part.endswith(')'):
                inner = part[1:-1]
                matches = re.findall(r"'([^']+)'", inner)
                result.append(list(matches))
            else:
                matches = re.findall(r"'([^']+)'", part)
                if matches:
                    result.append(matches[0])
                else:
                    result.append(part.strip("'").strip('"'))
        
        return result
    except Exception:
        return []


def detect_tensor_list(shapes: List, dtypes: List) -> Tuple[bool, List[int]]:
    if not shapes and not dtypes:
        return (False, [])
    
    tensor_list_indices = []
    
    if shapes:
        for i, s in enumerate(shapes):
            if isinstance(s, list) and len(s) > 0 and isinstance(s[0], list):
                tensor_list_indices.append(i)
    
    if dtypes:
        for i, d in enumerate(dtypes):
            if isinstance(d, list) and i not in tensor_list_indices:
                tensor_list_indices.append(i)
    
    if tensor_list_indices:
        return (True, sorted(tensor_list_indices))
    
    return (False, [])


def split_tuple_parts(s: str) -> List[str]:
    parts = []
    current = ''
    depth = 0
    
    for char in s:
        if char == '(' or char == '[':
            depth += 1
            current += char
        elif char == ')' or char == ']':
            depth -= 1
            current += char
        elif char == ',' and depth == 0:
            if current.strip():
                parts.append(current.strip())
            current = ''
        else:
            current += char
    
    if current.strip():
        parts.append(current.strip())
    
    return parts


def parse_attributes_field(value: str) -> Dict:
    if pd.isna(value) or value == '' or value == '{}':
        return {}
    
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        try:
            cleaned = value.strip()
            if cleaned.startswith('{') and cleaned.endswith('}'):
                cleaned = cleaned[1:-1]
            
            result = {}
            
            pattern_v1 = r'"([^"]+)":\s*((?:\[[^\]]*\])|(?:\{[^}]*\})|(?:\"[^"]*\")|[+-]?nan|[+-]?inf|[+-]?infinity|[0-9.+-]+|true|false|[^,}\s]+)'
            matches_v1 = re.findall(pattern_v1, cleaned)
            
            pattern_v2 = r'"([^"]+)":\s*([^,}]+)'
            matches_v2 = re.findall(pattern_v2, cleaned)
            
            def validate_matches(matches, pattern_name):
                valid = []
                for key, val in matches:
                    val = val.strip()
                    if val and not val.endswith(','):
                        try:
                            literal_eval(val)
                            valid.append((key, val))
                        except:
                            if val.startswith('[') and not val.endswith(']'):
                                continue
                            if val.startswith('{') and not val.endswith('}'):
                                continue
                            valid.append((key, val))
                return valid
            
            matches_v1_validated = validate_matches(matches_v1, 'v1')
            matches_v2_validated = validate_matches(matches_v2, 'v2')
            
            if len(matches_v1_validated) >= len(matches_v2_validated):
                matches = matches_v1_validated
            else:
                matches = _smart_parse_attributes(cleaned)
            
            for key, val in matches:
                val = val.strip()
                if val.startswith('"') and val.endswith('"'):
                    result[key] = val[1:-1]
                elif val.startswith("'") and val.endswith("'"):
                    result[key] = val[1:-1]
                elif val.lstrip('-').replace('.', '').isdigit():
                    result[key] = float(val) if '.' in val else int(val)
                elif val.lower() == 'true':
                    result[key] = True
                elif val.lower() == 'false':
                    result[key] = False
                elif val.lower() in ['nan', 'inf', '-inf', '+inf', 'infinity', '-infinity', '+infinity']:
                    result[key] = val.lower()
                else:
                    try:
                        result[key] = literal_eval(val)
                    except:
                        result[key] = val
            
            return result
        except Exception:
            return {}


def _smart_parse_attributes(cleaned: str) -> List[Tuple[str, str]]:
    matches = []
    pos = 0
    
    while pos < len(cleaned):
        key_match = re.match(r'"([^"]+)":\s*', cleaned[pos:])
        if not key_match:
            break
        
        key = key_match.group(1)
        pos += key_match.end()
        
        value_start = pos
        
        if cleaned[pos] == '[':
            bracket_count = 1
            pos += 1
            while pos < len(cleaned) and bracket_count > 0:
                if cleaned[pos] == '[':
                    bracket_count += 1
                elif cleaned[pos] == ']':
                    bracket_count -= 1
                pos += 1
            value = cleaned[value_start:pos]
        
        elif cleaned[pos] == '{':
            brace_count = 1
            pos += 1
            while pos < len(cleaned) and brace_count > 0:
                if cleaned[pos] == '{':
                    brace_count += 1
                elif cleaned[pos] == '}':
                    brace_count -= 1
                pos += 1
            value = cleaned[value_start:pos]
        
        elif cleaned[pos] == '"':
            pos += 1
            while pos < len(cleaned) and cleaned[pos] != '"':
                pos += 1
            if pos < len(cleaned):
                pos += 1
            value = cleaned[value_start:pos]
        
        else:
            while pos < len(cleaned) and cleaned[pos] not in ',}':
                pos += 1
            value = cleaned[value_start:pos]
        
        matches.append((key, value.strip()))
        
        if pos < len(cleaned) and cleaned[pos] == ',':
            pos += 1
    
    return matches


def add_input_tensor_fields(case: Dict, shapes: List, ranges: List, 
                             dtypes: List[str], tensor_list_dist: List,
                             has_tensor_list: bool = False,
                             formats: Optional[List[str]] = None,
                             original_input_indices: Optional[List[int]] = None,
                             tensor_list_indices: Optional[List[int]] = None):
    if shapes is None or (isinstance(shapes, list) and len(shapes) == 0):
        case['input_tensor_shape'] = '[[1]]'
        case['input_tensor_range'] = '[[-0.01,-0.001]]'
        case['input_tensor_dtype'] = "['fp16']"
        case['input_tensor_format'] = "['nd']"
        case['input_tensor_type'] = "['tensor']"
        case['input_tensor_index'] = '[0]'
        return
    
    tensor_list_indices = tensor_list_indices or []
    shapes_normalized = ensure_list_format(shapes)
    
    if has_tensor_list:
        shape_items = []
        for i, shape in enumerate(shapes_normalized):
            if i in tensor_list_indices:
                if shape is None:
                    shape_items.append('[[1]]')
                else:
                    inner = []
                    for sub_shape in shape:
                        if isinstance(sub_shape, (list, tuple)):
                            inner.append('[' + ','.join(str(d) for d in sub_shape) + ']')
                        else:
                            inner.append(f'[{sub_shape}]')
                    shape_items.append('[' + ','.join(inner) + ']')
            else:
                if isinstance(shape, (list, tuple)):
                    shape_items.append('[' + ','.join(str(d) for d in shape) + ']')
                else:
                    shape_items.append(f'[{shape}]')
        case['input_tensor_shape'] = '[' + ','.join(shape_items) + ']'
        
        if dtypes and len(dtypes) > 0:
            dtype_items = []
            for i, d in enumerate(dtypes):
                if i in tensor_list_indices:
                    if isinstance(d, list):
                        inner = ','.join(f"'{convert_dtype(dd)}'" for dd in d)
                        dtype_items.append(f'[{inner}]')
                    else:
                        dtype_items.append(f"'{convert_dtype(d)}'")
                else:
                    if isinstance(d, list):
                        inner = ','.join(f"'{convert_dtype(dd)}'" for dd in d)
                        dtype_items.append(f'[{inner}]')
                    else:
                        dtype_items.append(f"'{convert_dtype(d)}'")
            case['input_tensor_dtype'] = '[' + ','.join(dtype_items) + ']'
        else:
            case['input_tensor_dtype'] = ''
        
        format_items = []
        for i in range(len(shapes_normalized)):
            if i in tensor_list_indices:
                if formats and i < len(formats) and isinstance(formats[i], list):
                    inner = ','.join(f"'{ff}'" for ff in formats[i])
                    format_items.append(f'[{inner}]')
                else:
                    n = len(shapes_normalized[i]) if isinstance(shapes_normalized[i], list) else 1
                    inner = ','.join("'ND'" for _ in range(n))
                    format_items.append(f'[{inner}]')
            else:
                _fmt = formats[i] if formats and i < len(formats) else 'ND'
                if isinstance(_fmt, list):
                    inner = ','.join(f"'{ff}'" for ff in _fmt)
                    format_items.append(f'[{inner}]')
                else:
                    format_items.append(f"'{_fmt}'")
        case['input_tensor_format'] = '[' + ','.join(format_items) + ']'
        
        types = []
        for i in range(len(shapes_normalized)):
            if i in tensor_list_indices:
                types.append('tensor_list')
            else:
                types.append('tensor')
        case['input_tensor_type'] = format_quoted_list_output(types)
        
        indices = original_input_indices if original_input_indices is not None else list(range(len(shapes_normalized)))
        case['input_tensor_index'] = str(indices)
        
        if ranges and len(ranges) > 0:
            ranges_normalized = ensure_list_format(ranges)
            if isinstance(ranges_normalized, list) and len(ranges_normalized) > 0:
                range_items = []
                for i, tensor_range in enumerate(ranges_normalized):
                    if i in tensor_list_indices:
                        if isinstance(tensor_range, list) and len(tensor_range) > 0 and isinstance(tensor_range[0], list):
                            inner = []
                            for sub_range in tensor_range:
                                if isinstance(sub_range, list) and len(sub_range) >= 2:
                                    min_val = format_single_item(sub_range[0])
                                    max_val = format_single_item(sub_range[-1])
                                    inner.append(f'[{min_val},{max_val}]')
                                elif isinstance(sub_range, list) and len(sub_range) == 1:
                                    val = format_single_item(sub_range[0])
                                    inner.append(f'[{val},{val}]')
                                else:
                                    inner.append('[]')
                            range_items.append('[' + ','.join(inner) + ']')
                        elif isinstance(tensor_range, list) and len(tensor_range) >= 2:
                            min_val = format_single_item(tensor_range[0])
                            max_val = format_single_item(tensor_range[-1])
                            range_items.append(f'[{min_val},{max_val}]')
                        else:
                            range_items.append('[]')
                    else:
                        if isinstance(tensor_range, list) and len(tensor_range) >= 2:
                            min_val = format_single_item(tensor_range[0])
                            max_val = format_single_item(tensor_range[-1])
                            range_items.append(f'[{min_val},{max_val}]')
                        elif isinstance(tensor_range, list) and len(tensor_range) == 1:
                            val = format_single_item(tensor_range[0])
                            range_items.append(f'[{val},{val}]')
                        else:
                            formatted_val = format_single_item(tensor_range)
                            range_items.append(f'[{formatted_val},{formatted_val}]')
                case['input_tensor_range'] = '[' + ','.join(range_items) + ']'
            else:
                case['input_tensor_range'] = ''
        else:
            case['input_tensor_range'] = ''
    else:
        is_multiple_tensors = isinstance(shapes_normalized, list) and len(shapes_normalized) > 0 and isinstance(shapes_normalized[0], list)
        
        if is_multiple_tensors:
            shape_items = []
            for shape in shapes_normalized:
                if isinstance(shape, (list, tuple)):
                    shape_items.append('[' + ','.join(str(d) for d in shape) + ']')
                else:
                    shape_items.append(f'[{shape}]')
            case['input_tensor_shape'] = '[' + ','.join(shape_items) + ']'
            
            if dtypes and len(dtypes) > 0:
                dtype_items = []
                for d in dtypes:
                    if isinstance(d, list):
                        inner = ','.join(f"'{convert_dtype(dd)}'" for dd in d)
                        dtype_items.append(f'[{inner}]')
                    else:
                        dtype_items.append(f"'{convert_dtype(d)}'")
                case['input_tensor_dtype'] = '[' + ','.join(dtype_items) + ']'
            else:
                case['input_tensor_dtype'] = ''
            
            format_items = []
            for i in range(len(shapes_normalized)):
                _fmt = formats[i] if formats and i < len(formats) else 'ND'
                if isinstance(_fmt, list):
                    inner = ','.join(f"'{ff}'" for ff in _fmt)
                    format_items.append(f'[{inner}]')
                else:
                    format_items.append(f"'{_fmt}'")
            case['input_tensor_format'] = '[' + ','.join(format_items) + ']'
            
            types = ['tensor' for _ in shapes_normalized]
            case['input_tensor_type'] = format_quoted_list_output(types)
            
            indices = original_input_indices if original_input_indices is not None else list(range(len(shapes_normalized)))
            case['input_tensor_index'] = str(indices)
        else:
            if isinstance(shapes_normalized, (list, tuple)):
                case['input_tensor_shape'] = '[' + ','.join(str(d) for d in shapes_normalized) + ']'
            else:
                case['input_tensor_shape'] = f'[{shapes_normalized}]'
            
            case['input_tensor_dtype'] = f"'{convert_dtype(dtypes[0])}'" if dtypes and len(dtypes) > 0 else ''
            
            _fmt = formats[0] if formats and len(formats) > 0 else 'ND'
            case['input_tensor_format'] = f"'{_fmt}'"
            
            case['input_tensor_type'] = "'tensor'"
            
            case['input_tensor_index'] = str([original_input_indices[0]]) if original_input_indices is not None else '[0]'
        
        if ranges and len(ranges) > 0:
            if is_multiple_tensors:
                ranges_normalized = ensure_list_format(ranges)
                if isinstance(ranges_normalized, list) and len(ranges_normalized) > 0:
                    all_ranges = []
                    for tensor_range in ranges_normalized:
                        if isinstance(tensor_range, list) and len(tensor_range) >= 2:
                            min_val = format_single_item(tensor_range[0])
                            max_val = format_single_item(tensor_range[-1])
                            all_ranges.append(f'[{min_val},{max_val}]')
                        elif isinstance(tensor_range, list) and len(tensor_range) == 1:
                            val = format_single_item(tensor_range[0])
                            all_ranges.append(f'[{val},{val}]')
                        else:
                            all_ranges.append('[]')
                    case['input_tensor_range'] = '[' + ','.join(all_ranges) + ']'
                else:
                    case['input_tensor_range'] = ''
            else:
                range_normalized = ensure_list_format(ranges[0]) if isinstance(ranges[0], list) else ranges
                case['input_tensor_range'] = f'[{",".join([format_single_item(x) for x in range_normalized])}]'
        else:
            case['input_tensor_range'] = ''


def add_output_tensor_fields(case: Dict, shapes: List, dtypes: List[str], 
                              tensor_list_dist: List, num_inputs: int,
                              is_output_tensor_list: bool = False,
                              formats: Optional[List[str]] = None,
                              output_tensor_list_indices: Optional[List[int]] = None):
    if shapes is None:
        case['output_tensor_shape'] = ''
        case['output_tensor_range'] = ''
        case['output_tensor_dtype'] = ''
        case['output_tensor_format'] = ''
        case['output_tensor_type'] = ''
        return
    
    output_tensor_list_indices = output_tensor_list_indices or []
    shapes_normalized = ensure_list_format(shapes)
    
    if is_output_tensor_list:
        shape_items = []
        for i, shape in enumerate(shapes_normalized):
            if i in output_tensor_list_indices:
                inner = []
                for sub_shape in shape:
                    if isinstance(sub_shape, (list, tuple)):
                        inner.append('[' + ','.join(str(d) for d in sub_shape) + ']')
                    else:
                        inner.append(f'[{sub_shape}]')
                shape_items.append('[' + ','.join(inner) + ']')
            else:
                if isinstance(shape, (list, tuple)):
                    shape_items.append('[' + ','.join(str(d) for d in shape) + ']')
                else:
                    shape_items.append(f'[{shape}]')
        case['output_tensor_shape'] = '[' + ','.join(shape_items) + ']'
        
        if dtypes and len(dtypes) > 0:
            dtype_items = []
            for i, d in enumerate(dtypes):
                if i in output_tensor_list_indices:
                    if isinstance(d, list):
                        inner = ','.join(f"'{convert_dtype(dd)}'" for dd in d)
                        dtype_items.append(f'[{inner}]')
                    else:
                        dtype_items.append(f"'{convert_dtype(d)}'")
                else:
                    if isinstance(d, list):
                        inner = ','.join(f"'{convert_dtype(dd)}'" for dd in d)
                        dtype_items.append(f'[{inner}]')
                    else:
                        dtype_items.append(f"'{convert_dtype(d)}'")
            case['output_tensor_dtype'] = '[' + ','.join(dtype_items) + ']'
        else:
            case['output_tensor_dtype'] = ''
        
        format_items = []
        for i in range(len(shapes_normalized)):
            if i in output_tensor_list_indices:
                if formats and i < len(formats) and isinstance(formats[i], list):
                    inner = ','.join(f"'{ff}'" for ff in formats[i])
                    format_items.append(f'[{inner}]')
                else:
                    n = len(shapes_normalized[i]) if isinstance(shapes_normalized[i], list) else 1
                    inner = ','.join("'ND'" for _ in range(n))
                    format_items.append(f'[{inner}]')
            else:
                _fmt = formats[i] if formats and i < len(formats) else 'ND'
                if isinstance(_fmt, list):
                    inner = ','.join(f"'{ff}'" for ff in _fmt)
                    format_items.append(f'[{inner}]')
                else:
                    format_items.append(f"'{_fmt}'")
        case['output_tensor_format'] = '[' + ','.join(format_items) + ']'
        
        types = []
        for i in range(len(shapes_normalized)):
            if i in output_tensor_list_indices:
                types.append('tensor_list')
            else:
                types.append('tensor')
        case['output_tensor_type'] = format_quoted_list_output(types)
    else:
        is_multiple_tensors = isinstance(shapes_normalized, list) and len(shapes_normalized) > 0 and isinstance(shapes_normalized[0], list)
        
        if is_multiple_tensors:
            shape_items = []
            for shape in shapes_normalized:
                if isinstance(shape, (list, tuple)):
                    shape_items.append('[' + ','.join(str(d) for d in shape) + ']')
                else:
                    shape_items.append(f'[{shape}]')
            case['output_tensor_shape'] = '[' + ','.join(shape_items) + ']'
            
            if dtypes and len(dtypes) > 0:
                dtype_items = []
                for d in dtypes:
                    if isinstance(d, list):
                        inner = ','.join(f"'{convert_dtype(dd)}'" for dd in d)
                        dtype_items.append(f'[{inner}]')
                    else:
                        dtype_items.append(f"'{convert_dtype(d)}'")
                case['output_tensor_dtype'] = '[' + ','.join(dtype_items) + ']'
            else:
                case['output_tensor_dtype'] = ''
            
            format_items = []
            for i in range(len(shapes_normalized)):
                _fmt = formats[i] if formats and i < len(formats) else 'ND'
                if isinstance(_fmt, list):
                    inner = ','.join(f"'{ff}'" for ff in _fmt)
                    format_items.append(f'[{inner}]')
                else:
                    format_items.append(f"'{_fmt}'")
            case['output_tensor_format'] = '[' + ','.join(format_items) + ']'
            
            types = ['tensor' for _ in shapes_normalized]
            case['output_tensor_type'] = format_quoted_list_output(types)
        else:
            if isinstance(shapes_normalized, (list, tuple)):
                case['output_tensor_shape'] = '[' + ','.join(str(d) for d in shapes_normalized) + ']'
            else:
                case['output_tensor_shape'] = f'[{shapes_normalized}]'
            
            if dtypes and len(dtypes) > 0:
                if isinstance(dtypes, list):
                    dtype_items = []
                    for d in dtypes:
                        if isinstance(d, list):
                            inner = ','.join(f"'{convert_dtype(dd)}'" for dd in d)
                            dtype_items.append(f'[{inner}]')
                        else:
                            dtype_items.append(f"'{convert_dtype(d)}'")
                    case['output_tensor_dtype'] = '[' + ','.join(dtype_items) + ']'
                else:
                    case['output_tensor_dtype'] = f"'{convert_dtype(dtypes)}'"
            else:
                case['output_tensor_dtype'] = ''
            
            if formats and len(formats) > 0:
                if isinstance(formats, list):
                    format_items = []
                    for f in formats:
                        if isinstance(f, list):
                            inner = ','.join(f"'{ff}'" for ff in f)
                            format_items.append(f'[{inner}]')
                        else:
                            format_items.append(f"'{f}'")
                    case['output_tensor_format'] = '[' + ','.join(format_items) + ']'
                else:
                    case['output_tensor_format'] = f"'{formats}'"
            else:
                case['output_tensor_format'] = "'ND'"
            
            case['output_tensor_type'] = "'tensor'"
    
    case['output_tensor_range'] = ''


def add_precision_fields(case: Dict, row: pd.Series):
    absolute_precision = row.get('absolute_precision', '')
    precision_tolerances = row.get('precision_tolerances', '')
    
    if absolute_precision and not pd.isna(absolute_precision) and absolute_precision != '':
        try:
            abs_val = float(absolute_precision)
            case['precision_mode'] = '1'
            case['precision_tolerance'] = '((0.001, 0.001, 999999, 0.001, 0),)'
        except:
            case['precision_mode'] = '0'
            case['precision_tolerance'] = '((0.001, 0.001, 999999, 0.001, 0),)'
    elif precision_tolerances and not pd.isna(precision_tolerances) and precision_tolerances != '':
        case['precision_mode'] = '0'
        case['precision_tolerance'] = str(precision_tolerances)
    else:
        case['precision_mode'] = '1'
        case['precision_tolerance'] = '((0.001, 0.001, 999999, 0.001, 0),)'


def infer_attr_dtype_from_value(attr_name: str, attr_value: Any) -> str:
    """
    从参数名和参数值推断dtype
    
    Args:
        attr_name: 参数名（如\'minlength\', \'alpha\')
        attr_value: 参数值
    
    Returns:
        dtype字符串（如\'int64_t\', \'float32\', \'bool\', \'string\'）
    推断优先级：
        优先级1: 根据实际值类型推断（优先级最高）
        优先级2: 参数名关键词推断（降级为后备方案）
    
    修复问题：
        - 修复 mode="nearest" 被错误推断为 int64 的问题
        - 优先检查实际值类型，避免关键词匹配导致的类型错误
    """
    if isinstance(attr_value, bool):
        return 'bool'
    elif isinstance(attr_value, int):
        return 'int64_t'
    elif isinstance(attr_value, float):
        return 'float32'
    elif isinstance(attr_value, str):
        return 'string'
    
    attr_name_lower = attr_name.lower()
    for keyword in BUILDIN_PARAM_KEYWORDS:
        if keyword in attr_name_lower:
            return 'int64_t'
    for keyword in SCALAR_PARAM_KEYWORDS:
        if keyword in attr_name_lower:
            return 'float32'
    return 'int64_t'


def infer_array_type_and_dtype(attr_value: Any) -> Tuple[str, str]:
    """
    根据数组元素类型推断attr_type和attr_dtype
    
    Args:
        attr_value: 数组值（list或tuple）
    
    Returns:
        (attr_type, attr_dtype) tuple
        例如：(['bool_array', 'bool'], ['int_array', 'int64'], ['float_array', 'float32'])
    
    推断规则：
    1. 所有元素都是bool -> bool_array + bool
    2. 所有元素都是int（不含bool） -> int_array + int64
    3. 所有元素都是float -> float_array + float32
    4. 混合类型 -> mixed_array + string
    """
    if not isinstance(attr_value, (list, tuple)) or len(attr_value) == 0:
        return ('int_array', 'int64')
    
    # 检查所有元素的类型
    has_bool = False
    has_int = False
    has_float = False
    has_other = False
    
    for elem in attr_value:
        if isinstance(elem, bool):
            has_bool = True
        elif isinstance(elem, int):
            has_int = True
        elif isinstance(elem, float):
            has_float = True
        else:
            has_other = True
    
    # 按优先级返回类型
    if has_other:
        return ('mixed_array', 'string')
    elif has_float:
        return ('float_array', 'float32')
    elif has_bool and not has_int:
        # 纯布尔数组
        return ('bool_array', 'bool')
    elif has_bool and has_int:
        # bool在Python中是int的子类，如果有True/False和整数混合，仍视为int_array
        return ('int_array', 'int64')
    elif has_int:
        return ('int_array', 'int64')
    else:
        return ('int_array', 'int64')


def infer_array_dtype(attr_value: Any) -> str:
    """
    根据数组元素类型推断dtype
    
    Args:
        attr_value: 数组值
    
    Returns:
        dtype字符串
    """
    _, dtype = infer_array_type_and_dtype(attr_value)
    return dtype


FLOAT_DTYPE_SHORTHAND = {
    'float32': 'fp32',
    'float': 'fp32',
    'float16': 'fp16',
    'float64': 'fp64',
    'bfloat16': 'bf16',
}


def _convert_float_dtype_to_shorthand(value: Any) -> Any:
    """
    当attr_dtype为string时，将attr_value中float类的dtype名称转换成简写格式

    例如: 'float32' -> 'fp32', 'float16' -> 'fp16', 'bfloat16' -> 'bf16', 'float64' -> 'fp64'
    对于非float类dtype（如'int8', 'bool'等），不做转换

    Args:
        value: 属性值，可以是字符串、整数(dtype枚举值)、列表等

    Returns:
        转换后的属性值
    """
    if isinstance(value, str):
        return FLOAT_DTYPE_SHORTHAND.get(value, value)
    elif isinstance(value, int) and value in ACL_DTYPE_ENUM_TO_STR:
        dtype_str = ACL_DTYPE_ENUM_TO_STR[value]
        return FLOAT_DTYPE_SHORTHAND.get(dtype_str, dtype_str)
    elif isinstance(value, (list, tuple)):
        converted = [_convert_float_dtype_to_shorthand(item) for item in value]
        return type(value)(converted)
    return value


def add_attribute_fields(case: Dict, attributes: Dict, scalar_dtypes: List[str],
                         scalar_params_from_md: Optional[Set[str]] = None,
                         buildins_params_from_md: Optional[Dict[str, str]] = None,
                         data_type_params_from_md: Optional[Set[str]] = None,
                         aclnn_name: Optional[str] = None):
    if not attributes:
        return
    
    if data_type_params_from_md is None:
        data_type_params_from_md = set()
    
    attr_idx = 0
    scalar_idx = 0
    
    for attr_name, attr_value in attributes.items():
        prefix = '' if attr_idx == 0 else f'.{attr_idx}'
        
        case[f'attr_name{prefix}'] = attr_name
        
        is_buildins_param = buildins_params_from_md and attr_name in buildins_params_from_md
        is_scalar_param = scalar_params_from_md is not None and attr_name in scalar_params_from_md

        if is_buildins_param:
            attr_dtype = buildins_params_from_md[attr_name]
        elif scalar_idx < len(scalar_dtypes) and not is_buildins_param:
            attr_dtype = scalar_dtypes[scalar_idx]
        else:
            attr_dtype = infer_attr_dtype_from_value(attr_name, attr_value)
        
        is_dtype_acl_data_type = (
            attr_name in data_type_params_from_md or
            (attr_name == 'dtype' and
             (not is_buildins_param or
              (is_buildins_param and buildins_params_from_md[attr_name] == 'int32_t'))) or
            (attr_dtype == 'string' and isinstance(attr_value, int) and attr_value in ACL_DTYPE_ENUM_TO_STR)
        )

        if is_dtype_acl_data_type:
            case[f'attr_dtype{prefix}'] = 'string'
            case[f'attr_type{prefix}'] = 'data_type'
            
            if isinstance(attr_value, int) and attr_value in ACL_DTYPE_ENUM_TO_STR:
                dtype_str = ACL_DTYPE_ENUM_TO_STR[attr_value]
                case[f'attr_value{prefix}'] = FLOAT_DTYPE_SHORTHAND.get(dtype_str, dtype_str)
            else:
                dtype_str = str(attr_value).strip()
                if dtype_str in ACL_DTYPE_ENUM_MAP:
                    case[f'attr_value{prefix}'] = FLOAT_DTYPE_SHORTHAND.get(dtype_str, dtype_str)
                else:
                    case[f'attr_value{prefix}'] = _convert_float_dtype_to_shorthand(format_attr_value_output(attr_value))
        elif attr_name == 'dtype' and is_buildins_param and buildins_params_from_md[attr_name] != 'int32_t':
            resolved_dtype = convert_dtype(buildins_params_from_md[attr_name])
            case[f'attr_dtype{prefix}'] = resolved_dtype
            case[f'attr_type{prefix}'] = 'buildins'
            normalized_value = _normalize_bool_value(attr_value) if attr_dtype == 'bool' else attr_value
            case[f'attr_value{prefix}'] = format_attr_value_output(normalized_value)
        elif isinstance(attr_value, (list, tuple)):
            attr_type, attr_dtype_arr = infer_array_type_and_dtype(attr_value)
            case[f'attr_dtype{prefix}'] = "list"
            case[f'attr_type{prefix}'] = attr_type
            case[f'attr_value{prefix}'] = format_attr_value_output(attr_value)
        else:
            inferred_type = infer_attr_type(attr_name, attr_dtype, attr_value, scalar_params_from_md)
            resolved_dtype = convert_dtype(attr_dtype)
            case[f'attr_dtype{prefix}'] = resolved_dtype
            case[f'attr_type{prefix}'] = inferred_type

            if inferred_type == 'buildins' and buildins_params_from_md and attr_name in buildins_params_from_md:
                resolved_dtype = convert_dtype(buildins_params_from_md[attr_name])
                case[f'attr_dtype{prefix}'] = resolved_dtype
            if inferred_type == 'buildins' and resolved_dtype in ('fp32', 'float32'):
                case[f'attr_dtype{prefix}'] = 'float'
            if inferred_type == 'buildins' and resolved_dtype == 'fp64':
                case[f'attr_dtype{prefix}'] = 'double'
            
            normalized_value = _normalize_bool_value(attr_value) if attr_dtype == 'bool' else attr_value

            if aclnn_name and aclnn_name in BOOL_TO_INT_WHITELIST:
                whitelisted = _apply_operator_bool_rules(aclnn_name, attr_value)
                if whitelisted is not attr_value:
                    normalized_value = whitelisted

            if attr_dtype in COMPLEX_DTYPES:
                complex_parsed = parse_complex_value(normalized_value)
                if complex_parsed is not None:
                    case[f'attr_value{prefix}'] = f"[{complex_parsed[0]},{complex_parsed[1]}]"
                else:
                    case[f'attr_value{prefix}'] = format_attr_value_output(normalized_value)
            elif resolved_dtype == 'string':
                case[f'attr_value{prefix}'] = _convert_float_dtype_to_shorthand(format_attr_value_output(normalized_value))
            else:
                case[f'attr_value{prefix}'] = format_attr_value_output(normalized_value)
        
        attr_idx += 1
        if not is_buildins_param:
            scalar_idx += 1


def convert_dtype(dtype_str: str) -> str:
    return DTYPE_MAPPING.get(dtype_str, dtype_str)


def get_attr_type(dtype: str) -> str:
    return ATTR_TYPE_MAPPING.get(dtype, 'buildins')


def infer_attr_type(attr_name: str, attr_dtype: str, attr_value: Any, 
                    scalar_params_from_md: Optional[Set[str]] = None) -> str:
    """
    推断attr_type的类型
    
    Args:
        attr_name: 参数名（如'alpha', 'keepdim', 'minlength'）
        attr_dtype: 参数的dtype（如'float32', 'bool', 'int64'）
        attr_value: 参数值
        scalar_params_from_md: 从md文档解析出的aclScalar参数名集合
    
    Returns:
        'scalar' 或 'buildins'
    
    分类规则：
    - scalar: aclScalar类型参数（通常是系数、权重、标量值等，如alpha/beta）
    - buildins: 原生标量类型参数（如int64_t的minlength、bool的keepdim等）
    
    优先级规则（优化后）：
    1. 从md文档解析出aclScalar参数名集合，参数名在集合中 -> scalar（优先级最高）
    2. 参数名匹配BUILDIN_PARAM_KEYWORDS -> buildins（避免关键词冲突）
    3. 参数名匹配SCALAR_PARAM_KEYWORDS -> scalar
    4. dtype为原生标量类型（int/bool/string） -> buildins
    5. dtype为浮点类型（float/double等） -> scalar
    6. 默认 -> buildins
    """
    if scalar_params_from_md is not None and attr_name in scalar_params_from_md:
        return 'scalar'
    
    attr_name_lower = attr_name.lower()
    
    # for keyword in BUILDIN_PARAM_KEYWORDS:
    #     if keyword in attr_name_lower:
     #        return 'buildins'
    
    # for keyword in SCALAR_PARAM_KEYWORDS:
    #     if keyword in attr_name_lower:
    #         return 'scalar'
    
    if attr_dtype in ['bool', 'string', 'int', 'int8', 'int16', 'int32', 'int64',
                       'int8_t', 'int16_t', 'int32_t', 'int64_t',
                       'uint8', 'uint16', 'uint32', 'uint64',
                       'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t']:
        return 'buildins'
    
    # if attr_dtype in ['float', 'float16', 'float32', 'float64', 'double', 'bfloat16']:
    #     return 'scalar'
    
    return 'buildins'


def infer_formats(shapes: List, tensor_list_dist: List, offset: int = 0) -> List[str]:
    formats = []
    total_tensors = len(shapes)
    
    if tensor_list_dist:
        list_positions = []
        current_pos = offset
        for length in tensor_list_dist:
            list_positions.append((current_pos, current_pos + length))
            current_pos += length
        
        for i in range(total_tensors):
            is_in_list = False
            for start, end in list_positions:
                if start <= i < end:
                    is_in_list = True
                    break
            formats.append('ND')
    else:
        formats = ['ND' for _ in range(total_tensors)]
    
    return formats


def infer_tensor_types(shapes: List, tensor_list_dist: List, offset: int = 0) -> List[str]:
    types = []
    total_tensors = len(shapes)
    
    if tensor_list_dist:
        list_positions = []
        current_pos = offset
        for length in tensor_list_dist:
            list_positions.append((current_pos, current_pos + length))
            current_pos += length
        
        for i in range(total_tensors):
            is_in_list = False
            for start, end in list_positions:
                if start <= i < end:
                    is_in_list = True
                    break
            types.append('tensor')
    else:
        types = ['tensor' for _ in range(total_tensors)]
    
    return types


def format_single_item(item: Any) -> str:
    if isinstance(item, str):
        if item in ['nan', 'inf', '-inf', '+0', '-0']:
            return f'"{item}"'
        return str(item)
    elif isinstance(item, float):
        if item != item:
            return '"nan"'
        elif item == float('inf'):
            return '"inf"'
        elif item == float('-inf'):
            return '"-inf"'
        else:
            return str(item)
    elif isinstance(item, bool):
        return str(item)
    elif isinstance(item, (int, list, tuple)):
        return str(item)
    else:
        return str(item)


def _resolve_formats(formats: Optional[List[str]], shapes_normalized: List, default_type: str) -> List[str]:
    if formats and len(formats) > 0:
        if len(formats) >= len(shapes_normalized):
            return formats[:len(shapes_normalized)]
        else:
            result = list(formats)
            result.extend(['ND'] * (len(shapes_normalized) - len(formats)))
            return result
    return ['ND' for _ in shapes_normalized]

def format_list_output(items: List) -> str:
    formatted = []
    for item in items:
        if isinstance(item, (list, tuple)):
            inner_formatted = [format_single_item(x) for x in item]
            formatted.append(f'[{",".join(inner_formatted)}]')
        else:
            formatted.append(format_single_item(item))
    return f'[{",".join(formatted)}]'


def format_tensor_shape_output(shape: List) -> str:
    """
    格式化单个tensor的shape为[[dim1,dim2,...]]格式
    例如: [11] -> [[11]], [9,6] -> [[9,6]], [] -> [[]] (0维tensor/scalar)
    """
    if not shape:
        return '[[]]'
    dims_str = ','.join(str(dim) for dim in shape)
    return f'[[{dims_str}]]'


def format_tensor_list_shape_output(shapes: List) -> str:
    """
    格式化tensorlist的shapes为[[shape1, shape2, ...]]格式
    例如: [[1], [1], [2,1]] -> [[[1], [1], [2,1]]]
    """
    if not shapes:
        return '[]'
    inner_shapes = []
    for shape in shapes:
        if isinstance(shape, (list, tuple)):
            inner_shapes.append(f'[{",".join(str(dim) for dim in shape)}]')
        else:
            inner_shapes.append(f'[{shape}]')
    return f'[[{",".join(inner_shapes)}]]'


def format_multiple_tensors_shape_output(shapes: List) -> str:
    """
    格式化多个tensor的shapes为[[dim1,dim2],[dim3,dim4]]格式（两层嵌套)
    用于非tensor_list的多tensor输入场景
    例如: [[1], [1]] -> [[1],[1]]
          [[1,2], [3,4]] -> [[1,2],[3,4]]
          [None, [1]] -> [[],[1]] (None转换为空列表)
    """
    if not shapes:
        return '[]'
    inner_shapes = []
    for shape in shapes:
        if shape is None:
            continue
        elif isinstance(shape, (list, tuple)):
            if not shape:
                inner_shapes.append('[[]]')
            else:
                dims_str = ','.join(str(dim) for dim in shape)
                inner_shapes.append(f'[{dims_str}]')
        else:
            inner_shapes.append(f'[{shape}]')
    return '[' + ','.join(inner_shapes) + ']'


def ensure_list_format(obj):
    if isinstance(obj, tuple):
        return list(obj)
    elif isinstance(obj, list):
        return [ensure_list_format(item) for item in obj]
    return obj


def format_quoted_list_output(items: List) -> str:
    if not items:
        return "[]"
    formatted = []
    for item in items:
        if isinstance(item, list):
            formatted.append(format_quoted_list_output(item))
        else:
            formatted.append(f"'{item}'")
    return f"[{','.join(formatted)}]"


def _apply_operator_bool_rules(aclnn_name: str, attr_value: Any) -> Any:
    """
    Per-operator bool value transformation rules.
    Returns transformed value; original value when operator not in whitelist.
    """
    if aclnn_name not in BOOL_TO_INT_WHITELIST:
        return attr_value
    normalized = _normalize_bool_value(attr_value)
    if isinstance(normalized, bool):
        return int(normalized)
    return attr_value


def _normalize_bool_value(attr_value: Any) -> Any:
    """
    Normalize value to Python bool when attr_dtype is bool.
    Handles: Python bool, str 'true'/'false', int 1/0.
    Returns Python True/False for bool-like values, original value otherwise.
    """
    if isinstance(attr_value, bool):
        return attr_value
    if isinstance(attr_value, str):
        if attr_value.lower() == 'true':
            return True
        if attr_value.lower() == 'false':
            return False
    if isinstance(attr_value, int) and not isinstance(attr_value, bool):
        if attr_value in (0, 1):
            return bool(attr_value)
    return attr_value


def format_attr_value_output(value: Any) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (list, tuple)):
        return str(list(value))
    if isinstance(value, float):
        if value != value:
            return '"nan"'
        elif value == float('inf'):
            return '"inf"'
        elif value == float('-inf'):
            return '"-inf"'
        else:
            return str(value)
    if isinstance(value, str):
        if value.lower() in ['nan', 'inf', '-inf', '+inf', 'infinity', '-infinity', '+infinity']:
            return f'"{value.lower()}"'
        return value
    return str(value)


def sort_attr_columns(attr_columns: List[str]) -> List[str]:
    """
    按编号分组排序attr字段，每组内按name, type, dtype, value顺序排列
    例如: attr_name, attr_type, attr_dtype, attr_value, attr_name.1, attr_type.1, attr_dtype.1, attr_value.1
    """
    attr_field_order = ['attr_name', 'attr_type', 'attr_dtype', 'attr_value']
    
    groups = {}
    for col in attr_columns:
        if col in attr_field_order:
            group_idx = 0
            field_type = col
        else:
            for field_type in attr_field_order:
                if col.startswith(field_type + '.'):
                    try:
                        group_idx = int(col.split('.')[-1])
                    except:
                        group_idx = 0
                    break
            else:
                group_idx = 0
                field_type = col
        
        if group_idx not in groups:
            groups[group_idx] = {}
        groups[group_idx][field_type] = col
    
    sorted_columns = []
    for group_idx in sorted(groups.keys()):
        group = groups[group_idx]
        for field_type in attr_field_order:
            if field_type in group:
                sorted_columns.append(group[field_type])
    
    remaining = [col for col in attr_columns if col not in sorted_columns]
    sorted_columns.extend(sorted(remaining))
    
    return sorted_columns


def build_aclnn_dataframe(cases: List[Dict]) -> pd.DataFrame:
    df = pd.DataFrame(cases)
    
    fixed_columns = [
        'aclnn_name', 'case_name', 'bin_dir', 'genetic', 'precision_mode',
        'precision_tolerance', 'red_range',
        'input_tensor_shape', 'input_tensor_range', 'input_tensor_dtype',
        'input_tensor_format', 'input_tensor_type', 'input_tensor_index',
        'output_tensor_shape', 'output_tensor_range', 'output_tensor_dtype',
        'output_tensor_format', 'output_tensor_type'
    ]
    
    attr_columns = sort_attr_columns([col for col in df.columns if col.startswith('attr_')])
    
    other_columns = [col for col in df.columns if col not in fixed_columns and col not in attr_columns]
    
    all_columns = fixed_columns + attr_columns + other_columns
    
    df = df.reindex(columns=all_columns, fill_value='')
    
    return df


def save_aclnn_excel(df: pd.DataFrame, output_path: Path, verbose: bool):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        df.to_excel(output_path, index=False, engine='openpyxl')
        if verbose:
            print(f"[INFO] 成功保存ACLNN Excel: {output_path}")
    except Exception as e:
        csv_path = output_path.with_suffix('.csv')
        df.to_csv(csv_path, index=False)
        if verbose:
            print(f"[WARN] Excel保存失败，已保存为CSV: {csv_path}")
            print(f"[ERROR] {e}")


def save_multi_sheet_excel(dfs_list: List[Dict], output_path: Path, 
                           aclnn_name: str, verbose: bool):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    if not dfs_list:
        print("[ERROR] 没有数据可保存")
        return
    
    try:
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            for item in dfs_list:
                df = item['df']
                level = item['level']
                is_standard = item['is_standard']
                sheet_name_override = item['sheet_name']
                
                if is_standard:
                    sheet_name = f"{aclnn_name}_{level}"
                else:
                    sheet_name = sheet_name_override if sheet_name_override else level
                
                if len(sheet_name) > 31:
                    name_part = aclnn_name[:8] + '..' if len(aclnn_name) > 8 else aclnn_name
                    sheet_name = f"{name_part}_{level}"
                    if len(sheet_name) > 31:
                        sheet_name = sheet_name[:31]
                
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                
                if verbose:
                    print(f"[INFO] Sheet '{sheet_name}' 已写入 ({len(df)}条用例)")
        
        if verbose:
            total_cases = sum(len(item['df']) for item in dfs_list)
            l0_count = sum(len(item['df']) for item in dfs_list if item['level'] == 'L0')
            l1_count = sum(len(item['df']) for item in dfs_list if item['level'] == 'L1')
            l2_count = sum(len(item['df']) for item in dfs_list if item['level'] == 'L2')
            custom_count = sum(len(item['df']) for item in dfs_list if item['level'] == 'CUSTOM')
            print(f"[INFO] 成功保存L3 Excel: {output_path}")
            print(f"[INFO] L3包含总用例数: {total_cases} (L0: {l0_count}, L1: {l1_count}, L2: {l2_count}, CUSTOM: {custom_count})")
    
    except Exception as e:
        print(f"[ERROR] Excel保存失败: {e}")
        for item in dfs_list:
            df = item['df']
            level = item['level']
            is_standard = item['is_standard']
            if is_standard:
                csv_path = output_path.parent / f"{aclnn_name}_{level}_functional.csv"
            else:
                csv_path = output_path.parent / f"{item['filename']}.csv"
            df.to_csv(csv_path, index=False)
            if verbose:
                print(f"[WARN] 已保存为CSV: {csv_path}")


if __name__ == '__main__':
    main()
