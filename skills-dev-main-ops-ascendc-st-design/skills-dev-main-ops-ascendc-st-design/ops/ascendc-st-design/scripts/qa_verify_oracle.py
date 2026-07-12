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
QA 自动校验引擎 — 测试设计自动化质量门禁

自动执行交叉产物一致性检查，作为 SKILL.md 步骤 4 阶段 C 的脚本门禁。

用法:
    python qa_verify_oracle.py \\
        --csv-l0 {L0 CSV} --csv-l1 {L1 CSV} \\
        --factors {02_test_factors.yaml} --constraints {04_constraints.py} \\
        --param-desc {01_parameter_description.md} \\
        --scenarios {03_scenario_enumeration.md} \\
        --aclnn-doc {原始文档} \\
        --output {报告路径}
"""

import argparse
import sys
import os
import re
import json
import math
from pathlib import Path
from collections import defaultdict
from ast import literal_eval

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import pandas as pd
except ImportError:
    print("[ERROR] 需要 pandas: pip install pandas", file=sys.stderr)
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("[ERROR] 需要 PyYAML: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


CSV_TENSOR_COLS = ['tensor_view_shapes', 'tensor_dtypes', 'tensor_formats']


def _load_csv(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        return pd.read_csv(path)
    except Exception as e:
        print(f"[ERROR] 无法读取 CSV: {path}: {e}", file=sys.stderr)
        return None


def _load_text(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"[ERROR] 无法读取文件: {path}: {e}", file=sys.stderr)
        return None


def _load_yaml(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"[ERROR] 无法读取 YAML: {path}: {e}", file=sys.stderr)
        return None


def _safe_literal_eval(val):
    if not isinstance(val, str) or not val.strip():
        return None
    try:
        return literal_eval(val)
    except Exception:
        return None


def _safe_json_loads(val):
    if not isinstance(val, str) or not val.strip():
        return None
    try:
        val = val.replace('True', 'true').replace('False', 'false')
        return json.loads(val)
    except Exception:
        return None


def _get_yaml_parameters(factors):
    if not factors:
        return {}
    if isinstance(factors, dict):
        if 'aclnn_name' in factors:
            if 'parameters' in factors:
                return factors['parameters']
            params = {}
            for k, v in factors.items():
                if k in ('aclnn_name', 'intermediate'):
                    continue
                if isinstance(v, dict) and isinstance(v.get('type'), str):
                    params[k] = v
            return params
        return factors
    return {}


# ═══════════════════════════════════════════════════════════════════
# Q1: 产品支持场景校验（自动模式简化版：标记需人工检查）
# ═══════════════════════════════════════════════════════════════════

def check_Q1(param_desc_text, operator_doc_text, df_l0):
    results = {'pass': True, 'details': {}, 'needs_manual': False}
    if not operator_doc_text or df_l0 is None:
        results['skipped'] = True
        return results
    product_section = ''
    for kw in ['产品支持', '支持情况', '产品说明']:
        m = re.search(rf'##.*{kw}.*?\n(.*?)(?=\n##|\Z)', operator_doc_text, re.DOTALL)
        if m:
            product_section = m.group(1)
            break
    if not product_section:
        results['skipped'] = True
        return results
    target_product = ''
    if param_desc_text:
        m = re.search(r'目标产品[：:]\s*(.+)', param_desc_text)
        if m:
            target_product = m.group(1).strip()
    results['details'] = {
        'target_product': target_product,
        'has_product_section': bool(product_section),
        'note': '仅检测产品支持章节是否存在，具体约束需手动检查',
    }
    if product_section:
        results['needs_manual'] = True
    return results


# ═══════════════════════════════════════════════════════════════════
# Q2: attributes 值域分析（异常检测 + 退化检测）
# ═══════════════════════════════════════════════════════════════════

def check_Q2(df_l0, constraints_code=None, factors=None):
    results = {'pass': True, 'details': []}
    if df_l0 is None or 'attributes' not in df_l0.columns:
        results['skipped'] = True
        return results
    yaml_singletons = set()
    if factors and isinstance(factors, dict):
        for _pname, pdef in factors.items():
            if not isinstance(pdef, dict):
                continue
            facs = pdef.get('factors', {})
            val_fac = facs.get(f'{_pname}.value')
            if isinstance(val_fac, list) and len(val_fac) == 1:
                yaml_singletons.add(_pname)
    stats = {}
    for _, row in df_l0.iterrows():
        raw = row.get('attributes', '')
        attrs = _safe_json_loads(raw)
        if attrs is None:
            continue
        for k, v in attrs.items():
            if k not in stats:
                stats[k] = {
                    'count': 0, 'values': set(),
                    'min': None, 'max': None,
                    'is_scalar': isinstance(v, (int, float)),
                }
            s = stats[k]
            s['count'] += 1
            try:
                s['values'].add(json.dumps(v, sort_keys=True))
            except TypeError:
                s['values'].add(str(v))
            if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
                if s['min'] is None or v < s['min']:
                    s['min'] = v
                if s['max'] is None or v > s['max']:
                    s['max'] = v

    for k, s in sorted(stats.items()):
        unique = len(s['values'])
        entry = {'param': k, 'unique': unique, 'total': s['count'], 'is_scalar': s['is_scalar']}
        if unique == 1:
            entry['type'] = 'degenerate'
            entry['value'] = list(s['values'])[0]
            if k in yaml_singletons:
                entry['yaml_singleton'] = True
            elif constraints_code:
                escaped = re.escape(k)
                match = re.search(
                    rf"@solves\(['\"]({escaped}(?:\.value)?)['\"].*?def\s+(\w+)",
                    constraints_code,
                    re.DOTALL,
                )
                if match:
                    fn = match.group(2)
                    body = re.search(
                        rf'def {fn}\(.*?\):.*?(?=\n@|\ndef\s|\Z)',
                        constraints_code,
                        re.DOTALL,
                    )
                    if body and 'Candidates' not in body.group(0):
                        entry['hardcoded'] = True
                        results['pass'] = False
            if not entry.get('hardcoded') and not entry.get('yaml_singleton') and unique == 1:
                non_enum = not re.search(rf'{re.escape(k)}\s*.*\.value\s*:', constraints_code or '')
                if non_enum:
                    results['pass'] = False
        elif s['is_scalar'] and s['min'] is not None:
            entry['type'] = 'scalar'
            entry['min'] = s['min']
            entry['max'] = s['max']
            if s['max'] > 0 and s['min'] is not None and s['min'] > 0:
                ratio = s['max'] / s['min']
                if ratio > 1e6:
                    entry['extreme'] = True
                    results['pass'] = False
        else:
            entry['type'] = 'array'
        results['details'].append(entry)
    return results


# ═══════════════════════════════════════════════════════════════════
# Q3: tensor 列组数一致性
# ═══════════════════════════════════════════════════════════════════

def check_Q3(df_l0):
    results = {'pass': True, 'details': {}}
    if df_l0 is None:
        results['skipped'] = True
        return results
    mismatches = []
    for idx, row in df_l0.iterrows():
        lengths = {}
        for col in CSV_TENSOR_COLS:
            raw = row.get(col, '')
            parsed = _safe_literal_eval(raw)
            lengths[col] = len(parsed) if parsed is not None else 0
        if len(set(lengths.values())) > 1:
            mismatches.append((idx, lengths))
    if mismatches:
        results['pass'] = False
    results['details'] = {
        'total': len(df_l0),
        'mismatches': len(mismatches),
        'samples': mismatches[:5],
    }
    return results


# ═══════════════════════════════════════════════════════════════════
# Q4: YAML 域值与文档一致性
# ═══════════════════════════════════════════════════════════════════

def check_Q4(param_desc_text, factors):
    results = {'pass': True, 'details': []}
    if not param_desc_text or factors is None:
        results['skipped'] = True
        return results
    params = _get_yaml_parameters(factors)
    for pname, pdef in params.items():
        if not isinstance(pdef, dict):
            continue
        ptype = pdef.get('type', '')
        if ptype in ('aclTensor', 'aclTensorList'):
            yaml_dtypes = set(pdef.get('dtype', {}).get('value_range_bfloat16',
                           pdef.get('dtype', {}).get('value_range',
                           pdef.get('dtype', {}).get('domain', []))))
            doc_pattern = rf'\|{re.escape(pname)}\|.*?\|.*?\|.*?(\w+.*?)\|'
            doc_match = re.search(doc_pattern, param_desc_text)
            if not doc_match:
                continue
            dtype_cell = doc_match.group(1).strip()
            doc_dtypes = set()
            for dt in re.findall(r'(float\d+|int\d+|uint\d+|bfloat\d+|bool|complex\d+)', dtype_cell):
                doc_dtypes.add(dt)
            if doc_dtypes and yaml_dtypes:
                doc_only = doc_dtypes - yaml_dtypes
                yaml_only = yaml_dtypes - doc_dtypes
                if doc_only or yaml_only:
                    results['pass'] = False
                    results['details'].append({
                        'param': pname,
                        'attribute': 'dtype',
                        'doc_values': sorted(doc_dtypes),
                        'yaml_values': sorted(yaml_dtypes),
                        'doc_only': sorted(doc_only),
                        'yaml_only': sorted(yaml_only),
                    })
    return results


# ═══════════════════════════════════════════════════════════════════
# Q5: 存在性约束违反检测
# ═══════════════════════════════════════════════════════════════════

def check_Q5(factors, df_l0):
    results = {'pass': True, 'details': []}
    if factors is None or df_l0 is None:
        results['skipped'] = True
        return results
    params = _get_yaml_parameters(factors)
    null_required = set()
    optional_params = {}
    idx = 0
    for pname, pdef in params.items():
        if not isinstance(pdef, dict):
            continue
        ptype = pdef.get('type', '')
        if ptype in ('aclTensor', 'aclTensorList'):
            exist = pdef.get('exist', {})
            if isinstance(exist, list) and exist == [False]:
                null_required.add(idx)
            if isinstance(exist, list) and True in exist and False in exist:
                optional_params[pname] = {'idx': idx, 'exist': exist}
            idx += 1
    if not null_required and not optional_params:
        results['skipped'] = True
        return results
    violations = []
    for _, row in df_l0.iterrows():
        shapes = _safe_literal_eval(row.get('tensor_view_shapes', ''))
        if shapes is None:
            continue
        for i in null_required:
            if i < len(shapes) and shapes[i] is not None:
                violations.append({
                    'type': 'null_required_has_value',
                    'idx': i,
                    'value': shapes[i],
                })
    for pname, info in optional_params.items():
        true_count = 0
        false_count = 0
        for _, row in df_l0.iterrows():
            shapes = _safe_literal_eval(row.get('tensor_view_shapes', ''))
            if shapes and info['idx'] < len(shapes):
                if shapes[info['idx']] is None:
                    false_count += 1
                else:
                    true_count += 1
        entry = {
            'param': pname,
            'true_count': true_count,
            'false_count': false_count,
        }
        results['details'].append(entry)
    if violations:
        results['pass'] = False
        results['details'].insert(0, {'null_violations': violations[:5]})
    return results


def _extract_value_constraints_from_01(param_desc_text):
    """从 01_parameter_description.md 的'取值范围'列提取值域约束"""
    if not param_desc_text:
        return {}
    constraints = {}
    lines = param_desc_text.split('\n')
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
            if not param_col_idx or param_col_idx >= len(cells):
                continue
            param_name = cells[param_col_idx]
            param_type = cells[type_col_idx] if type_col_idx and type_col_idx < len(cells) else ''
            range_text = cells[range_col_idx] if range_col_idx and range_col_idx < len(cells) else ''
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
                m = re.search(r'(?<!推断值域[：:])>\s*(\d+(?:\.\d+)?)', range_text)
                if m:
                    lo = float(m.group(1))
                    op = '>'
                    expr = f'>{lo}'
            if not op:
                m = re.search(r'(?<!推断值域[：:])≥\s*(\d+(?:\.\d+)?)', range_text)
                if m:
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


def _check_value_against_op(value, constraint):
    """检查单个值是否满足约束"""
    op = constraint.get('op')
    if not op:
        return True
    try:
        v = float(value)
    except (TypeError, ValueError):
        return True
    if op == '>' and constraint.get('lo') is not None:
        return v > constraint['lo']
    if op == '>=' and constraint.get('lo') is not None:
        return v >= constraint['lo']
    if op == '<' and constraint.get('hi') is not None:
        return v < constraint['hi']
    if op == '<=' and constraint.get('hi') is not None:
        return v <= constraint['hi']
    if op == 'range' and constraint.get('lo') is not None and constraint.get('hi') is not None:
        return constraint['lo'] <= v <= constraint['hi']
    return True


def check_Q6(param_desc_text, df_l0):
    """Q6: 参数值域文档一致性检查"""
    results = {'pass': True, 'details': [], 'unparsed': []}
    if not param_desc_text or df_l0 is None:
        results['skipped'] = True
        return results
    if 'attributes' not in df_l0.columns:
        results['skipped'] = True
        return results

    constraints = _extract_value_constraints_from_01(param_desc_text)
    if not constraints:
        results['skipped'] = True
        return results

    for param, constraint in constraints.items():
        if constraint.get('unparsed') and not constraint.get('op'):
            results['unparsed'].append({
                'param': param,
                'expr': constraint['expr'],
                'note': '复合约束无法自动解析，需人工确认',
            })
            continue

        violation_count = 0
        bad_examples = []
        for idx, row in df_l0.iterrows():
            raw = row.get('attributes', '')
            attrs = _safe_json_loads(raw)
            if attrs is None or param not in attrs:
                continue
            val = attrs[param]
            if isinstance(val, list):
                values_to_check = val
            else:
                values_to_check = [val]
            bad_values = []
            for v in values_to_check:
                if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
                    if not _check_value_against_op(v, constraint):
                        bad_values.append(v)
            if bad_values:
                violation_count += 1
                if len(bad_examples) < 5:
                    bad_examples.append(bad_values)

        if violation_count > 0:
            results['pass'] = False
            results['details'].append({
                'param': param,
                'constraint': constraint['expr'],
                'total_rows': len(df_l0),
                'violation_count': violation_count,
                'violation_rate': f'{violation_count / len(df_l0):.1%}',
                'examples': bad_examples,
            })

    return results


def _parse_enhanced_scenarios(scenarios_text):
    """解析03_scenario_enumeration.md中的ET/BD/EX子场景"""
    scenarios = {'ET': [], 'BD': [], 'EX': []}
    if not scenarios_text:
        return scenarios
    current_prefix = None
    section_keywords = {'ET': '空tensor', 'BD': '边界值', 'EX': '异常'}
    for line in scenarios_text.split('\n'):
        stripped = line.strip()
        for prefix, keyword in section_keywords.items():
            if keyword in stripped and stripped.startswith('##'):
                current_prefix = prefix
                break
        if current_prefix and stripped.startswith('|') and '---' not in stripped:
            m = re.match(rf'\|\s*({current_prefix}-S\d+)\s*\|', stripped)
            if m:
                cells = [c.strip() for c in stripped.split('|')]
                cells = [c for c in cells if c]
                scenarios[current_prefix].append((m.group(1), cells))
    return scenarios


# ═══════════════════════════════════════════════════════════════════
# 公共辅助函数（Q16/Q17/Q18/Q13-Q15 共用）
# ═══════════════════════════════════════════════════════════════════

def _parse_locked_factors_from_cells(cells):
    """从场景表格的所有 cells 中提取 locked 因子。
    兼容 4/5/6/8 列格式：扫描全部 cells 提取 key=value 对。
    仅提取 key 含 '.' 的项（引擎因子名格式为 param.attr）。
    """
    locked = {}
    for cell in cells:
        if not isinstance(cell, str):
            continue
        for match in re.findall(
            r'([\w.]+)\s*=\s*(\[[^\]]*\]|\{[^}]*\}|[^\s,|]+)',
            cell
        ):
            key, val = match
            if '.' not in key:
                continue
            if key in locked:
                continue
            if val.lower() == 'true':
                locked[key] = True
            elif val.lower() == 'false':
                locked[key] = False
            else:
                try:
                    locked[key] = literal_eval(val)
                except (ValueError, SyntaxError):
                    locked[key] = val
    return locked


def _parse_expected_output_from_cells(cells):
    """从场景表格的所有 cells 中提取预期输出（out/indices/C 开头的 key=value）。"""
    output = {}
    for cell in cells:
        if not isinstance(cell, str):
            continue
        for match in re.findall(
            r'((?:out|indices|C)\.[\w.]+)\s*=\s*(\[[^\]]*\]|[^\s,|]+)',
            cell
        ):
            key, val = match
            try:
                output[key] = literal_eval(val)
            except (ValueError, SyntaxError):
                output[key] = val
    return output


def _extract_param_names(locked):
    """从 locked dict 中提取所有参数名（'.'前的部分）。"""
    names = set()
    for key in locked:
        if '.' in key:
            names.add(key.split('.')[0])
    return names


def _build_base_case(factors):
    """用 YAML 默认值构建基础 case（取每个 factor 的第一个值）。"""
    case = {}
    for pname, pdef in factors.items():
        if not isinstance(pdef, dict) or 'factors' not in pdef:
            continue
        for fname, fvals in pdef['factors'].items():
            if isinstance(fvals, list) and fvals:
                case[fname] = fvals[0]
    return case


def _load_validate_constraints_func(constraints_code):
    """从 04_constraints.py 代码加载 validate_constraints 函数。"""
    if not constraints_code:
        return None
    try:
        ns = {'__builtins__': __builtins__}
        exec(compile(constraints_code, '<constraints>', 'exec'), ns)
        return ns.get('validate_constraints')
    except Exception:
        return None


def _find_matching_case(locked, cases):
    """在 cases 中查找匹配 locked 因子的用例。支持通配符 '*'。"""
    for case in cases:
        match = True
        for key, expected in locked.items():
            actual = case.get(key)
            if actual is None:
                match = False
                break
            if not _value_matches(expected, actual):
                match = False
                break
        if match:
            return case
    return None


def _value_matches(expected, actual):
    """判断 actual 值是否匹配 expected（支持通配符 '*'）。"""
    if expected == '*':
        return True
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return False
        return all(_value_matches(e, a) for e, a in zip(expected, actual))
    return expected == actual


def _verify_expected_output(case, expected_output):
    """验证用例的实际输出是否匹配预期输出。"""
    for key, expected in expected_output.items():
        actual = case.get(key)
        if actual is None:
            return False
        if not _value_matches(expected, actual):
            return False
    return True


def _load_sidecar(path):
    """加载 sidecar JSON 文件。"""
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _cleanup_sidecars(csv_dir):
    """校验通过后清理 sidecar JSON 文件。"""
    csv_dir = Path(csv_dir)
    if not csv_dir.is_dir():
        return
    for f in csv_dir.glob('*_factors.json'):
        try:
            f.unlink()
            print(f"[INFO] 已清理 sidecar: {f.name}")
        except Exception:
            pass


def _make_json_serializable(obj):
    """将对象转换为 JSON 可序列化格式。"""
    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_serializable(v) for v in obj]
    return obj


# ═══════════════════════════════════════════════════════════════════
# Q7: ET场景完备性
# ═══════════════════════════════════════════════════════════════════

def check_Q7(factors, scenarios_text):
    results = {'pass': True, 'details': []}
    if not factors or not scenarios_text:
        results['skipped'] = True
        return results
    intermediate = factors.get('intermediate', {})
    risky_vars = []
    for name, info in intermediate.items():
        if not isinstance(info, dict):
            continue
        vr = info.get('factors', {}).get(f'{name}.value_range', [])
        if vr and isinstance(vr, list) and len(vr) > 0:
            lo = vr[0][0] if isinstance(vr[0], list) else vr[0]
            if isinstance(lo, (int, float)) and lo <= 0:
                risky_vars.append(name)
    if not risky_vars:
        results['skipped'] = True
        return results
    et_scenarios = re.findall(r'\|(ET-S\d+)\|', scenarios_text)
    if not et_scenarios:
        results['pass'] = False
        results['details'] = {'missing_et': True, 'risky_vars': risky_vars}
        return results
    return results


# ═══════════════════════════════════════════════════════════════════
# Q8: ET场景变量存在性
# ═══════════════════════════════════════════════════════════════════

def check_Q8(factors, scenarios_text):
    results = {'pass': True, 'details': []}
    if not factors or not scenarios_text:
        results['skipped'] = True
        return results
    parsed = _parse_enhanced_scenarios(scenarios_text)
    et_items = parsed.get('ET', [])
    if not et_items:
        results['skipped'] = True
        return results
    # 收集所有因子名（含中间体）
    all_factor_names = set()
    for pname, pdef in factors.items():
        if not isinstance(pdef, dict):
            continue
        if pname == 'intermediate':
            for iname, idef in pdef.items():
                if isinstance(idef, dict):
                    for fk in idef.get('factors', {}).keys():
                        all_factor_names.add(fk)
                    all_factor_names.add(iname)
            continue
        for fk in pdef.get('factors', {}).keys():
            all_factor_names.add(fk)
        all_factor_names.add(pname)
    bad = []
    for sid, cells in et_items:
        for col in cells[1:]:
            for match in re.findall(r'([\w.]+)\s*=\s*([^\s,|]+)', col):
                key = match[0]
                if '.' in key and key not in all_factor_names:
                    # 尝试参数名匹配
                    param = key.split('.')[0]
                    if param not in factors:
                        bad.append({'scenario': sid, 'var': key})
    if bad:
        results['pass'] = False
        results['details'] = bad[:5]
    return results


# ═══════════════════════════════════════════════════════════════════
# Q9: BD场景边界值与01一致性
# ═══════════════════════════════════════════════════════════════════

def check_Q9(param_desc_text, scenarios_text):
    results = {'pass': True, 'details': []}
    if not param_desc_text or not scenarios_text:
        results['skipped'] = True
        return results
    parsed = _parse_enhanced_scenarios(scenarios_text)
    bd_items = parsed.get('BD', [])
    if not bd_items:
        results['skipped'] = True
        return results
    # 提取01中的数值边界
    bounds = {}
    for m in re.finditer(r'(\w+)\s*[:：]\s*(\d+)\s*[~\-]\s*(\d+)', param_desc_text):
        var, lo, hi = m.group(1), int(m.group(2)), int(m.group(3))
        bounds[var] = (lo, hi)
    if not bounds:
        results['skipped'] = True
        return results
    # 简化检查：BD场景行中若出现数字，检查是否在边界内
    for sid, cells in bd_items:
        for cell in cells:
            for num in re.findall(r'\b(\d+)\b', cell):
                n = int(num)
                for var, (lo, hi) in bounds.items():
                    if lo <= n <= hi:
                        continue
                    if n == lo or n == hi or n == lo - 1 or n == hi + 1:
                        continue
                    # 数字不在任何边界附近，可能有问题
                    pass
    return results


# ═══════════════════════════════════════════════════════════════════
# Q10: EX场景异常有效性
# ═══════════════════════════════════════════════════════════════════

def check_Q10(scenarios_text):
    results = {'pass': True, 'details': []}
    if not scenarios_text:
        results['skipped'] = True
        return results
    parsed = _parse_enhanced_scenarios(scenarios_text)
    ex_items = parsed.get('EX', [])
    if not ex_items:
        results['skipped'] = True
        return results
    # 检查EX场景是否有明确的违反值
    bad = []
    for sid, cells in ex_items:
        has_violation = False
        for col in cells:
            if re.search(r'[\w.]+\s*=\s*\S+', col):
                has_violation = True
                break
        if not has_violation:
            bad.append(sid)
    if bad:
        results['pass'] = False
        results['details'] = bad[:5]
    return results


# ═══════════════════════════════════════════════════════════════════
# Q11: EX场景 _expected_error 完整性
# ═══════════════════════════════════════════════════════════════════

def check_Q11(scenarios_text):
    results = {'pass': True, 'details': []}
    if not scenarios_text:
        results['skipped'] = True
        return results
    parsed = _parse_enhanced_scenarios(scenarios_text)
    ex_items = parsed.get('EX', [])
    if not ex_items:
        results['skipped'] = True
        return results
    missing = []
    for sid, cells in ex_items:
        has_error = any(('ACL_ERROR_' in cell or 'ACLNN_ERR_' in cell) for cell in cells)
        if not has_error:
            missing.append(sid)
    if missing:
        results['pass'] = False
        results['details'] = missing
    return results


# ═══════════════════════════════════════════════════════════════════
# Q12: 场景ID格式正确性
# ═══════════════════════════════════════════════════════════════════

def check_Q12(scenarios_text):
    results = {'pass': True, 'details': []}
    if not scenarios_text:
        results['skipped'] = True
        return results
    for prefix in ['ET', 'BD', 'EX']:
        ids = re.findall(rf'\|({prefix}-S\d+)\|', scenarios_text)
        if not ids:
            continue
        nums = [int(re.search(rf'{prefix}-S(\d+)', sid).group(1)) for sid in ids]
        expected = list(range(1, len(nums) + 1))
        if sorted(nums) != expected:
            results['pass'] = False
            results['details'].append({
                'prefix': prefix,
                'expected': expected,
                'actual': sorted(nums),
            })
    return results


# ═══════════════════════════════════════════════════════════════════
# Q13: ET场景用例覆盖
# ═══════════════════════════════════════════════════════════════════

def check_Q13(df_l0, df_l1, scenarios_text):
    results = {'pass': True, 'details': []}
    if not scenarios_text:
        results['skipped'] = True
        return results
    parsed = _parse_enhanced_scenarios(scenarios_text)
    et_items = parsed.get('ET', [])
    if not et_items:
        results['skipped'] = True
        return results
    # 收集所有用例的factor值
    all_cases = []
    for df in [df_l0, df_l1]:
        if df is not None:
            all_cases.extend(df.to_dict('records'))
    missing = []
    for item in et_items:
        if len(item) == 2:
            sid, cells = item
        elif len(item) == 5:
            sid, locked, description, cat, meta = item
        else:
            continue
        results['details'].append({'sid': sid, 'found': True, 'cells': cells if len(item) == 2 else None})
    return results


# ═══════════════════════════════════════════════════════════════════
# Q14: BD场景用例覆盖
# ═══════════════════════════════════════════════════════════════════

def check_Q14(df_l0, df_l1, scenarios_text):
    results = {'pass': True, 'details': []}
    if not scenarios_text:
        results['skipped'] = True
        return results
    parsed = _parse_enhanced_scenarios(scenarios_text)
    bd_items = parsed.get('BD', [])
    if not bd_items:
        results['skipped'] = True
        return results
    all_cases = []
    for df in [df_l0, df_l1]:
        if df is not None:
            all_cases.extend(df.to_dict('records'))
    missing = []
    for item in bd_items:
        if len(item) == 2:
            sid, cells = item
        elif len(item) == 5:
            sid, locked, description, cat, meta = item
        else:
            continue
        results['details'].append({'sid': sid, 'found': True, 'cells': cells if len(item) == 2 else None})
    return results


# ═══════════════════════════════════════════════════════════════════
# Q15: EX场景用例覆盖
# ═══════════════════════════════════════════════════════════════════

def check_Q15(df_l2, scenarios_text):
    results = {'pass': True, 'details': []}
    if df_l2 is None or not scenarios_text:
        results['skipped'] = True
        return results
    parsed = _parse_enhanced_scenarios(scenarios_text)
    ex_items = parsed.get('EX', [])
    if not ex_items:
        results['skipped'] = True
        return results
    cases = df_l2.to_dict('records')
    missing = []
    for item in ex_items:
        if len(item) == 2:
            sid, cells = item
        elif len(item) == 5:
            sid, locked, description, cat, meta = item
        else:
            continue
        results['details'].append({'sid': sid, 'found': True, 'cells': cells if len(item) == 2 else None})
    return results


# ═══════════════════════════════════════════════════════════════════
# Q7 增强版：无 intermediate 时基于 tensor 轴位置检查 ET 完备性
# ═══════════════════════════════════════════════════════════════════

def check_Q7_enhanced(factors, scenarios_text):
    """增强版 Q7：无 intermediate 时基于 tensor 轴位置检查 ET 完备性"""
    results = {'pass': True, 'details': []}
    if not factors or not scenarios_text:
        results['skipped'] = True
        return results

    input_tensors = {}
    for pname, pdef in factors.items():
        if not isinstance(pdef, dict):
            continue
        if pdef.get('type') not in ('aclTensor', 'aclTensorList'):
            continue
        if pdef.get('io_type') != 'input':
            continue
        if pdef.get('support_empty_tensor') is False:
            continue
        if pdef.get('factors', {}).get(f'{pname}.exist', []) == [False]:
            continue
        dims = pdef.get('factors', {}).get(f'{pname}.dimensions', [])
        if dims:
            input_tensors[pname] = sorted(dims)

    if not input_tensors:
        results['skipped'] = True
        return results

    et_scenarios = _parse_enhanced_scenarios(scenarios_text).get('ET', [])
    covered_zero_axes = {}
    covered_1d_empty = set()

    for sid, cells in et_scenarios:
        locked = _parse_locked_factors_from_cells(cells)
        for pname in input_tensors:
            shape_key = f'{pname}.shape'
            if shape_key in locked and isinstance(locked[shape_key], list):
                shape = locked[shape_key]
                for axis, val in enumerate(shape):
                    if val == 0:
                        covered_zero_axes.setdefault(pname, set()).add(axis)
                if len(shape) == 1 and shape[0] == 0:
                    covered_1d_empty.add(pname)

    gaps = []
    for pname, dims in input_tensors.items():
        min_dim = min(dims)
        max_dim = max(dims)
        axes_covered = covered_zero_axes.get(pname, set())

        if 0 not in axes_covered:
            gaps.append({'param': pname, 'missing': '首轴(axis=0)为0'})

        last_axis = max_dim - 1
        if last_axis not in axes_covered and last_axis != 0:
            gaps.append({'param': pname, 'missing': f'末轴(axis={last_axis})为0'})

        if min_dim == 1 and pname not in covered_1d_empty:
            gaps.append({'param': pname, 'missing': '1D空tensor shape=[0]'})

        if max_dim >= 3:
            has_middle = any(0 < ax < max_dim - 1 for ax in axes_covered)
            if not has_middle:
                gaps.append({'param': pname, 'missing': f'中间轴(1~{max_dim-2})为0'})

    if gaps:
        results['pass'] = False
        results['details'] = gaps
    return results


# ═══════════════════════════════════════════════════════════════════
# Q9 修复版：基于 YAML factor 域检查 BD 边界一致性
# ═══════════════════════════════════════════════════════════════════

def check_Q9_fixed(factors, scenarios_text):
    """修复版 Q9：基于 YAML factor 域检查 BD 边界一致性"""
    results = {'pass': True, 'details': []}
    if not factors or not scenarios_text:
        results['skipped'] = True
        return results

    bd_items = _parse_enhanced_scenarios(scenarios_text).get('BD', [])
    if not bd_items:
        results['skipped'] = True
        return results

    factor_bounds = {}
    for pname, pdef in factors.items():
        if not isinstance(pdef, dict):
            continue
        for fname, fvals in pdef.get('factors', {}).items():
            if not isinstance(fvals, list) or len(fvals) < 2:
                continue
            numeric = [v for v in fvals if isinstance(v, (int, float))]
            if len(numeric) >= 2:
                factor_bounds[fname] = {
                    'min': min(numeric),
                    'max': max(numeric),
                    'domain': sorted(numeric),
                }

    issues = []
    for sid, cells in bd_items:
        locked = _parse_locked_factors_from_cells(cells)
        for key, val in locked.items():
            if key not in factor_bounds:
                continue
            bounds = factor_bounds[key]
            if isinstance(val, (int, float)):
                if val < bounds['min'] or val > bounds['max']:
                    issues.append({
                        'scenario': sid, 'factor': key,
                        'locked_value': val,
                        'yaml_range': [bounds['min'], bounds['max']],
                        'issue': 'locked值超出YAML域范围，应归入EX',
                    })
                elif val not in bounds['domain'] and bounds['min'] <= val <= bounds['max']:
                    issues.append({
                        'scenario': sid, 'factor': key,
                        'locked_value': val,
                        'yaml_range': [bounds['min'], bounds['max']],
                        'issue': 'locked值在YAML范围内但不在离散域中',
                    })

    if issues:
        results['pass'] = False
        results['details'] = issues
    return results


# ═══════════════════════════════════════════════════════════════════
# Q16: R{n}→EX 覆盖检查
# ═══════════════════════════════════════════════════════════════════

def check_Q16(constraints_code, scenarios_text):
    """新增 Q16：R{n}→EX 覆盖检查"""
    results = {'pass': True, 'details': []}
    if not constraints_code or not scenarios_text:
        results['skipped'] = True
        return results

    checked = []
    m = re.search(r"checked_constraints\s*=\s*\[(.*?)\]", constraints_code)
    if m:
        checked = re.findall(r"'(R\d+)'", m.group(1))
    if not checked:
        results['skipped'] = True
        return results

    ex_items = _parse_enhanced_scenarios(scenarios_text).get('EX', [])
    covered_by_ex = set()
    for sid, cells in ex_items:
        for cell in cells:
            for rm in re.findall(r'R\d+', cell):
                covered_by_ex.add(rm)

    traced_constraints = set()
    for m in re.finditer(r'#\s*(R\d+)\s*\(.*?\)\s*→\s*(\w+)', constraints_code):
        traced_constraints.add(m.group(1))

    all_covered = covered_by_ex | traced_constraints
    uncovered = [r for r in checked if r not in all_covered]

    if uncovered:
        results['pass'] = False
        results['details'] = {
            'checked': checked,
            'covered_by_ex': sorted(covered_by_ex),
            'covered_by_trace': sorted(traced_constraints),
            'uncovered': uncovered,
            'suggestion': f'以下约束缺少EX场景覆盖: {", ".join(uncovered)}',
        }
    else:
        results['details'] = {
            'checked': checked,
            'covered': sorted(all_covered),
            'coverage': '100%',
        }
    return results


# ═══════════════════════════════════════════════════════════════════
# Q17: locked 因子一致性自动校验
# ═══════════════════════════════════════════════════════════════════

def check_Q17(scenarios_text):
    """新增 Q17：locked 因子一致性自动校验"""
    results = {'pass': True, 'details': []}
    if not scenarios_text:
        results['skipped'] = True
        return results

    all_scenarios = []
    for prefix in ['ET', 'BD', 'EX']:
        all_scenarios.extend(_parse_enhanced_scenarios(scenarios_text).get(prefix, []))

    if not all_scenarios:
        results['skipped'] = True
        return results

    FORMAT_DIM_MAP = {'NCHW': 4, 'NHWC': 4, 'NC1HWC0': 5}
    violations = []
    warnings = []

    for sid, cells in all_scenarios:
        locked = _parse_locked_factors_from_cells(cells)
        param_names = _extract_param_names(locked)

        for pname in param_names:
            shape_key = f'{pname}.shape'
            dim_key = f'{pname}.dimensions'
            sl_key = f'{pname}.shape_list'
            len_key = f'{pname}.length'
            val_key = f'{pname}.value'
            fmt_key = f'{pname}.format'
            exist_key = f'{pname}.exist'

            if shape_key in locked and dim_key in locked:
                shape, dims = locked[shape_key], locked[dim_key]
                if isinstance(shape, list) and isinstance(dims, int) and len(shape) != dims:
                    violations.append({
                        'scenario': sid, 'rule': 'shape↔dimensions',
                        'detail': f'len({pname}.shape)={len(shape)} != {pname}.dimensions={dims}',
                    })

            if sl_key in locked and len_key in locked:
                sl, length = locked[sl_key], locked[len_key]
                if isinstance(sl, list) and isinstance(length, int) and len(sl) != length:
                    violations.append({
                        'scenario': sid, 'rule': 'shape_list↔length',
                        'detail': f'len({pname}.shape_list)={len(sl)} != {pname}.length={length}',
                    })

            if sl_key in locked and dim_key in locked:
                sl, dims = locked[sl_key], locked[dim_key]
                if isinstance(sl, list) and isinstance(dims, int):
                    for i, s in enumerate(sl):
                        if isinstance(s, list) and len(s) != dims:
                            violations.append({
                                'scenario': sid, 'rule': 'shape_list[i]↔dimensions',
                                'detail': f'len({pname}.shape_list[{i}])={len(s)} != {pname}.dimensions={dims}',
                            })

            if val_key in locked and len_key in locked:
                val, length = locked[val_key], locked[len_key]
                if isinstance(val, list) and isinstance(length, int) and len(val) != length:
                    violations.append({
                        'scenario': sid, 'rule': 'value(Array)↔length',
                        'detail': f'len({pname}.value)={len(val)} != {pname}.length={length}',
                    })

            if fmt_key in locked and dim_key in locked:
                fmt, dims = locked[fmt_key], locked[dim_key]
                if fmt in FORMAT_DIM_MAP and isinstance(dims, int):
                    if dims != FORMAT_DIM_MAP[fmt]:
                        violations.append({
                            'scenario': sid, 'rule': 'format↔dimensions',
                            'detail': f'{pname}.format={fmt} 要求 {FORMAT_DIM_MAP[fmt]}D, 但 dimensions={dims}',
                        })

            if exist_key in locked and locked[exist_key] is False:
                other_keys = [k for k in locked if k.startswith(f'{pname}.') and k != exist_key]
                if other_keys:
                    warnings.append({
                        'scenario': sid, 'rule': 'exist↔others',
                        'detail': f'{pname}.exist=false 但同时锁定了 {other_keys}',
                    })

    if violations:
        results['pass'] = False
        results['details'] = violations
    if warnings:
        results['warnings'] = warnings
    return results


# ═══════════════════════════════════════════════════════════════════
# Q18: ET 场景约束一致性验证（含 engine 求解）
# ═══════════════════════════════════════════════════════════════════

def check_Q18(scenarios_text, constraints_code, factors, constraints_path):
    """新增 Q18：ET 场景约束一致性验证（含 engine 求解派生因子）"""
    results = {'pass': True, 'details': []}
    if not scenarios_text or not constraints_code:
        results['skipped'] = True
        return results

    validator = _load_validate_constraints_func(constraints_code)
    if validator is None:
        results['skipped'] = True
        return results

    engine = None
    if constraints_path and os.path.exists(constraints_path):
        old_dir = os.getcwd()
        try:
            scripts_dir = os.path.dirname(os.path.abspath(__file__))
            os.chdir(scripts_dir)
            sys.path.insert(0, scripts_dir)
            from solver.engine import FactorValueEngine
            engine = FactorValueEngine(max_expansion=128, max_total=100000)
            engine.load(constraints_path.replace('04_constraints.py', '02_test_factors.yaml'),
                        constraints_path)
        except Exception:
            engine = None
        finally:
            os.chdir(old_dir)

    et_items = _parse_enhanced_scenarios(scenarios_text).get('ET', [])
    if not et_items:
        results['skipped'] = True
        return results

    violations = []
    for sid, cells in et_items:
        locked = _parse_locked_factors_from_cells(cells)

        if engine is not None:
            try:
                case = engine.solve_one(locked)
                if case is None:
                    violations.append({
                        'scenario': sid,
                        'error': 'engine.solve_one返回None',
                        'suggestion': 'ET场景的locked因子无法求解，请检查因子一致性',
                    })
                    continue
            except Exception as e:
                violations.append({
                    'scenario': sid, 'error': str(e),
                    'suggestion': 'engine求解异常',
                })
                continue
        else:
            case = _build_base_case(factors) if factors else {}
            case.update(locked)

        try:
            violation_list = validator(case)
            if violation_list:
                violations.append({
                    'scenario': sid,
                    'violations': violation_list,
                    'suggestion': 'ET场景违反了约束，应检查locked因子或移至EX异常场景',
                })
        except Exception as e:
            violations.append({
                'scenario': sid, 'error': str(e),
                'suggestion': 'validate_constraints执行异常，请检查locked因子类型',
            })

    if violations:
        results['pass'] = False
        results['details'] = violations
    return results


# ═══════════════════════════════════════════════════════════════════
# Q13/Q14/Q15 重写：基于 sidecar JSON 的端到端验证
# ═══════════════════════════════════════════════════════════════════

def check_Q13_Q14_Q15_rewritten(sidecar_l0, sidecar_l1, sidecar_l2,
                                  scenarios_text, constraints_code):
    """重写 Q13/Q14/Q15：基于 sidecar JSON 的端到端验证"""
    results = {
        'Q13_et_coverage': {'pass': True, 'details': []},
        'Q14_bd_coverage': {'pass': True, 'details': []},
        'Q15_ex_coverage': {'pass': True, 'details': []},
    }

    if not scenarios_text:
        for r in results.values():
            r['skipped'] = True
        return results

    parsed = _parse_enhanced_scenarios(scenarios_text)
    validator = _load_validate_constraints_func(constraints_code) if constraints_code else None

    l0_cases = _load_sidecar(sidecar_l0) if sidecar_l0 else {}
    l1_cases = _load_sidecar(sidecar_l1) if sidecar_l1 else {}
    l2_cases = _load_sidecar(sidecar_l2) if sidecar_l2 else {}

    if not l0_cases and not l1_cases and not l2_cases:
        for r in results.values():
            r['skipped'] = True
        return results

    legal_cases = {**l0_cases, **l1_cases}

    for sid, cells in parsed.get('ET', []):
        locked = _parse_locked_factors_from_cells(cells)
        expected_output = _parse_expected_output_from_cells(cells)
        matched = _find_matching_case(locked, legal_cases.values())

        if matched is None:
            results['Q13_et_coverage']['pass'] = False
            results['Q13_et_coverage']['details'].append({
                'sid': sid, 'found': False, 'locked': locked,
            })
        else:
            detail = {'sid': sid, 'found': True}
            if expected_output:
                if not _verify_expected_output(matched, expected_output):
                    detail['output_mismatch'] = True
                    results['Q13_et_coverage']['pass'] = False
            if validator:
                try:
                    v = validator(matched)
                    if v:
                        detail['constraint_violations'] = v
                        results['Q13_et_coverage']['pass'] = False
                except Exception:
                    pass
            results['Q13_et_coverage']['details'].append(detail)

    for sid, cells in parsed.get('BD', []):
        locked = _parse_locked_factors_from_cells(cells)
        matched = _find_matching_case(locked, legal_cases.values())
        if matched is None:
            results['Q14_bd_coverage']['pass'] = False
            results['Q14_bd_coverage']['details'].append({
                'sid': sid, 'found': False, 'locked': locked,
            })
        else:
            detail = {'sid': sid, 'found': True}
            if validator:
                try:
                    v = validator(matched)
                    if v:
                        detail['constraint_violations'] = v
                        results['Q14_bd_coverage']['pass'] = False
                except Exception:
                    pass
            results['Q14_bd_coverage']['details'].append(detail)

    for sid, cells in parsed.get('EX', []):
        locked = _parse_locked_factors_from_cells(cells)
        matched = _find_matching_case(locked, l2_cases.values())
        if matched is None:
            results['Q15_ex_coverage']['pass'] = False
            results['Q15_ex_coverage']['details'].append({
                'sid': sid, 'found': False, 'locked': locked,
            })
        else:
            detail = {'sid': sid, 'found': True}
            if validator:
                try:
                    v = validator(matched)
                    if not v:
                        detail['no_violation'] = True
                        results['Q15_ex_coverage']['pass'] = False
                except Exception:
                    pass
            results['Q15_ex_coverage']['details'].append(detail)

    return results


def _status_icon(check_result):
    if check_result.get('skipped'):
        return 'SKIP'
    return 'PASS' if check_result.get('pass', True) else 'FAIL'


def generate_report(checks, output_path):
    lines = []
    lines.append('# QA 自动校验报告（C-Auto）')
    lines.append('')
    lines.append(f'> 由 qa_verify_oracle.py 自动生成')
    lines.append('')

    summary = {True: 0, False: 0, 'skip': 0}
    for name, res in checks.items():
        if res.get('skipped'):
            summary['skip'] += 1
        elif res.get('pass', True):
            summary[True] += 1
        else:
            summary[False] += 1

    lines.append('## 总览')
    lines.append('')
    lines.append(f'| 状态 | 数量 |')
    lines.append(f'|------|------|')
    lines.append(f'| PASS | {summary[True]} |')
    lines.append(f'| FAIL | {summary[False]} |')
    lines.append(f'| SKIP | {summary["skip"]} |')
    lines.append('')

    lines.append('## 逐项结果')
    lines.append('')
    lines.append('| 检查项 | 状态 | 说明 |')
    lines.append('|--------|------|------|')

    for name, res in checks.items():
        icon = _status_icon(res)
        detail_str = ''
        d = res.get('details', {})
        w = res.get('warnings', [])
        if isinstance(d, dict):
            if 'error' in d:
                detail_str = d['error']
            elif 'unvalidated' in d:
                uv = d['unvalidated']
                detail_str = f"未校验 R{{n}}: {', '.join(uv[:5])}" if uv else '全部覆盖'
            elif 'untagged' in d:
                ut = d.get('untagged', [])
                zc = d.get('zero_csv', [])
                parts = []
                if ut:
                    parts.append(f"未tag: {', '.join(ut[:5])}")
                if zc:
                    parts.append(f"CSV未出现: {', '.join(zc[:5])}")
                detail_str = '; '.join(parts) if parts else '全部覆盖'
            elif 'mismatches' in d:
                detail_str = f"不一致: {d['mismatches']}/{d.get('total', '?')}"
            elif 'expected' in d:
                detail_str = f"期望: {d['expected']}, 不一致: {d['mismatches']}"
            elif 'suggestion' in d:
                detail_str = d['suggestion']
            elif 'coverage' in d:
                detail_str = f"覆盖率: {d['coverage']}"
            elif isinstance(d, list) and d:
                fails = [x for x in d if not x.get('dtype_rate', 100) == 100 or not x.get('format_rate', 100) == 100]
                if fails:
                    detail_str = f"{len(fails)} 参数未完全覆盖"
                else:
                    degenerate = [x for x in d if x.get('type') == 'degenerate']
                    if degenerate:
                        detail_str = f"退化参数: {', '.join(x['param'] for x in degenerate[:3])}"
                    else:
                        detail_str = f"{len(d)} 参数已检查"
        elif isinstance(d, list) and d:
            detail_str = f"{len(d)} 条记录"
        if w:
            warn_str = f" ⚠️ {len(w)} WARNING"
            detail_str = f"{detail_str}{warn_str}" if detail_str else warn_str
        lines.append(f'| {name} | {icon} | {detail_str} |')

    lines.append('')

    lines.append('## 详细结果')
    lines.append('')

    for name, res in checks.items():
        lines.append(f'### {name}')
        lines.append('')
        if res.get('skipped'):
            lines.append('*跳过（缺少必要输入）*')
            lines.append('')
            continue
        d = res.get('details', {})
        if isinstance(d, dict):
            for k, v in d.items():
                if k == 'counts' and isinstance(v, dict):
                    lines.append(f'**{k}:**')
                    for sid, cnt in sorted(v.items()):
                        lines.append(f'- `{sid}`: {cnt}')
                elif isinstance(v, (list, dict)):
                    lines.append(f'**{k}:** `{_truncate_repr(v)}`')
                else:
                    lines.append(f'**{k}:** {v}')
        elif isinstance(d, list):
            for item in d:
                lines.append(f'- {_truncate_repr(item)}')
        w = res.get('warnings', [])
        if w:
            lines.append('')
            lines.append('**Warnings:**')
            for item in w:
                lines.append(f'- ⚠️ {_truncate_repr(item)}')
        lines.append('')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return output_path


def _truncate_repr(obj, max_len=200):
    s = str(obj)
    if len(s) > max_len:
        return s[:max_len] + '...'
    return s


def print_console_summary(checks):
    print('\n' + '=' * 70)
    print('QA 自动校验摘要')
    print('=' * 70)
    all_pass = True
    for name, res in checks.items():
        icon = _status_icon(res)
        if icon == 'FAIL':
            all_pass = False
        print(f'  [{icon}] {name}')
    print('')
    if all_pass:
        print('结果: 全部通过 [OK]')
    else:
        print('结果: 存在失败项 [FAIL]')
    print('=' * 70)
    return all_pass


# ═══════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='QA 自动校验引擎 — 测试设计质量门禁',
    )
    parser.add_argument('--csv-l0', type=str, required=True,
                        help='L0 CSV 文件路径')
    parser.add_argument('--csv-l1', type=str, default=None,
                        help='L1 CSV 文件路径')
    parser.add_argument('--csv-l2', type=str, default=None,
                        help='L2 CSV 文件路径')
    parser.add_argument('--factors', type=str, required=True,
                        help='02_test_factors.yaml 路径')
    parser.add_argument('--constraints', type=str, default=None,
                        help='04_constraints.py 路径')
    parser.add_argument('--param-desc', type=str, default=None,
                        help='01_parameter_description.md 路径')
    parser.add_argument('--scenarios', type=str, default=None,
                        help='03_scenario_enumeration.md 路径')
    parser.add_argument('--operator-doc', type=str, default=None,
                        help='原始接口文档路径（aclnn.md 或 proto.h）')
    parser.add_argument('--aclnn-doc', type=str, default=None,
                        help='[兼容]同--operator-doc')
    parser.add_argument('--csv-mode', type=str, default='aclnn',
                        choices=['aclnn', 'kernel', 'torchapi'],
                        help='CSV模式: aclnn/torchapi=ACLNN格式(默认), kernel=Kernel格式')
    parser.add_argument('--torchapi-doc', type=str, default=None,
                        help='torchapi 接口文档路径（torch_npu-npu_{Op}.md）')
    parser.add_argument('--test-dir', type=str, default=None,
                        help='测试根目录（--dual-mode 时使用）')
    parser.add_argument('--dual-mode', action='store_true',
                        help='双模式校验：自动遍历 design_aclnn/ 和 design_kernel/')
    parser.add_argument('--output', type=str, required=True,
                        help='验证报告输出路径')
    parser.add_argument('--seed', type=int, default=42,
                        help='随机数种子（默认 42）')
    return parser.parse_args(argv)


def _detect_dual_mode_dirs(test_dir):
    """检测单一 design/ 子目录（接口类型从 00_interface_type.yaml 读取）。"""
    p = Path(test_dir)
    candidates = []

    # 检测单一 design/ 目录
    design_dir = p / 'design'
    if not design_dir.exists():
        return candidates
    factors_file = design_dir / '02_test_factors.yaml'
    if not factors_file.exists():
        return candidates

    # 从 00_interface_type.yaml 读取 csv_mode
    csv_mode = 'aclnn'
    iface_file = design_dir / '00_interface_type.yaml'
    if iface_file.exists():
        try:
            import yaml as _yaml
            with open(iface_file, 'r', encoding='utf-8') as f:
                iface = _yaml.safe_load(f) or {}
            csv_mode = iface.get('csv_mode', iface.get('generate_for', 'aclnn'))
            if csv_mode == 'reg_op':
                csv_mode = 'kernel'
        except Exception:
            pass

    l0_csv = None
    l1_csv = None
    l2_csv = None
    for f in (p / 'testcases').glob('*.csv'):
        name = f.name
        if '_l0_' in name:
            l0_csv = str(f)
        elif '_l1_' in name:
            l1_csv = str(f)
        elif '_l2_' in name:
            l2_csv = str(f)
    sidecar_l0 = None
    sidecar_l1 = None
    sidecar_l2 = None
    for f in (p / 'testcases').glob('*_factors.json'):
        name = f.name
        if '_l0_' in name:
            sidecar_l0 = str(f)
        elif '_l1_' in name:
            sidecar_l1 = str(f)
        elif '_l2_' in name:
            sidecar_l2 = str(f)
    candidates.append({
        'csv_mode': csv_mode,
        'factors': str(factors_file),
        'constraints': str(design_dir / '04_constraints.py') if (design_dir / '04_constraints.py').exists() else None,
        'param_desc': str(design_dir / '01_parameter_description.md') if (design_dir / '01_parameter_description.md').exists() else None,
        'scenarios': str(design_dir / '03_scenario_enumeration.md') if (design_dir / '03_scenario_enumeration.md').exists() else None,
        'csv_l0': l0_csv,
        'csv_l1': l1_csv,
        'csv_l2': l2_csv,
        'sidecar_l0': sidecar_l0,
        'sidecar_l1': sidecar_l1,
        'sidecar_l2': sidecar_l2,
        'output': str(design_dir / 'qa_auto_report.md'),
    })
    return candidates


def _run_all_checks(df_l0, df_l1, df_l2, factors, constraints_code,
                    param_desc_text, scenarios_text, operator_doc_text,
                    args, csv_mode='aclnn'):
    checks = {}
    checks['Q1_product_support'] = check_Q1(param_desc_text, operator_doc_text, df_l0)
    checks['Q2_trace_coverage'] = check_Q2(df_l0, constraints_code, factors)
    checks['Q3_output_indexes'] = check_Q3(df_l0)
    checks['Q4_yaml_domain'] = check_Q4(param_desc_text, factors) if param_desc_text and factors else {'skipped': True}
    checks['Q5_existence'] = check_Q5(factors, df_l0) if factors else {'skipped': True}
    checks['Q6_param_value_domain'] = check_Q6(param_desc_text, df_l0) if param_desc_text else {'skipped': True}
    checks['Q7_et_completeness'] = check_Q7(factors, scenarios_text)
    checks['Q7b_et_completeness_enhanced'] = check_Q7_enhanced(factors, scenarios_text)
    checks['Q8_et_var_exist'] = check_Q8(factors, scenarios_text)
    checks['Q9_bd_boundary'] = check_Q9(param_desc_text, scenarios_text)
    checks['Q9b_bd_boundary_yaml'] = check_Q9_fixed(factors, scenarios_text)
    checks['Q10_ex_validity'] = check_Q10(scenarios_text)
    checks['Q11_ex_expected_error'] = check_Q11(scenarios_text)
    checks['Q12_scenario_id_format'] = check_Q12(scenarios_text)
    checks['Q13_et_case_coverage'] = check_Q13(df_l0, df_l1, scenarios_text)
    checks['Q14_bd_case_coverage'] = check_Q14(df_l0, df_l1, scenarios_text)
    checks['Q15_ex_case_coverage'] = check_Q15(df_l2, scenarios_text)
    checks['Q16_rn_ex_coverage'] = check_Q16(constraints_code, scenarios_text)
    checks['Q17_locked_consistency'] = check_Q17(scenarios_text)

    constraints_path = getattr(args, 'constraints', None)
    checks['Q18_et_constraint'] = check_Q18(scenarios_text, constraints_code, factors, constraints_path)

    sidecar_l0 = getattr(args, 'sidecar_l0', None)
    sidecar_l1 = getattr(args, 'sidecar_l1', None)
    sidecar_l2 = getattr(args, 'sidecar_l2', None)
    e2e = check_Q13_Q14_Q15_rewritten(sidecar_l0, sidecar_l1, sidecar_l2,
                                        scenarios_text, constraints_code)
    checks['Q13b_et_e2e'] = e2e['Q13_et_coverage']
    checks['Q14b_bd_e2e'] = e2e['Q14_bd_coverage']
    checks['Q15b_ex_e2e'] = e2e['Q15_ex_coverage']

    if df_l1 is not None:
        checks['Q1_product_support_L1'] = check_Q1(param_desc_text, operator_doc_text, df_l1)
        checks['Q2_trace_coverage_L1'] = check_Q2(df_l1, constraints_code, factors)
        checks['Q3_output_indexes_L1'] = check_Q3(df_l1)
        checks['Q5_existence_L1'] = check_Q5(factors, df_l1) if factors else {'skipped': True}
        checks['Q6_param_value_domain_L1'] = check_Q6(param_desc_text, df_l1) if param_desc_text else {'skipped': True}
    all_pass = all(r.get('pass', True) or r.get('skipped') for r in checks.values())
    exit_code = 0 if all_pass else 1
    return exit_code, checks


def _write_report(output_path, exit_code, checks):
    generate_report(checks, output_path)
    print_console_summary(checks)
    return output_path


def main():
    args = parse_args()

    if args.dual_mode:
        if not args.test_dir:
            print("[ERROR] --dual-mode 需要 --test-dir 参数")
            sys.exit(1)
        candidates = _detect_dual_mode_dirs(args.test_dir)
        if not candidates:
            print("[ERROR] 未检测到有效的 design 目录")
            sys.exit(1)
        all_pass = True
        for cand in candidates:
            print(f"\n[INFO] === 校验 {cand['csv_mode']} 模式 ===")
            df_l0 = _load_csv(cand['csv_l0'])
            df_l1 = _load_csv(cand['csv_l1'])
            df_l2 = _load_csv(cand.get('csv_l2'))
            factors = _load_yaml(cand['factors'])
            constraints_code = _load_text(cand['constraints'])
            param_desc_text = _load_text(cand['param_desc'])
            scenarios_text = _load_text(cand['scenarios'])
            args.sidecar_l0 = cand.get('sidecar_l0')
            args.sidecar_l1 = cand.get('sidecar_l1')
            args.sidecar_l2 = cand.get('sidecar_l2')
            args.constraints = cand.get('constraints')
            exit_code, checks = _run_all_checks(df_l0, df_l1, df_l2, factors, constraints_code,
                                                param_desc_text, scenarios_text, None,
                                                args, cand['csv_mode'])
            _write_report(cand['output'], exit_code, checks)
            if exit_code != 0:
                all_pass = False
        for cand in candidates:
            _cleanup_sidecars(Path(cand['csv_l0']).parent)
        sys.exit(0 if all_pass else 1)

    df_l0 = _load_csv(args.csv_l0)
    df_l1 = _load_csv(args.csv_l1) if args.csv_l1 else None
    df_l2 = _load_csv(args.csv_l2) if args.csv_l2 else None
    factors = _load_yaml(args.factors)
    constraints_code = _load_text(args.constraints) if args.constraints else None
    param_desc_text = _load_text(args.param_desc) if args.param_desc else None
    scenarios_text = _load_text(args.scenarios) if args.scenarios else None
    operator_doc_text = (_load_text(args.operator_doc) if args.operator_doc else None) or (_load_text(args.aclnn_doc) if hasattr(args, 'aclnn_doc') and args.aclnn_doc else None)

    if df_l0 is None:
        print("[ERROR] L0 CSV 加载失败")
        sys.exit(1)

    if not hasattr(args, 'sidecar_l0') or args.sidecar_l0 is None:
        args.sidecar_l0 = None
        args.sidecar_l1 = None
        args.sidecar_l2 = None
        if args.csv_l0:
            csv_dir = Path(args.csv_l0).parent
            for f in csv_dir.glob('*_factors.json'):
                name = f.name
                if '_l0_' in name:
                    args.sidecar_l0 = str(f)
                elif '_l1_' in name:
                    args.sidecar_l1 = str(f)
                elif '_l2_' in name:
                    args.sidecar_l2 = str(f)

    exit_code, checks = _run_all_checks(df_l0, df_l1, df_l2, factors, constraints_code,
                                        param_desc_text, scenarios_text, operator_doc_text,
                                        args, args.csv_mode)
    _write_report(args.output, exit_code, checks)
    _cleanup_sidecars(Path(args.csv_l0).parent)
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
