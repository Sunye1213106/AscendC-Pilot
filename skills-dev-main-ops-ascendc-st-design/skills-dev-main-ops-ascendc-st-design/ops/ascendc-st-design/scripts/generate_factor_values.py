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
约束校验与拓扑可视化工具

基于 @solves 装饰器的约束求解引擎，提供校验模式和拓扑生成。

用法:
    # 校验模式：少量样本试探性求解，输出约束满足率报告和告警
    python generate_factor_values.py <02_test_factors.yaml> --validate --constraints <04_constraints.py>

    # 仅生成拓扑可视化
    python generate_factor_values.py <02_test_factors.yaml> --topology-only --topology-out <05_topology.md>

示例:
    python generate_factor_values.py 02_test_factors.yaml --validate --constraints 04_constraints.py --sample-size 100
    python generate_factor_values.py 02_test_factors.yaml --topology-only --topology-out 05_topology.md
"""

import sys
from typing import Dict, List, Any, Tuple
from pathlib import Path
import os
import re
import ast
import itertools

try:
    from utils import (
        normalize_dtype,
        generate_random_shape,
        generate_random_value_by_dtype,
        FLOAT_DTYPES,
        INTEGER_DTYPES,
        generate_broadcast_shapes,
        generate_unidirectional_broadcast_shapes,
        get_broadcast_result,
        MAX_SHAPE_PRODUCT,
        get_default_value_range,
    )
except ImportError:
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from utils import (
        normalize_dtype,
        generate_random_shape,
        generate_random_value_by_dtype,
        FLOAT_DTYPES,
        INTEGER_DTYPES,
        generate_broadcast_shapes,
        generate_unidirectional_broadcast_shapes,
        get_broadcast_result,
        MAX_SHAPE_PRODUCT,
        get_default_value_range,
    )


def print_summary(cases: List[Dict[str, Any]]):
    print("\n" + "=" * 70)
    print("约束校验摘要")
    print("=" * 70)

    print(f"\n校验样本数: {len(cases)}")

    if cases:
        all_factors = set()
        for case in cases:
            all_factors.update(case.keys())

        print(f"因子总数: {len(all_factors)}")

        dtype_factors = [f for f in all_factors if '.dtype' in f]
        shape_factors = [f for f in all_factors if '.shape' in f]
        exist_factors = [f for f in all_factors if '.exist' in f]
        value_range_factors = [f for f in all_factors if '.value_range' in f]

        print(f"\n因子类型分布:")
        print(f"  - dtype 因子: {len(dtype_factors)}个")
        print(f"  - shape 因子: {len(shape_factors)}个")
        print(f"  - exist 因子: {len(exist_factors)}个")
        print(f"  - value_range 因子: {len(value_range_factors)}个")

    print("\n" + "=" * 70)


def _check_strategy_consistency(r_id, strategy_line, constraints_path):
    func_match = re.search(r'@solves\((\w+)\)', strategy_line)
    if func_match:
        func_name = func_match.group(1)
        if constraints_path and os.path.exists(constraints_path):
            with open(constraints_path, 'r', encoding='utf-8') as f:
                code = f.read()
            if f'def {func_name}(' not in code:
                return False, f"{r_id} 标注 @solves({func_name}) 但函数 {func_name}() 未定义"
    return True, None


def _check_constraint_traceability(factors_path, constraints_path):
    """校验 01_parameter_description.md 中的每个 R{n} 约束都出现在 04_constraints.py 的追溯表中"""
    design_dir = os.path.dirname(os.path.abspath(factors_path))
    param_desc_path = os.path.join(design_dir, "01_parameter_description.md")

    if not os.path.exists(param_desc_path):
        return True

    r_ids_in_01 = set()
    r_conditions = {}
    with open(param_desc_path, "r", encoding="utf-8") as f:
        current_r = None
        for line in f:
            m = re.match(r'###\s+(R\d+)', line.strip())
            if m:
                current_r = m.group(1)
                r_ids_in_01.add(current_r)
            elif current_r and line.strip().startswith('条件因子:'):
                val = line.strip()[len('条件因子:'):].strip()
                r_conditions[current_r] = val

    if not r_ids_in_01:
        return True

    r_ids_in_04 = set()
    trace_lines_for_strategy = []
    if constraints_path and os.path.exists(constraints_path):
        in_trace_block = False
        with open(constraints_path, "r", encoding="utf-8") as f:
            for line in f:
                if "约束追溯表" in line and line.strip().startswith("#"):
                    in_trace_block = True
                    continue
                if in_trace_block and "追溯表结束" in line:
                    in_trace_block = False
                    continue
                if in_trace_block:
                    m = re.match(r'#\s+(R\d+)', line.strip())
                    if m:
                        r_ids_in_04.add(m.group(1))
                        trace_lines_for_strategy.append((m.group(1), line.strip()))

    missing = r_ids_in_01 - r_ids_in_04
    if missing:
        print(f"\n[ERROR] 约束追溯完整性校验失败：以下约束在追溯表中缺失: {sorted(missing)}")
        print(f"  01_parameter_description.md 中的约束: {sorted(r_ids_in_01)}")
        print(f"  04_constraints.py 追溯表中的约束: {sorted(r_ids_in_04)}")
        return False

    strategy_errors = []
    for r_id, line in trace_lines_for_strategy:
        if '@solves' in line:
            ok, msg = _check_strategy_consistency(r_id, line, constraints_path)
            if not ok:
                strategy_errors.append(msg)

    for r_id, line in trace_lines_for_strategy:
        if 'factor-domain' in line:
            cond = r_conditions.get(r_id, None)
            if cond is None:
                print(f"[TRACE-STRATEGY-MISMATCH] {r_id} 标注 factor-domain，"
                      f"但 01 中无'条件因子'字段（旧格式），请确认约束是否为无条件约束")
            elif cond != '无':
                if 'factor-domain(' in line and ')' in line.split('factor-domain(')[1]:
                    pass
                else:
                    strategy_errors.append(
                        f"[TRACE-STRATEGY-MISMATCH] {r_id} 标注 factor-domain，"
                        f"但条件因子为'{cond}'且未在括号中标注控制类型理由。"
                        f"值空间约束须使用 @solves [条件过滤] + assert 正向强制；"
                        f"存在性控制须标注 factor-domain(exist控制生效域)。"
                    )

    if strategy_errors:
        print(f"\n[ERROR] 策略一致性校验失败：")
        for msg in strategy_errors:
            print(f"  {msg}")
        return False

    print(f"[INFO] 约束追溯完整性校验通过: {sorted(r_ids_in_01)} 全部已登记")
    return True


def _check_validate_coverage(factors_path, constraints_path):
    """校验追溯表中所有 R{n} 在 validate_constraints 中有覆盖"""
    if not constraints_path or not os.path.exists(constraints_path):
        return True, False

    trace_rns = {}
    in_trace_block = False
    with open(constraints_path, 'r', encoding="utf-8") as f:
        for line in f:
            if "约束追溯表" in line and line.strip().startswith("#"):
                in_trace_block = True
                continue
            if in_trace_block and "追溯表结束" in line:
                break
            if in_trace_block:
                m = re.match(r'#\s+(R\d+)', line.strip())
                if m:
                    r_id = m.group(1)
                    stripped = line.strip()
                    if 'factor-domain' in stripped:
                        trace_rns[r_id] = 'factor-domain'
                    elif '[条件过滤]' in stripped:
                        trace_rns[r_id] = '[条件过滤]'
                    elif '@solves' in stripped:
                        trace_rns[r_id] = '@solves'
                    else:
                        trace_rns[r_id] = 'unknown'

    if not trace_rns:
        return True, False

    with open(constraints_path, 'r', encoding="utf-8") as f:
        code = f.read()

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return True, False

    validate_func_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'validate_constraints':
            validate_func_node = node
            break

    if validate_func_node is None:
        print("[TRACE-COVERAGE] validate_constraints 函数未定义")
        return True, False

    code_rns = set()
    for node in ast.walk(validate_func_node):
        if isinstance(node, ast.Call):
            func = node.func
            func_name = None
            if isinstance(func, ast.Name):
                func_name = func.id
            elif isinstance(func, ast.Attribute):
                func_name = func.attr
            if func_name:
                m = re.match(r'_validate_r(\d+)$', func_name)
                if m:
                    code_rns.add(f'R{m.group(1)}')

    for node in ast.walk(validate_func_node):
        if isinstance(node, (ast.Tuple, ast.List)):
            for elt in node.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    if re.match(r'R\d+$', elt.value):
                        code_rns.add(elt.value)

    comment_rns = set()
    vc_match = re.search(
        r'def validate_constraints.*?(?=\ndef\s|\Z)', code, re.DOTALL
    )
    if vc_match:
        for vc_line in vc_match.group(0).split('\n'):
            stripped = vc_line.strip()
            if stripped.startswith('#'):
                r_matches = set(re.findall(r'R(\d+)', stripped))
                comment_rns.update(f'R{n}' for n in r_matches)

    non_fd = {r for r, s in trace_rns.items() if s != 'factor-domain'}

    really_missing = sorted(non_fd - code_rns - comment_rns)
    if really_missing:
        for r_id in really_missing:
            strategy = trace_rns.get(r_id, 'unknown')
            print(f"[TRACE-COVERAGE] {r_id} 未在 validate_constraints 中覆盖 "
                  f"(策略: {strategy})")

    commented_only_in_vc = comment_rns - code_rns
    suspicious_skips = []
    for r_id in sorted(commented_only_in_vc & non_fd):
        strategy = trace_rns.get(r_id, 'unknown')
        if strategy == 'factor-domain':
            continue
        suspicious_skips.append((r_id, strategy))

    if suspicious_skips:
        for r_id, strategy in suspicious_skips:
            print(f"[TRACE-COVERAGE-WARN] {r_id} 在 validate_constraints 中被注释跳过，"
                  f"但策略为 {strategy}（非 factor-domain），请确认跳过理由是否合理")

    has_errors = bool(really_missing)
    has_warnings = bool(suspicious_skips)

    if not has_errors and not has_warnings:
        print(f"[INFO] validate_constraints 覆盖校验通过: "
              f"共 {len(non_fd)} 条需覆盖，全部已覆盖")

    return has_errors, has_warnings


def _check_sources_unused(constraints_path):
    """静态检查 @solves 函数 sources 中是否有参数被声明但未在函数体中使用"""
    if not constraints_path or not os.path.exists(constraints_path):
        return []

    warnings = []
    with open(constraints_path, 'r', encoding='utf-8') as f:
        source = f.read()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return warnings

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Name):
                continue
            if dec.func.id != 'solves':
                continue
            if not dec.args or not isinstance(dec.args[0], ast.Constant):
                continue
            target_name = dec.args[0].value

            sources_kw = None
            for kw in dec.keywords:
                if kw.arg == 'sources':
                    sources_kw = kw.value
            if not sources_kw or not isinstance(sources_kw, ast.List):
                continue

            func_params = {arg.arg for arg in node.args.args}

            used_names = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Name):
                    used_names.add(child.id)

            unused = func_params - used_names - {'self'}
            for param in sorted(unused):
                warnings.append(
                    f"[SOURCE-UNUSED] @solves('{target_name}'): "
                    f"parameter '{param}' is in sources but never used in function body. "
                    f"If this parameter is a condition factor, add a conditional branch; "
                    f"otherwise remove it from sources."
                )
    return warnings


def _extract_names_from_ast(node):
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
    return names


def _extract_names_from_list_elts(list_node):
    names = set()
    if isinstance(list_node, ast.List):
        for elt in list_node.elts:
            names |= _extract_names_from_ast(elt)
    return names


def _extract_ordered_names_from_list(list_node):
    result = []
    if isinstance(list_node, ast.List):
        for elt in list_node.elts:
            elt_names = sorted(_extract_names_from_ast(elt))
            result.append(tuple(elt_names))
    return tuple(result)


def _get_if_branch_bodies(if_node):
    bodies = [if_node.body]
    current_orelse = if_node.orelse
    while current_orelse:
        if len(current_orelse) == 1 and isinstance(current_orelse[0], ast.If):
            elif_node = current_orelse[0]
            bodies.append(elif_node.body)
            current_orelse = elif_node.orelse
        else:
            bodies.append(current_orelse)
            break
    return bodies


def _find_result_list_assigns(body):
    assigns = []
    for stmt in body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == 'result':
                    if isinstance(stmt.value, ast.List):
                        assigns.append(stmt.value)
    return assigns


def _detect_permutation_factors(func_node, param_names):
    param_set = set(param_names)
    perm_factors = set()

    for node in ast.walk(func_node):
        if not isinstance(node, ast.If):
            continue

        cond_names = _extract_names_from_ast(node.test) & param_set
        if not cond_names:
            continue

        branch_sequences = []
        for branch_body in _get_if_branch_bodies(node):
            result_assigns = _find_result_list_assigns(branch_body)
            if not result_assigns:
                continue
            seq = _extract_ordered_names_from_list(result_assigns[-1])
            branch_sequences.append(seq)

        if len(branch_sequences) >= 2:
            if any(branch_sequences[i] != branch_sequences[j]
                   for i in range(len(branch_sequences))
                   for j in range(i + 1, len(branch_sequences))):
                perm_factors.update(cond_names)

    return perm_factors


def _check_source_missing(constraints_path):
    if not constraints_path or not os.path.exists(constraints_path):
        return []

    with open(constraints_path, 'r', encoding='utf-8') as f:
        source = f.read()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    solves_funcs = {}
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Name):
                continue
            if dec.func.id != 'solves':
                continue
            if not dec.args or not isinstance(dec.args[0], ast.Constant):
                continue
            target = dec.args[0].value
            sources_kw = next((kw.value for kw in dec.keywords if kw.arg == 'sources'), None)
            if not sources_kw or not isinstance(sources_kw, ast.List):
                continue
            sources = [elt.value for elt in sources_kw.elts if isinstance(elt, ast.Constant)]
            params = [arg.arg for arg in node.args.args]
            param_to_factor = dict(zip(params, sources)) if len(params) == len(sources) else {}
            solves_funcs[target] = {
                'sources': sources, 'node': node, 'params': params,
                'param_to_factor': param_to_factor,
            }

    perm_factors = {}
    for target, info in solves_funcs.items():
        pf_params = _detect_permutation_factors(info['node'], info['params'])
        if pf_params:
            pf_factors = set()
            for p in pf_params:
                factor_name = info['param_to_factor'].get(p, p)
                pf_factors.add(factor_name)
            perm_factors[target] = pf_factors

    warnings = []
    for target, info in solves_funcs.items():
        needed = set()
        via = {}
        for src in info['sources']:
            if src.endswith('.shape') and src in perm_factors:
                for pf in perm_factors[src]:
                    needed.add(pf)
                    via[pf] = src
        missing = needed - set(info['sources'])
        for m in sorted(missing):
            shape_src = via[m]
            suggested = info['sources'] + [m]
            warnings.append(
                f"[SOURCE-MISSING] {target} 消费 {shape_src}，"
                f"后者受排列型因子 {m} 影响，"
                f"但 {target} 的 sources 中不包含 {m}\n"
                f"  → 建议: sources={suggested}"
            )

    return warnings


def _extract_value_constraints_from_param_desc(param_desc_path):
    """从 01_parameter_description.md 的'取值范围'列提取值域约束"""
    if not param_desc_path or not os.path.exists(param_desc_path):
        return {}

    constraints = {}
    with open(param_desc_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    in_param_table = False
    header_line_idx = None
    range_col_idx = None
    type_col_idx = None
    param_col_idx = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('| 参数名 |'):
            in_param_table = True
            header_line_idx = i
            cells = [c.strip() for c in stripped.split('|')]
            for idx, cell in enumerate(cells):
                if cell == '参数名':
                    param_col_idx = idx
                elif cell == '类型':
                    type_col_idx = idx
                elif cell == '取值范围':
                    range_col_idx = idx
            continue
        if in_param_table and header_line_idx is not None:
            if i == header_line_idx + 1:
                continue
            if not stripped.startswith('|'):
                in_param_table = False
                continue

            cells = [c.strip() for c in stripped.split('|')]
            if param_col_idx and param_col_idx < len(cells):
                param_name = cells[param_col_idx]
            else:
                continue
            if type_col_idx and type_col_idx < len(cells):
                param_type = cells[type_col_idx]
            else:
                param_type = ''
            if range_col_idx and range_col_idx < len(cells):
                range_text = cells[range_col_idx]
            else:
                range_text = ''

            if not range_text or range_text in ('-', '不适用', '不适用（输出参数）'):
                continue

            expr = None
            lo = None
            hi = None
            op = None
            unparsed = False

            m = re.search(r'推断值域[：:]\s*>\s*(\d+(?:\.\d+)?)', range_text)
            if m:
                lo = float(m.group(1))
                op = '>'
                expr = f'>{lo}'
            if not op:
                m = re.search(r'推断值域[：:]\s*≥\s*(\d+(?:\.\d+)?)', range_text)
                if m:
                    lo = float(m.group(1))
                    op = '>='
                    expr = f'≥{lo}'
            if not op:
                m = re.search(r'推断值域[：:]\s*<\s*(\d+(?:\.\d+)?)', range_text)
                if m:
                    hi = float(m.group(1))
                    op = '<'
                    expr = f'<{hi}'
            if not op:
                m = re.search(r'推断值域[：:]\s*≤\s*(\d+(?:\.\d+)?)', range_text)
                if m:
                    hi = float(m.group(1))
                    op = '<='
                    expr = f'≤{hi}'
            if not op:
                m = re.search(r'推断值域[：:]\s*∈\s*\[(\d+(?:\.\d+)?),\s*(\d+(?:\.\d+)?)\]', range_text)
                if m:
                    lo = float(m.group(1))
                    hi = float(m.group(2))
                    op = 'range'
                    expr = f'∈[{lo},{hi}]'
            if not op:
                m = re.search(r'>\s*(\d+(?:\.\d+)?)', range_text)
                if m and '推断值域' not in range_text:
                    lo = float(m.group(1))
                    op = '>'
                    expr = f'>{lo}'
            if not op:
                m = re.search(r'≥\s*(\d+(?:\.\d+)?)', range_text)
                if m and '推断值域' not in range_text:
                    lo = float(m.group(1))
                    op = '>='
                    expr = f'≥{lo}'
            if not op and ('推断值域' in range_text or '且' in range_text or '或' in range_text):
                expr = range_text
                unparsed = True

            if expr:
                constraints[param_name] = {
                    'expr': expr,
                    'op': op,
                    'lo': lo,
                    'hi': hi,
                    'granularity': 'element' if '每个元素' in range_text else 'scalar',
                    'source_line': i + 1,
                    'unparsed': unparsed,
                    'type': param_type,
                }

    return constraints


def _check_value_constraint_propagation(factors_path, constraints_path):
    """检查 01 的值域约束是否在 YAML 或 04 中有下游实现"""
    design_dir = os.path.dirname(os.path.abspath(factors_path))
    param_desc_path = os.path.join(design_dir, "01_parameter_description.md")

    if not os.path.exists(param_desc_path):
        return True, []

    constraints = _extract_value_constraints_from_param_desc(param_desc_path)
    if not constraints:
        return True, []

    import yaml
    try:
        with open(factors_path, 'r', encoding='utf-8') as f:
            factors = yaml.safe_load(f)
    except Exception:
        return True, []

    solves_targets = set()
    if constraints_path and os.path.exists(constraints_path):
        with open(constraints_path, 'r', encoding='utf-8') as f:
            code = f.read()
        solves_targets = set(re.findall(r"@solves\(['\"]([^'\"]+)", code))

    warnings = []
    for param, constraint in constraints.items():
        if constraint.get('unparsed') and not constraint.get('op'):
            continue

        pdef = factors.get('parameters', factors).get(param, {})
        if isinstance(pdef, dict):
            fkeys = list(pdef.get('factors', {}).keys())
        else:
            fkeys = []

        has_vr = any('value_range' in k for k in fkeys)
        has_value = any(k.endswith('.value') and 'value_range' not in k for k in fkeys)
        has_solves = any(t.startswith(f'{param}.value') for t in solves_targets)

        if not has_vr and not has_value and not has_solves:
            warnings.append(
                f"[VALUE-DOMAIN-GAP] {param}: 01 has value domain constraint "
                f"'{constraint['expr']}' (line {constraint.get('source_line', '?')}) "
                f"but no value_range / .value / @solves defined. "
                f"Engine will use DEFAULT_VALUE_RANGES which may violate the constraint."
            )

    return len(warnings) == 0, warnings


def _check_dtype_equality(factors_path, constraints_path, engine):
    """检测 dtype @solves 函数中的等值替换错误 (DTYPE-EQUALITY-SUSPECT)"""
    if not constraints_path or not os.path.exists(constraints_path):
        return True

    with open(constraints_path, 'r', encoding='utf-8') as f:
        code = f.read()

    suspects = []

    strategy_patterns = [
        (r'#\s*(R\d+)\s*.*?→\s*(\w+)\s*\[.*?(?:推导|可转换|推导规则|互推导|类型可转换).*?\]',
         'inference'),
        (r'#\s*(R\d+)\s*.*?→\s*(\w+)\s*\[.*?模式\s*1\.5.*?\]',
         'inference'),
        (r'#\s*(R\d+)\s*.*?→\s*(\w+)\s*\[.*?模式\s*2[^\d].*?\]',
         'conversion'),
    ]

    dtype_funcs = {}
    for line in code.split('\n'):
        for pat, stype in strategy_patterns:
            m = re.search(pat, line)
            if m:
                r_id, func_name = m.group(1), m.group(2)
                if '.dtype' in line:
                    dtype_funcs[func_name] = (r_id, stype)

    for func_name, (r_id, stype) in dtype_funcs.items():
        func_match = re.search(
            rf'def\s+{re.escape(func_name)}\s*\([^)]*\):\s*(.*?)(?=\n@|def\s|\Z)',
            code, re.DOTALL
        )
        if not func_match:
            continue
        body = func_match.group(1)

        trace_lines = [l for l in code.split('\n') if func_name in l and l.strip().startswith('#')]
        is_mode1 = any('类型等值' in l or '模式 1' in l or '模式1' in l for l in trace_lines)

        if re.search(r'return\s+\w+_dtype\s*$', body, re.MULTILINE):
            if not is_mode1:
                suspects.append((r_id, func_name, 'return source_dtype (等值替换)'))

        if re.search(r'Candidates\(\[\s*\w+_dtype\s*\]\s*\)', body):
            if not is_mode1:
                suspects.append((r_id, func_name, 'Candidates([source_dtype]) (单值退化)'))

    if suspects:
        print(f"\n[DTYPE-EQUALITY-SUSPECT] 检测到 {len(suspects)} 个疑似等值替换:")
        for r_id, func_name, pattern in suspects:
            print(f"  {r_id}: {func_name}() -> {pattern}")
        print("  建议: 使用 infer_two_dtypes / can_convert_dtype 替代直接返回锚点值")
        return False

    print("[INFO] dtype 等值替换检测通过: 未发现疑似等值替换")
    return True


def _parse_args(argv):
    factors_path = None
    constraints_path = None
    param_desc_path = None
    seed = None
    topology_out = None
    topology_only = False
    validate = False
    sample_size = 100
    max_total = None
    deprecated_output = None

    positional = []
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--constraints":
            i += 1
            if i < len(argv):
                constraints_path = argv[i]
        elif arg == "--param-desc":
            i += 1
            if i < len(argv):
                param_desc_path = argv[i]
        elif arg == "--seed":
            i += 1
            if i < len(argv):
                seed = int(argv[i])
        elif arg == "--topology-out":
            i += 1
            if i < len(argv):
                topology_out = argv[i]
        elif arg == "--topology-only":
            topology_only = True
        elif arg == "--validate":
            validate = True
        elif arg == "--sample-size":
            i += 1
            if i < len(argv):
                sample_size = int(argv[i])
        elif arg == "--max-total":
            i += 1
            if i < len(argv):
                max_total = int(argv[i])
        elif arg == "--max-cases":
            i += 1
        elif not arg.startswith("--"):
            positional.append(arg)
        i += 1

    if len(positional) >= 1:
        factors_path = positional[0]
    if len(positional) >= 2:
        deprecated_output = positional[1]

    return {
        "factors_path": factors_path,
        "constraints_path": constraints_path,
        "param_desc_path": param_desc_path,
        "seed": seed,
        "topology_out": topology_out,
        "topology_only": topology_only,
        "validate": validate,
        "sample_size": sample_size,
        "max_total": max_total,
        "deprecated_output": deprecated_output,
    }


def _check_reverse_validation_table(param_desc_path):
    """检查 01_parameter_description.md 中反向校验表是否存在 MISMATCH 项"""
    if not param_desc_path or not os.path.exists(param_desc_path):
        return True

    with open(param_desc_path, 'r', encoding='utf-8') as f:
        content = f.read()

    marker = '## 约束提取反向校验表'
    idx = content.find(marker)
    if idx == -1:
        print("[WARN] 01_parameter_description.md 未包含反向校验表（步骤3.4未执行或未产出）")
        return True

    table_text = content[idx:]
    mismatches = []
    for line in table_text.split('\n'):
        stripped = line.strip()
        if not stripped.startswith('|'):
            continue
        cells = [c.strip() for c in stripped.split('|')]
        cells = [c for c in cells if c]
        if len(cells) < 6:
            continue
        if cells[0] in ('R{n}', '------', '---'):
            continue
        status = cells[5].strip()
        if status == 'MISMATCH':
            mismatches.append({
                'r_id': cells[0],
                'constraint': cells[1],
                'original': cells[2],
                'symbolized': cells[3],
                'transcribed': cells[4],
            })

    if mismatches:
        print("\n[ERROR] 约束提取反向校验失败：以下约束项与原文不一致")
        for m in mismatches:
            print(f"[ERROR]   {m['r_id']} {m['constraint']}: "
                  f"原文 {m['original']} → 符号化 {m['symbolized']}, "
                  f"转录为 {m['transcribed']}")
        print("[ERROR] 请修正 01_parameter_description.md 中对应约束后重新 --validate")
        return False

    print("[INFO] 约束提取反向校验通过: 无 MISMATCH 项")
    return True


def _check_constraint_conservation(factors_path, constraints_path):
    """检查 01 中每个 R{n} 都在 validate_constraints 中有对应校验（AST 语义检测）"""
    design_dir = os.path.dirname(os.path.abspath(factors_path))
    param_desc_path = os.path.join(design_dir, "01_parameter_description.md")

    if not os.path.exists(param_desc_path):
        return True

    r_ids_in_01 = set()
    with open(param_desc_path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r'###\s+(R\d+)', line.strip())
            if m:
                r_ids_in_01.add(m.group(1))

    if not r_ids_in_01:
        return True

    if not constraints_path or not os.path.exists(constraints_path):
        for r_id in sorted(r_ids_in_01):
            print(f"[CONSTRAINT-CONSERVATION] {r_id} 存在于 01 但 04 不存在")
        return False

    with open(constraints_path, 'r', encoding="utf-8") as f:
        code = f.read()

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        print(f"[CONSTRAINT-CONSERVATION] 04 语法错误: {e}")
        return False

    validate_func_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'validate_constraints':
            validate_func_node = node
            break

    if validate_func_node is None:
        for r_id in sorted(r_ids_in_01):
            print(f"[CONSTRAINT-CONSERVATION] {r_id}: validate_constraints 未定义")
        return False

    called_rns = set()
    for node in ast.walk(validate_func_node):
        if isinstance(node, ast.Call):
            func = node.func
            func_name = None
            if isinstance(func, ast.Name):
                func_name = func.id
            elif isinstance(func, ast.Attribute):
                func_name = func.attr
            if func_name:
                m = re.match(r'_validate_r(\d+)$', func_name)
                if m:
                    called_rns.add(f'R{m.group(1)}')

    for node in ast.walk(validate_func_node):
        if isinstance(node, (ast.Tuple, ast.List)):
            for elt in node.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    if re.match(r'R\d+$', elt.value):
                        called_rns.add(elt.value)

    validate_funcs = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            m = re.match(r'_validate_r(\d+)$', node.name)
            if m:
                validate_funcs.add(f'R{m.group(1)}')

    missing = sorted(r_ids_in_01 - called_rns)
    if missing:
        print(f"\n[CONSTRAINT-CONSERVATION] 以下约束未在 validate_constraints 中校验:")
        for r_id in missing:
            if r_id in validate_funcs:
                print(f"  {r_id}: 存在 _validate_{r_id.lower()} 但未被调用")
            else:
                print(f"  {r_id}: 无对应校验函数（需新增 _validate_{r_id.lower()}）")
        print(f"  → 按「修复唯一方向」原则补充校验函数")
        return False

    print(f"[INFO] [CONSTRAINT-CONSERVATION] 约束守恒校验通过")
    return True


def _check_validate_helper_isolation(constraints_path):
    if not constraints_path or not os.path.exists(constraints_path):
        return []

    with open(constraints_path, 'r', encoding='utf-8') as f:
        source = f.read()

    import ast
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    solves_funcs = {}
    validate_funcs = {}
    user_helpers = set()

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        is_solves = any(
            isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == 'solves'
            for d in node.decorator_list
        )
        if is_solves:
            solves_funcs[node.name] = node
        elif node.name == 'validate_constraints' or node.name.startswith('_validate_'):
            validate_funcs[node.name] = node
        else:
            user_helpers.add(node.name)

    if not user_helpers or not solves_funcs or not validate_funcs:
        print("[INFO] validate_constraints 辅助函数隔离检测通过: 无共享辅助函数")
        return []

    def _called_helpers(func_node):
        return {child.func.id for child in ast.walk(func_node)
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                and child.func.id in user_helpers}

    solves_callees = {}
    for fname, fnode in solves_funcs.items():
        for h in _called_helpers(fnode):
            solves_callees.setdefault(h, []).append(fname)

    validate_callees = {}
    for fname, fnode in validate_funcs.items():
        for h in _called_helpers(fnode):
            validate_callees.setdefault(h, []).append(fname)

    overlap = set(solves_callees.keys()) & set(validate_callees.keys())
    if overlap:
        print(f"\n[VALIDATE-HELPER-OVERLAP] 检测到 {len(overlap)} 个辅助函数"
              f"被 @solves 和 validate_constraints 共同引用:")
        for helper in sorted(overlap):
            sl = ', '.join(sorted(solves_callees[helper]))
            vl = ', '.join(sorted(validate_callees[helper]))
            print(f"  {helper}: 被 @solves({sl}) 和 validate({vl}) 共用")
        print("  建议: 在 validate_constraints 中从 01_parameter_description.md "
              "原样独立转录计算逻辑，不依赖 @solves 使用的辅助函数")
        return list(overlap)

    print("[INFO] validate_constraints 辅助函数隔离检测通过: "
          "@solves 与 validate_constraints 无共享辅助函数")
    return []


def _run_validate(engine, sample_size, topology_out, factors_path, constraints_path, param_desc_path=None):
    engine._validate_mode = True
    print(f"\nValidating constraints (sample_size={sample_size})...")
    cases = engine.solve(max_cases=sample_size)

    if topology_out:
        engine.generate_topology_report(topology_out)
        print(f"\nTopology report saved to: {topology_out}")

    print_summary(cases)

    trace_ok = _check_constraint_traceability(factors_path, constraints_path)
    dtype_ok = _check_dtype_equality(factors_path, constraints_path, engine)
    domain_ok = engine._report_domain_reachability()
    coverage_errors, coverage_warnings = _check_validate_coverage(factors_path, constraints_path)

    source_unused_warnings = _check_sources_unused(constraints_path)
    for w in source_unused_warnings:
        print(f"  {w}")

    domain_prop_ok, domain_prop_warnings = _check_value_constraint_propagation(factors_path, constraints_path)
    for w in domain_prop_warnings:
        print(f"  {w}")

    reverse_ok = _check_reverse_validation_table(param_desc_path)

    helper_overlap_warnings = _check_validate_helper_isolation(constraints_path)

    source_missing_warnings = _check_source_missing(constraints_path)
    for w in source_missing_warnings:
        print(f"  {w}")

    conservation_ok = _check_constraint_conservation(factors_path, constraints_path)

    has_source_unused = bool(source_unused_warnings)
    has_domain_gap = not domain_prop_ok
    has_helper_overlap = bool(helper_overlap_warnings)
    has_source_missing = bool(source_missing_warnings)

    has_contract = bool(engine._solve_failures)
    if (has_contract or not trace_ok or not dtype_ok or not domain_ok
            or coverage_errors or has_source_unused or has_domain_gap
            or not reverse_ok or not conservation_ok):
        print("\n[ERROR] 校验未通过，请修复后重试")
        sys.exit(1)
    elif coverage_warnings or has_helper_overlap or has_source_missing:
        notices = []
        if coverage_warnings:
            notices.append("TRACE-COVERAGE-WARN")
        if has_helper_overlap:
            notices.append("VALIDATE-HELPER-OVERLAP")
        if has_source_missing:
            notices.append("SOURCE-MISSING")
        print(f"\n[WARN] 校验通过（存在需确认的告警项），请检查 {' / '.join(notices)} 后继续")
    else:
        print("\n[INFO] 校验通过，可进行用例生成（步骤 4 阶段B）")


def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_factor_values.py <design/02_test_factors.yaml> --validate --constraints <design/04_constraints.py>")
        print("       python generate_factor_values.py <design/02_test_factors.yaml> --topology-only --topology-out <design/05_topology.md>")
        print("       (单一 design/ 目录，接口类型由 00_interface_type.yaml 决定)")
        sys.exit(1)

    args = _parse_args(sys.argv)

    if not args["factors_path"]:
        print("Error: factors YAML path required")
        sys.exit(1)
    if not Path(args["factors_path"]).exists():
        print(f"Error: file not found: {args['factors_path']}")
        sys.exit(1)
    if args["constraints_path"] and not Path(args["constraints_path"]).exists():
        print(f"Error: constraints file not found: {args['constraints_path']}")
        sys.exit(1)

    if not args["validate"] and not args["topology_only"]:
        if args["deprecated_output"]:
            print("[WARN] 全量求解 + CSV 模式已废弃，请使用 --validate 或 --topology-only", file=sys.stderr)
            print("[WARN] 忽略输出路径参数，切换为 --validate 模式", file=sys.stderr)
            args["validate"] = True
        else:
            print("Error: 请指定 --validate 或 --topology-only 模式")
            print("  --validate       校验模式：少量样本试探性求解，输出满足率报告")
            print("  --topology-only  仅生成拓扑可视化文件")
            sys.exit(1)

    from solver.engine import FactorValueEngine

    print("Loading factors and constraints...")
    print(f"  - Test factors: {args['factors_path']}")
    if args["constraints_path"]:
        print(f"  - Constraints: {args['constraints_path']}")

    effective_max_total = args["max_total"]
    if effective_max_total is None:
        if args["validate"]:
            effective_max_total = max(args["sample_size"] * 10, 1000)
        else:
            effective_max_total = 100000

    engine = FactorValueEngine(
        max_expansion=128,
        max_total=effective_max_total,
        seed=args["seed"],
    )
    engine.load(args["factors_path"], args["constraints_path"])

    print(f"\nAnchors: {len(engine.anchors)}")
    print(f"Explicit constraints: {len(engine.constraints)}")
    print(f"Built-in rules: {len(engine.builtin_rules)}")

    if args["topology_only"]:
        topo_path = args["topology_out"] or args["factors_path"].replace(".yaml", "_topology.md")
        engine.generate_topology_report(topo_path)
        print(f"\nTopology report saved to: {topo_path}")
        return

    if args["validate"]:
        _run_validate(
            engine,
            sample_size=args["sample_size"],
            topology_out=args["topology_out"],
            factors_path=args["factors_path"],
            constraints_path=args["constraints_path"],
            param_desc_path=args.get("param_desc_path"),
        )


if __name__ == "__main__":
    main()
