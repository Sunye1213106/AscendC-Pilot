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
测试用例生成脚本（直接生成架构）
支持 L0（单因子覆盖 ≤200）、L1（两两组合 500~700）、L2（异常用例 ≤50）
"""

import argparse
import sys
import os
import re
import inspect
import itertools
import math
import json
import numpy as np
from typing import Dict, Any
from dataclasses import dataclass
import yaml
import random
from pathlib import Path
from collections import defaultdict
import pandas as pd
from ast import literal_eval

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import (
    normalize_dtype,
    get_dtype_category,
    get_default_value_range,
    generate_random_shape,
    make_hashable,
    param_excludes_infnan,
)
from solver.engine import FactorValueEngine
from solver.constraint_graph import ConstraintGraph
import generate_kernelttk_cases

ARRAY_TYPES = ('aclIntArray', 'aclFloatArray', 'aclBoolArray', 'aclScalarList')
ENUM_SCALAR_TYPES = ('bool', 'aclDataType', 'string')

ALL_DTYPES = {
    'float32', 'float16', 'int8', 'int32', 'uint8', 'int16', 'uint16',
    'uint32', 'int64', 'uint64', 'float64', 'bool', 'string',
    'complex64', 'complex128', 'bfloat16', 'int4', 'uint1',
    'complex32', 'hifloat8', 'float8_e5m2', 'float8_e4m3fn',
    'float8_e8m0', 'float6_e3m2', 'float6_e2m3', 'float4_e2m1',
    'float4_e1m2', 'hifloat4', 'hifloat4_scale',
}

ALL_FORMATS = {'ND', 'NCHW', 'NHWC', 'NC1HWC0', 'FRACTAL_Z', 'FRACTAL_NZ'}

ACL_DTYPE_ENUM_MAP = {
    "float32": 0, "float16": 1, "int8": 2, "int32": 3, "uint8": 4,
    "int16": 5, "uint16": 6, "uint32": 7, "int64": 8, "uint64": 9,
    "float64": 10, "bool": 11, "string": 12, "complex64": 13,
    "complex128": 14, "bfloat16": 27, "int4": 29, "uint1": 30,
    "complex32": 32, "hifloat8": 33, "float8_e5m2": 35,
    "float8_e4m3fn": 36, "float8_e8m0": 37, "float6_e3m2": 38,
    "float6_e2m3": 39, "float4_e2m1": 40, "float4_e1m2": 41,
    "hifloat4": 42, "hifloat4_scale": 43, "quint4x2": 29,
}

CASE_KEYWORD_MAP = {
    'empty_tensor': '_empty_',
    'boundary': '_bound_',
    'exception': '_exc_',
    'unsupported_dtype': '_exc_dtype_',
    'unsupported_format': '_exc_format_',
    'dimension_overflow': '_exc_dimval_',
    'dim_boundary_underflow': '_exc_dimval_',
    'dim_boundary_overflow': '_exc_dimval_',
    'shape_boundary_exceed': '_exc_shape_',
    'enum_out_of_range': '_exc_enum_',
    'constraint_violation': '_exc_constraint_',
    'index_out_of_range': '_exc_index_',
    'dim_value_out_of_range': '_exc_dimval_',
    'value_duplicate_array': '_exc_dup_',
    'value_duplicate_tensor': '_exc_dup_',
    'io_dtype_mismatch': '_exc_dtype_',
    'dtype_mismatch': '_exc_dtype_',
    'output_shape_mismatch': '_exc_shape_',
    'array_duplicate_elements': '_exc_dup_',
    'array_length_mismatch': '_exc_len_',
    'dtype_format_incompatible': '_exc_format_',
    'required_param_missing': '_exc_missing_',
}


def _load_constraint_validators(constraints_path):
    """从 04_constraints.py 加载 validate_constraints 函数（可选）"""
    if not constraints_path or not os.path.exists(constraints_path):
        return None
    old_registry = None
    try:
        from solver.registry import (
            ConstraintRegistry,
            get_active_registry,
            set_active_registry,
        )
        from solver import solves as _solves, Candidates, SKIP, NOT_APPLICABLE
        from solver.tags import tag

        old_registry = get_active_registry()
        temp_registry = ConstraintRegistry()
        set_active_registry(temp_registry)

        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        solver_dir = os.path.join(scripts_dir, "solver")
        constraint_globals = {
            "solves": _solves,
            "Candidates": Candidates,
            "SKIP": SKIP,
            "NOT_APPLICABLE": NOT_APPLICABLE,
            "tag": tag,
            "__solver_dir__": solver_dir,
            "__builtins__": __builtins__,
        }
        with open(constraints_path, "r", encoding="utf-8") as f:
            code = f.read()
        exec(compile(code, constraints_path, "exec"), constraint_globals)

        if "validate_constraints" in constraint_globals:
            return constraint_globals["validate_constraints"]

        print("[WARN] 04_constraints.py 未定义 validate_constraints(case) 函数，"
              "第2层约束正确性自检将被跳过。请在 04_constraints.py 中添加此函数。"
              "详见 constraint-writing-guide.md §4.6", file=sys.stderr)
    except Exception:
        pass
    finally:
        if old_registry is not None:
            set_active_registry(old_registry)
    return None


def _extract_shape_constraints(constraints_path, param_def):
    """从 04_constraints.py 中提取 shape 约束关系，用于非连续 shape 推导。

    返回 dict: {(nc_idx, companion_idx): 'equal'|'broadcast_compatible'|'independent'}

    解析策略：
    1. 加载约束模块的 @solves 注册信息
    2. 找到 solve target 为 *.shape 或 *.shape_list 的 solves 函数
    3. 根据 solves 函数的 sources 和实现推断约束类型：
       - 返回 source_shape 原值 → 'equal'
       - 返回比 source 更大的 shape → 'broadcast_compatible'
       - 其他 → 'independent'
    """
    if not constraints_path or not os.path.exists(constraints_path):
        return None

    tensor_params = []
    skip_keys = {'operator_name', 'aclnn_name', 'parameters'}
    param_idx = 0
    for param_name, param_info in param_def.items():
        if param_name in skip_keys or not isinstance(param_info, dict):
            continue
        param_type = param_info.get('type', '')
        if param_type not in ('aclTensor', 'aclTensorList'):
            continue
        tensor_params.append({'name': param_name, 'idx': param_idx, 'type': param_type})
        param_idx += 1

    try:
        from solver.registry import ConstraintRegistry, get_active_registry, set_active_registry
        from solver import solves as _solves, Candidates, SKIP, NOT_APPLICABLE
        from solver.tags import tag

        old_registry = get_active_registry()
        temp_registry = ConstraintRegistry()
        set_active_registry(temp_registry)

        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        solver_dir = os.path.join(scripts_dir, "solver")
        constraint_globals = {
            "solves": _solves,
            "Candidates": Candidates,
            "SKIP": SKIP,
            "NOT_APPLICABLE": NOT_APPLICABLE,
            "tag": tag,
            "__solver_dir__": solver_dir,
            "__builtins__": __builtins__,
        }
        with open(constraints_path, "r", encoding="utf-8") as f:
            code = f.read()
        exec(compile(code, constraints_path, "exec"), constraint_globals)

        all_solves = temp_registry.get_all()
        set_active_registry(old_registry)

        shape_solves = {}
        for target, sol_entry in all_solves.items():
            sources = sol_entry.get('sources', [])
            func = sol_entry.get('function')
            if '.shape' in target or '.shape_list' in target:
                shape_solves[target] = {'sources': sources, 'func': func}

        def _classify_constraint(func, sources, test_shape=[2, 3, 4]):
            import random as _rng
            _rng.seed(42)
            mock_args = []
            for src in sources:
                src_field = src.split('.')[1] if '.' in src else ''
                if src.startswith('_'):
                    mock_args.append(0)
                elif src_field in ('shape_list', 'shape'):
                    mock_args.append([test_shape])
                elif src_field in ('length',):
                    mock_args.append(1)
                elif src_field in ('dimensions',):
                    mock_args.append(len(test_shape))
                else:
                    mock_args.append(test_shape)
            found_equal = False
            found_bc = False
            for scenario_val in [0, 1]:
                call_args = list(mock_args)
                for k, src in enumerate(sources):
                    if src.startswith('_scenario'):
                        call_args[k] = scenario_val
                try:
                    result = func(*call_args)
                except Exception:
                    continue
                if isinstance(result, list):
                    inner_results = result
                else:
                    inner_results = [result] if result is not None else []
                for r in inner_results:
                    if r == test_shape or r == list(test_shape) or r == tuple(test_shape):
                        found_equal = True
                    elif isinstance(r, (list, tuple)):
                        prod_in = 1
                        for d in test_shape:
                            prod_in *= d
                        prod_out = 1
                        for d in r:
                            prod_out *= d
                        if prod_out >= prod_in:
                            found_bc = True
            if found_bc:
                return 'broadcast_compatible'
            if found_equal:
                return 'equal'
            return 'independent'

        constraints = {}
        for target, sol_info in shape_solves.items():
            target_param = target.split('.')[0]
            target_idx = None
            for tp in tensor_params:
                if tp['name'] == target_param:
                    target_idx = tp['idx']
                    break
            if target_idx is None:
                continue

            tensor_src_indices = []
            for src in sol_info['sources']:
                src_param = src.split('.')[0]
                src_idx = None
                for tp in tensor_params:
                    if tp['name'] == src_param:
                        src_idx = tp['idx']
                        break
                if src_idx is not None:
                    tensor_src_indices.append(src_idx)

            func = sol_info.get('func')
            if func is not None:
                c_type = _classify_constraint(func, sol_info['sources'])
            else:
                c_type = 'independent'

            for src_idx in tensor_src_indices:
                constraints[(src_idx, target_idx)] = c_type

        return constraints
    except Exception:
        pass
    finally:
        try:
            if old_registry is not None:
                set_active_registry(old_registry)
        except Exception:
            pass
    return None


def _validate_cases_against_constraints(cases, validator, verbose=False):
    """用例级约束正确性校验——零容忍模式"""
    if validator is None:
        return cases

    valid_cases = []
    violation_stats = {}
    violation_examples = {}
    for case in cases:
        violations = validator(case)
        if not violations:
            valid_cases.append(case)
        else:
            for v in violations:
                violation_stats[v] = violation_stats.get(v, 0) + 1
                if v not in violation_examples:
                    violation_examples[v] = case

    total = len(cases)
    if total > 0 and violation_stats:
        total_violations = total - len(valid_cases)
        details = ', '.join(f'{k}:{v}' for k, v in sorted(violation_stats.items()))
        print(f"\n{'='*60}")
        print(f"[DIAGNOSIS] 约束校验违规诊断报告")
        print(f"{'='*60}")
        print(f"校验用例数: {total}, 违规用例数: {total_violations}")
        print()
        for v_id, count in sorted(violation_stats.items(), key=lambda x: -x[1]):
            print(f"  违规类型: {v_id}")
            print(f"  违规数量: {count}/{total} ({count/total:.1%})")
            if v_id in violation_examples:
                example = violation_examples[v_id]
                key_fields = {k: example[k] for k in sorted(example.keys())
                              if any(kw in k for kw in ['scenario', 'cacheMode', 'shape',
                                                          'num_head', 'head_size', 'dtype'])}
                if key_fields:
                    print(f"  样例用例关键字段:")
                    for k, val in key_fields.items():
                        print(f"    {k} = {val}")
            print()
        print(f"{'='*60}")
        print(f"\n[ERROR] 约束正确性校验: {total_violations}/{total} 条用例违规 ({details})")
        print(f"[ERROR] @solves 与 validate_constraints 描述同一份约束规格，正确实现下违规数应为 0。")
        print(f"[ERROR] 请根据上述诊断报告修复 @solves 实现后重新生成。")
        raise SystemExit(1)

    if not violation_stats and verbose:
        print(f"[INFO] 约束正确性校验通过: {len(cases)} 条用例全部合法")

    return valid_cases


@dataclass
class CoverageTarget:
    locked: Dict[str, Any]
    category: str
    label: str
    scenario_id: str = None


def _detect_dual_mode_design_dirs(test_factors_path):
    """检测单一 design/ 目录（接口类型从 00_interface_type.yaml 读取）。"""
    p = Path(test_factors_path)
    if p.is_file():
        p = p.parent
    candidates = []

    # 优先检测单一 design/ 目录
    design_dir = p / 'design' if p.name != 'design' else p
    tf = design_dir / '02_test_factors.yaml'
    if tf.exists():
        # 从 00_interface_type.yaml 读取 csv_mode
        iface_file = design_dir / '00_interface_type.yaml'
        csv_mode = 'aclnn'  # 默认
        if iface_file.exists():
            try:
                import yaml as _yaml
                with open(iface_file, 'r', encoding='utf-8') as f:
                    iface = _yaml.safe_load(f) or {}
                csv_mode = iface.get('csv_mode', iface.get('generate_for', 'aclnn'))
                # generate_for 的 reg_op → csv_mode kernel
                if csv_mode == 'reg_op':
                    csv_mode = 'kernel'
            except Exception:
                pass
        cs = design_dir / '04_constraints.py'
        sc = design_dir / '03_scenario_enumeration.md'
        candidates.append({
            'design_dir': design_dir,
            'test_factors': str(tf),
            'constraints': str(cs) if cs.exists() else None,
            'scenarios': str(sc) if sc.exists() else None,
            'csv_mode': csv_mode,
        })
    return candidates


def _run_single_mode(args, levels, test_factors_path, constraints_path,
                     scenarios_path, csv_mode, verbose):
    """以指定 csv_mode 运行单模式生成。"""
    engine = None
    if any(l in ('L0', 'L1') for l in levels):
        engine = FactorValueEngine(max_expansion=128, max_total=100000, seed=args.seed)
        engine.load(test_factors_path, constraints_path)
    elif 'L2' in levels:
        engine = FactorValueEngine(max_expansion=128, max_total=100000, seed=args.seed)
        if constraints_path and os.path.exists(constraints_path):
            engine.load(test_factors_path, constraints_path)
        else:
            engine.load(test_factors_path)

    factors = load_yaml(test_factors_path)
    param_def = _build_param_def_from_factors(factors)

    tmp_args = argparse.Namespace(**vars(args))
    tmp_args.test_factors = test_factors_path
    operator_name = extract_operator_name(tmp_args)

    constraint_validator = _load_constraint_validators(constraints_path)

    l0_raw = None
    l1_raw = None
    l1_seen = None

    for level in levels:
        if verbose:
            print(f"[INFO] {'='*10} 开始生成 {level} 用例 ({csv_mode} 模式) {'='*10}")

        if level == 'L0':
            l0_raw = generate_L0(engine, factors, param_def, args, verbose)
            cases = l0_raw
        elif level == 'L1':
            l1_raw, l1_seen = generate_L1(engine, factors, param_def, args)
            cases = l1_raw
        else:
            cases = generate_L2(engine, factors, param_def, args, verbose)

        _process_and_save_level(
            cases, level, engine, factors, param_def, operator_name, args,
            constraint_validator, l1_seen=l1_seen,
        )

        if verbose:
            print(f"[INFO] {'='*10} {level} 用例生成完成 ({csv_mode} 模式) {'='*10}\n")

    if l0_raw is not None and l1_raw is not None:
        promoted_l0 = _promote_l1_to_fill_l0(l0_raw, l1_raw, verbose=verbose)
        if len(promoted_l0) > len(l0_raw):
            _process_and_save_level(
                promoted_l0, 'L0', engine, factors, param_def, operator_name, args,
                constraint_validator,
            )
            if verbose:
                print(f"[INFO] L0 提升后重存完成 ({csv_mode} 模式): {len(promoted_l0)} 条")


def main():
    args = parse_arguments()
    levels = parse_levels(args.level)

    if args.dual_mode:
        candidates = _detect_dual_mode_design_dirs(args.test_factors)
        if not candidates:
            print("[ERROR] --dual-mode 未检测到 design_aclnn/ 或 design_kernel/ 目录")
            sys.exit(1)
        print(f"[INFO] --dual-mode 检测到 {len(candidates)} 个设计目录:")
        for cand in candidates:
            print(f"  - {cand['csv_mode']}: {cand['design_dir']}")
        for cand in candidates:
            mode_args = argparse.Namespace(**vars(args))
            mode_args.test_factors = cand['test_factors']
            mode_args.constraints = cand['constraints']
            mode_args.scenarios = cand['scenarios']
            mode_args.csv_mode = cand['csv_mode']
            _run_single_mode(mode_args, levels, cand['test_factors'],
                           cand['constraints'], cand['scenarios'],
                           cand['csv_mode'], args.verbose)
        return

    _run_single_mode(args, levels, args.test_factors, args.constraints,
                     args.scenarios, args.csv_mode, args.verbose)
def _process_and_save_level(cases, level, engine, factors, param_def, operator_name,
                            args, constraint_validator, l1_seen=None):
    if level in ('L0', 'L1') and constraint_validator is not None:
        cases = _validate_cases_against_constraints(cases, constraint_validator, args.verbose)

    if args.csv_mode == 'kernel':
        _process_and_save_level_kernel(
            cases, level, engine, factors, param_def, operator_name,
            args, l1_seen=l1_seen
        )
    else:
        _process_and_save_level_aclnn(
            cases, level, engine, factors, param_def, operator_name,
            args, l1_seen=l1_seen
        )


def _process_and_save_level_aclnn(cases, level, engine, factors, param_def, operator_name,
                                   args, l1_seen=None):
    case_df = _convert_cases_to_ttk(cases, param_def, operator_name, level, args.csv_mode)

    if level != 'L2' and engine is not None:
        original_count = len(case_df)
        case_df = ttk_self_check_and_repair(
            case_df, engine, factors, param_def,
            operator_name, level, seed=args.seed, verbose=args.verbose,
            csv_mode=args.csv_mode,
        )
        if args.verbose and len(case_df) != original_count:
            print(f"[INFO] 用例自检修复完成，原始 {original_count} 条 → 最终 {len(case_df)} 条")

    if level != 'L2':
        dedup_cols = ['tensor_view_shapes', 'tensor_dtypes', 'tensor_formats', 'attributes']
        dedup_cols = [c for c in dedup_cols if c in case_df.columns]
        before_dedup = len(case_df)
        case_df = case_df.drop_duplicates(subset=dedup_cols, keep='first').reset_index(drop=True)
        if args.verbose and len(case_df) < before_dedup:
            print(f"[INFO] CSV级别去重：{before_dedup} 条 → {len(case_df)} 条（移除 {before_dedup - len(case_df)} 条值重复）")

        if level == 'L1' and engine is not None and len(case_df) < args.target_count:
            deficit = args.target_count - len(case_df)
            case_df = _replenish_l1(case_df, engine, factors, param_def,
                                    operator_name, level, deficit, args, dedup_cols,
                                    initial_seen=l1_seen,
                                    csv_mode=args.csv_mode)

    case_df['testcase_name'] = [
        _generate_testcase_name(operator_name, level, i, {
            '_category': row.get('_category', ''),
            '_exception_type': row.get('_exception_type', ''),
        })
        for i, (_, row) in enumerate(case_df.iterrows())
    ]
    for col in ['_category', '_exception_type', '_expected_error', '_scenario_id']:
        if col in case_df.columns:
            case_df = case_df.drop(columns=[col])

    save_output(case_df, args.output_dir, operator_name, level, args.verbose)
    _save_sidecar_factors(case_df, cases, args.output_dir, operator_name, level,
                          intermediate_factors=getattr(engine, 'intermediate_factors', None))

    if level == 'L1':
        from non_contiguous import has_nc_support, add_continuous_nc_columns, inject_non_contiguous_params, NC_ACLNN_COLUMNS
        from non_contiguous import _build_tensor_param_map, _parse_tensor_shapes, _is_tensorlist_shape
        if has_nc_support(param_def):
            case_df_nc = add_continuous_nc_columns(case_df, param_def)
            if not case_df.empty:
                shape_constraints = _extract_shape_constraints(args.constraints, param_def)
                nc_df = inject_non_contiguous_params(
                    case_df, param_def, operator_name, level,
                    shape_constraints=shape_constraints,
                    verbose=args.verbose,
                )
                if nc_df is not None:
                    merged = pd.concat([case_df_nc, nc_df], ignore_index=True)
                    nc_dedup_cols = [c for c in NC_ACLNN_COLUMNS if c in merged.columns]
                    before = len(merged)
                    merged = merged.drop_duplicates(subset=nc_dedup_cols, keep='first').reset_index(drop=True)
                    if args.verbose and len(merged) < before:
                        print(f"[INFO] L1+NC 去重：{before} 条 → {len(merged)} 条")
                    merged = merged[NC_ACLNN_COLUMNS]
                    save_output(merged, args.output_dir, operator_name, level, args.verbose)


def _save_sidecar_factors(case_df, cases, output_dir, operator_name, level,
                          intermediate_factors=None):
    """保存因子元数据 sidecar JSON（供 QA 校验使用）。

    保留声明的中间因子键（如 _batch.value/_dim.value/_scenario.value），
    供 QA 的 BD/EX 端到端校验匹配；仍丢弃内部元数据键
    （_category/_expected_error/_scenario_id/_tag__* 等）。
    """
    templates = {
        'L0': f'{operator_name}_l0_functional_factors.json',
        'L1': f'{operator_name}_l1_functional_factors.json',
        'L2': f'{operator_name}_l2_exception_factors.json',
    }
    filename = templates.get(level)
    if not filename:
        return
    intermediate_factors = intermediate_factors or set()
    path = Path(output_dir) / filename
    sidecar = {}
    for i, (_, row) in enumerate(case_df.iterrows()):
        tc_name = row.get('testcase_name', f'{operator_name}_{level}_{i+1:03d}')
        if i < len(cases):
            factor_dict = {
                k: v for k, v in cases[i].items()
                if not k.startswith('_') or k in intermediate_factors
            }
            sidecar[tc_name] = _make_json_serializable(factor_dict)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(sidecar, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _make_json_serializable(obj):
    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_serializable(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def _process_and_save_level_kernel(cases, level, engine, factors, param_def, operator_name,
                                   args, l1_seen=None):
    meta_rows = []
    for case in cases:
        meta_rows.append({
            '_category': case.get('_category', ''),
            '_exception_type': case.get('_exception_type', ''),
            '_expected_error': case.get('_expected_error', ''),
            '_scenario_id': case.get('_scenario_id', ''),
        })

    rows = [{k: v for k, v in case.items() if not k.startswith('_')} for case in cases]
    case_df = pd.DataFrame(rows, dtype=object)
    if not case_df.empty:
        case_df = generate_kernelttk_cases.convert_to_aclnn_kernel_format(
            case_df, param_def, operator_name, level
        )

    for i, meta in enumerate(meta_rows):
        if i < len(case_df):
            for k, v in meta.items():
                case_df.loc[i, k] = v

    if level == 'L2':
        param_names = [k for k in param_def.keys()
                       if k not in {'operator_name', 'aclnn_name', 'parameters'}]
        for i in range(len(case_df)):
            exc_type = case_df.loc[i, '_exception_type'] if '_exception_type' in case_df.columns else ''
            if exc_type:
                case_df.loc[i, 'remark'] = _build_remark(case_df.iloc[i], param_names)

    if level != 'L2' and engine is not None:
        original_count = len(case_df)
        case_df = generate_kernelttk_cases._aclnn_self_check_and_repair(
            case_df, engine, factors, param_def, operator_name, level,
            seed=args.seed, verbose=args.verbose
        )
        if args.verbose and len(case_df) != original_count:
            print(f"[INFO] 用例自检修复完成，原始 {original_count} 条 → 最终 {len(case_df)} 条")

    if level != 'L2':
        dedup_cols = ['input_shapes', 'input_dtypes', 'input_formats', 'attributes']
        dedup_cols = [c for c in dedup_cols if c in case_df.columns]
        before_dedup = len(case_df)
        case_df = case_df.drop_duplicates(subset=dedup_cols, keep='first').reset_index(drop=True)
        if args.verbose and len(case_df) < before_dedup:
            print(f"[INFO] CSV级别去重：{before_dedup} 条 → {len(case_df)} 条（移除 {before_dedup - len(case_df)} 条值重复）")

        if level == 'L1' and engine is not None and len(case_df) < args.target_count:
            deficit = args.target_count - len(case_df)
            case_df = _replenish_l1(case_df, engine, factors, param_def,
                                    operator_name, level, deficit, args, dedup_cols,
                                    initial_seen=l1_seen,
                                    csv_mode=args.csv_mode)

    case_df['testcase_name'] = [
        _generate_testcase_name(operator_name, level, i, {
            '_category': row.get('_category', ''),
            '_exception_type': row.get('_exception_type', ''),
        })
        for i, (_, row) in enumerate(case_df.iterrows())
    ]
    for col in ['_category', '_exception_type', '_expected_error', '_scenario_id']:
        if col in case_df.columns:
            case_df = case_df.drop(columns=[col])

    case_df = case_df[generate_kernelttk_cases.ACLNN_KERNEL_COLUMNS]
    save_output(case_df, args.output_dir, operator_name, level, args.verbose)
    _save_sidecar_factors(case_df, cases, args.output_dir, operator_name, level,
                          intermediate_factors=getattr(engine, 'intermediate_factors', None))


def parse_arguments():
    parser = argparse.ArgumentParser(description='测试用例生成脚本（直接生成，支持L0/L1/L2）')
    parser.add_argument('test_factors', help='测试因子YAML文件')
    parser.add_argument('output_dir', help='输出目录')
    parser.add_argument('--constraints', help='约束模块 04_constraints.py')
    parser.add_argument('--scenarios', help='场景枚举文件 03_scenario_enumeration.md')
    parser.add_argument('--level', nargs='+', required=True,
                        help='用例级别: L0 L1 L2')
    parser.add_argument('--csv-mode', choices=['aclnn', 'kernel', 'torchapi'], default='aclnn',
                        help='CSV输出模式: aclnn/torchapi=ACLNN格式(13列), kernel=Kernel格式(26列)')
    parser.add_argument('--dual-mode', action='store_true',
                        help='双模式：自动检测 design_aclnn/ 和 design_kernel/，依次生成两套用例')
    parser.add_argument('--operator-name', help='算子名称（自动从YAML提取时无需指定）')
    parser.add_argument('--aclnn-name', help='[兼容]同--operator-name')
    parser.add_argument('--target-count', type=int, default=500, help='L1目标数量(默认500)')
    parser.add_argument('--seed', type=int, help='随机数种子')
    parser.add_argument('--verbose', action='store_true')
    return parser.parse_args()


def parse_levels(level_arg):
    levels = []
    for item in level_arg:
        if ',' in item:
            levels.extend(l.strip() for l in item.split(','))
        else:
            levels.append(item.strip())
    levels = sorted(set(levels), key=lambda x: (0 if x == 'L0' else (1 if x == 'L1' else 2)))
    valid = {'L0', 'L1', 'L2'}
    invalid = set(levels) - valid
    if invalid:
        print(f"[ERROR] 无效级别: {invalid}")
        sys.exit(1)
    return levels


def load_yaml(path):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def extract_operator_name(args):
    if hasattr(args, 'operator_name') and args.operator_name:
        return args.operator_name
    if hasattr(args, 'aclnn_name') and args.aclnn_name:
        return args.aclnn_name
    data = load_yaml(args.test_factors)
    if data.get('operator_name'):
        return data['operator_name']
    # 向后兼容：旧 YAML 使用 aclnn_name
    if data.get('aclnn_name'):
        return data['aclnn_name']
    for part in Path(args.test_factors).parts:
        if part.startswith('aclnn'):
            return part
    return 'UnknownOperator'


def _build_param_def_from_factors(factors_data):
    operator_name = factors_data.get('operator_name', '') or factors_data.get('aclnn_name', '')
    result = {'operator_name': operator_name}
    params_list = []
    for param_name, param_info in factors_data.items():
        if not isinstance(param_info, dict) or 'factors' not in param_info:
            continue
        factors = param_info.get('factors', {})
        p = {
            'name': param_name,
            'type': param_info.get('type', ''),
            'io_type': param_info.get('io_type', 'input'),
            'in_place': param_info.get('in_place', False),
            'support_non_contiguous': param_info.get('support_non_contiguous', True),
        }
        dtype_values = factors.get(f"{param_name}.dtype", [])
        has_value = f"{param_name}.value" in factors
        if dtype_values and has_value:
            p['dtype_with_values'] = [{'dtype': d, 'value': factors.get(f"{param_name}.value", [])} for d in dtype_values]
            p['is_enum'] = True
        elif dtype_values:
            p['dtype_with_ranges'] = [{'dtype': d} for d in dtype_values]
        format_values = factors.get(f"{param_name}.format", [])
        if format_values:
            p['format'] = format_values
        dim_values = factors.get(f"{param_name}.dimensions", [])
        if dim_values:
            p['dimensions'] = dim_values
        result[param_name] = p
        params_list.append(p)
    result['parameters'] = params_list
    return result


def save_output(case_df, output_dir, operator_name, level, verbose=False):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    templates = {
        'L0': f'{operator_name}_l0_functional.csv',
        'L1': f'{operator_name}_l1_functional.csv',
        'L2': f'{operator_name}_l2_exception.csv',
    }
    filename = templates.get(level, f'{operator_name}_{level}_test_cases.csv')
    path = output_dir / filename
    case_df.to_csv(path, index=False)
    if verbose:
        print(f"[INFO] 保存用例: {path} ({len(case_df)}条)")


def _convert_cases_to_ttk(cases, param_def, operator_name, level, csv_mode='aclnn'):
    rows = []
    meta_rows = []
    for case in cases:
        row = {k: v for k, v in case.items() if not k.startswith('_')}
        # 保存元数据，供后续语义化命名使用
        meta_rows.append({
            '_category': case.get('_category', ''),
            '_exception_type': case.get('_exception_type', ''),
            '_expected_error': case.get('_expected_error', ''),
            '_scenario_id': case.get('_scenario_id', ''),
        })
        rows.append(row)
    df = pd.DataFrame(rows, dtype=object)
    if df.empty:
        return df
    df = convert_to_ttk_format(df, param_def, operator_name, level, csv_mode)
    # 将元数据合并回结果DataFrame（convert_to_ttk_format 会重建 DataFrame，需重新附加）
    for i, meta in enumerate(meta_rows):
        for k, v in meta.items():
            df.loc[i, k] = v
    if level == 'L2':
        param_names = [k for k in param_def.keys()
                       if k not in {'operator_name', 'aclnn_name', 'parameters'}]
        for i in range(len(df)):
            exc_type = df.loc[i, '_exception_type'] if '_exception_type' in df.columns else ''
            if exc_type:
                df.loc[i, 'remark'] = _build_remark(df.iloc[i], param_names)
    return df


# ==================== 离散因子判定 ====================

def _is_discrete_factor(factor_name, values, param_type=None):
    if '.shape' in factor_name or '.value_range' in factor_name:
        return False
    if factor_name.endswith('.value'):
        if not _is_enum_value(values, param_type):
            return False
    if not isinstance(values, list) or len(values) <= 1:
        return False
    return True


def _is_enum_value(values, param_type=None):
    if param_type in ENUM_SCALAR_TYPES:
        return True
    if isinstance(values, list) and values:
        if isinstance(values[0], (bool, str)):
            return True
    return False


def _is_discrete_solved_factor(factor_name, values, param_type):
    if factor_name.endswith('.value') and _is_enum_value(values, param_type):
        return True
    if (factor_name.endswith('.dtype')
            and isinstance(values, list)
            and len(values) > 1
            and all(isinstance(v, str) for v in values)):
        return True
    return False


# ==================== 覆盖目标枚举器 ====================

def enumerate_factor_value_targets(factors, engine=None):
    solved_factors = set(engine.constraints.keys()) if engine else set()
    same_dtype_locked_factors = set()
    if engine:
        for target_factor, info in engine.constraints.items():
            if target_factor.endswith('.dtype'):
                sources = info['sources']
                dtype_sources = [s for s in sources if s.endswith('.dtype')]
                if dtype_sources and len(dtype_sources) == len(sources):
                    same_dtype_locked_factors.add(target_factor)
                    for ds in dtype_sources:
                        same_dtype_locked_factors.add(ds)
    targets = []
    for param_name, param_info in factors.items():
        if not isinstance(param_info, dict) or 'factors' not in param_info:
            continue
        param_type = param_info.get('type', '')
        for factor_name, values in param_info['factors'].items():
            if factor_name in same_dtype_locked_factors:
                continue
            if factor_name in solved_factors:
                if not _is_discrete_solved_factor(factor_name, values, param_type):
                    continue
            if not _is_discrete_factor(factor_name, values, param_type):
                continue
            for v in values:
                targets.append(CoverageTarget(
                    locked={factor_name: v},
                    category='factor_value',
                    label=f'{factor_name}={v}',
                ))
    return targets


def enumerate_infnan_targets(factors, engine=None):
    solved_factors = set(engine.constraints.keys()) if engine else set()
    targets = []
    infnan_ranges = [['inf', 'inf'], ['-inf', '-inf'], ['nan', 'nan']]
    infnan_strs = {'inf', '-inf', 'nan'}
    for param_name, param_info in factors.items():
        if not isinstance(param_info, dict) or param_info.get('io_type') != 'input':
            continue
        if param_excludes_infnan(param_info):
            continue
        dtype_key = f"{param_name}.dtype"
        if dtype_key in solved_factors:
            continue
        vr_key = f"{param_name}.value_range"
        if dtype_key not in param_info.get('factors', {}):
            continue
        float_dtypes = [d for d in param_info['factors'][dtype_key]
                        if get_dtype_category(d) == 'float']
        if not float_dtypes:
            continue
        param_factors = param_info.get('factors', {})
        for dtype in float_dtypes:
            vr_dtype_key = f"{param_name}.value_range_{dtype}"
            explicit_vr = None
            if vr_dtype_key in param_factors:
                explicit_vr = param_factors[vr_dtype_key]
            elif vr_key in param_factors:
                explicit_vr = param_factors[vr_key]
            if explicit_vr is not None:
                has_infnan = any(
                    any(str(v) in infnan_strs for v in r)
                    for r in explicit_vr
                )
                if not has_infnan:
                    continue
            for rng in infnan_ranges:
                targets.append(CoverageTarget(
                    locked={dtype_key: dtype, vr_key: rng},
                    category='infnan',
                    label=f'{param_name} dtype={dtype} range={rng}',
                ))
    return targets


def enumerate_boundary_targets(factors, engine):
    targets = []
    anchor_shapes = _identify_anchor_shape_factors(factors, engine)
    for param_name, dimensions_list in anchor_shapes.items():
        for d in dimensions_list:
            targets.append(CoverageTarget(
                locked={f'{param_name}.shape': [1] * d, f'{param_name}.dimensions': d},
                category='boundary',
                label=f'{param_name}.shape=[1]*{d}',
            ))
    for param_name, param_info in factors.items():
        if not isinstance(param_info, dict):
            continue
        ptype = param_info.get('type', '')
        if ptype in ARRAY_TYPES:
            lr_key = f"{param_name}.length_ranges"
            lr_values = param_info.get('factors', {}).get(lr_key, [])
            if isinstance(lr_values, list) and lr_values:
                if isinstance(lr_values[0], list):
                    lo = int(lr_values[0][0])
                else:
                    lo = int(lr_values[0])
                if lo > 0:
                    continue
            targets.append(CoverageTarget(
                locked={f'{param_name}.value': []},
                category='boundary',
                label=f'{param_name}.value=[]',
            ))
    return targets


def _parse_scenarios(scenarios_file, prefix='ET', category='empty_tensor'):
    """解析03_scenario_enumeration.md中的子场景（统一4列格式）。

    新格式：| 子场景 ID | locked因子 | 元数据 | 测试重点 |
    - 第2列（locked因子）：key=value，key必须是引擎因子名（如 self.shape）
    - 第3列（元数据）：ET=预期输出, BD=约束来源, EX=预期错误码
    - 第4列（测试重点）：一句话描述

    支持前缀: ET(空tensor), BD(边界值), EX(异常)
    """
    scenarios = []
    if not scenarios_file or not os.path.exists(scenarios_file):
        return scenarios

    in_section = False
    section_keywords = {
        'ET': '空tensor',
        'BD': '边界值',
        'EX': '异常',
    }

    with open(scenarios_file, 'r', encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()
            if section_keywords[prefix] in stripped and stripped.startswith('##'):
                in_section = True
                continue
            if in_section and stripped.startswith('## ') and section_keywords[prefix] not in stripped:
                in_section = False
                continue
            if not in_section:
                continue

            m = re.match(rf'\|\s*({prefix}-S\d+)\s*\|', stripped)
            if not m:
                continue

            scenario_id = m.group(1)
            cells = [c.strip() for c in stripped.split('|')]
            cells = [c for c in cells if c]

            if len(cells) < 3:
                continue

            locked = {}
            meta = {}
            locked_col = cells[1]
            meta_col = cells[2] if len(cells) > 2 else ''

            for match in re.findall(
                r'([\w.]+)\s*=\s*(\[[^\]]*\]|\{[^}]*\}|[^\s,|]+)',
                locked_col
            ):
                key, val = match
                if val.lower() == 'true':
                    locked[key] = True
                elif val.lower() == 'false':
                    locked[key] = False
                else:
                    try:
                        locked[key] = literal_eval(val)
                    except (ValueError, SyntaxError):
                        locked[key] = val

            if prefix == 'EX':
                m_err = re.search(r'(ACL_ERROR_\w+)', meta_col)
                if m_err:
                    meta['_expected_error'] = m_err.group(1)
                else:
                    meta['_expected_error'] = 'ACL_ERROR_INVALID_PARAM'
                meta['_exception_type'] = 'constraint_violation'

            description = cells[3] if len(cells) > 3 else ''
            scenarios.append((scenario_id, locked, description, category, meta))

    return scenarios


def enumerate_scenario_targets(factors, engine, scenarios_file):
    """统一生成器：从03读取所有子场景生成CoverageTarget"""
    if not scenarios_file or not os.path.exists(scenarios_file):
        return []
    targets = []
    for prefix, category in [('ET', 'empty_tensor'), ('BD', 'boundary'), ('EX', 'exception')]:
        scenarios = _parse_scenarios(scenarios_file, prefix=prefix, category=category)
        for scenario_id, locked, description, cat, meta in scenarios:
            # 跳过无法解析locked变量的场景（格式错误）
            if not locked and prefix != 'EX':
                continue
            # ET 场景中涉及参数全部不支持空tensor时跳过
            if prefix == 'ET' and locked:
                referenced_params = {k.split('.')[0] for k in locked if '.' in k}
                known = {p for p in referenced_params
                         if isinstance(factors.get(p), dict)}
                if known and all(
                    factors[p].get('support_empty_tensor') is False for p in known
                ):
                    continue
            if engine and locked:
                for key in locked:
                    if key in engine.constraints:
                        print(
                            f"[WARN] Scenario {scenario_id} locks derived factor "
                            f"'{key}' — should lock its anchor source instead",
                            file=sys.stderr,
                        )
            targets.append(CoverageTarget(
                locked=locked,
                category=cat,
                label=f'{scenario_id}: {description}',
                scenario_id=scenario_id,
            ))
    return targets


def _pick_boundary_dims(dims_sorted):
    """从有序维度列表选min/mid/max三个代表维度"""
    if not dims_sorted:
        return []
    selected = [dims_sorted[0]]
    if len(dims_sorted) >= 3:
        mid_idx = len(dims_sorted) // 2
        selected.append(dims_sorted[mid_idx])
    if len(dims_sorted) >= 2 and dims_sorted[-1] not in selected:
        selected.append(dims_sorted[-1])
    return sorted(set(selected))


def enumerate_default_shape_boundary_targets(factors, engine):
    """无明确shape约束时的默认边界兜底"""
    INT32_MAX = 2147483648
    targets = []
    anchor_shapes = _identify_anchor_shape_factors(factors, engine)

    for param_name, dimensions_list in anchor_shapes.items():
        shape_key = f"{param_name}.shape"
        dim_key = f"{param_name}.dimensions"

        if not dimensions_list:
            continue

        dims_sorted = sorted(set(dimensions_list))
        selected_dims = _pick_boundary_dims(dims_sorted)

        for d in selected_dims:
            if d == 0:
                targets.append(CoverageTarget(
                    locked={shape_key: [], dim_key: 0},
                    category='boundary',
                    label=f'{param_name} default_bound lower dim={d} shape=[]',
                ))
                continue

            # 下边界: 全1
            targets.append(CoverageTarget(
                locked={shape_key: [1] * d, dim_key: d},
                category='boundary',
                label=f'{param_name} default_bound lower dim={d} shape=[1]*{d}',
            ))
            # 上边界: 单轴极大值
            targets.append(CoverageTarget(
                locked={shape_key: [1] * (d - 1) + [INT32_MAX], dim_key: d},
                category='boundary',
                label=f'{param_name} default_bound upper dim={d} shape=[1]*{d-1}+[{INT32_MAX}]',
            ))

    return targets


def _generate_dimension_boundary_exceptions(factors):
    """维度边界异常：仅对非默认0~7维的参数生成，上溢不超过7"""
    DEFAULT_DIMS = set(range(0, 8))  # {0,1,2,3,4,5,6,7}
    cases = []

    for pn, pi in factors.items():
        if not isinstance(pi, dict) or 'factors' not in pi:
            continue
        dim_key = f"{pn}.dimensions"
        dim_vals = pi.get('factors', {}).get(dim_key, [])
        if not dim_vals:
            continue

        dim_set = set(dim_vals)
        if DEFAULT_DIMS.issubset(dim_set):
            continue  # 覆盖完整0-7维，跳过

        min_d = min(dim_vals)
        max_d = max(dim_vals)

        # 下溢
        if min_d > 0:
            case = _build_exception_base(factors)
            case[dim_key] = min_d - 1
            case['_expected_error'] = 'ACL_ERROR_INVALID_DIMENSION'
            case['_exception_type'] = 'dim_boundary_underflow'
            cases.append(case)

        # 上溢：不超过7
        if max_d < 7:
            case = _build_exception_base(factors)
            case[dim_key] = max_d + 1
            case['_expected_error'] = 'ACL_ERROR_INVALID_DIMENSION'
            case['_exception_type'] = 'dim_boundary_overflow'
            cases.append(case)

    return cases


_FORMAT_FIXED_AXES = {
    'NC1HWC0': {4: 16},
    'FRACTAL_Z': {},
    'FRACTAL_NZ': {},
}


def _get_format_fixed_axes(factors, pname):
    fmt_list = factors.get(pname, {}).get('factors', {}).get(f'{pname}.format', [])
    if not fmt_list:
        return {}
    fmt = fmt_list[0] if isinstance(fmt_list, list) else fmt_list
    return _FORMAT_FIXED_AXES.get(fmt, {})


def _generate_empty_tensor_exceptions(factors):
    """为不支持空tensor的参数生成 shape 含零轴的异常用例。

    仅对 support_empty_tensor: false 的 input tensor 参数生成。
    跳过 exist=[False]（永远不存在）的参数。
    每个参数取最小维度生成 1 条用例（首轴=0）。
    对格式固定轴（如 NC1HWC0 的 C0=16）保持其固定值不变。
    """
    cases = []
    for pname, pdef in factors.items():
        if not isinstance(pdef, dict):
            continue
        if pdef.get('type') not in ('aclTensor', 'aclTensorList'):
            continue
        if pdef.get('io_type') != 'input':
            continue
        if pdef.get('support_empty_tensor') is not False:
            continue

        exist_vals = pdef.get('factors', {}).get(f'{pname}.exist', [])
        if exist_vals == [False]:
            continue

        dims_list = pdef.get('factors', {}).get(f'{pname}.dimensions', [])
        if not dims_list:
            continue

        dims = min(dims_list)
        fixed_axes = _get_format_fixed_axes(factors, pname)
        case = _build_exception_base(factors)
        shape = [0] + [1] * (dims - 1) if dims > 0 else []
        for axis_idx, fixed_val in fixed_axes.items():
            if 0 <= axis_idx < len(shape):
                shape[axis_idx] = fixed_val
        case[f'{pname}.shape'] = shape
        case[f'{pname}.dimensions'] = dims
        case['_expected_error'] = 'ACL_ERROR_PARAM_INVALID'
        case['_exception_type'] = 'empty_tensor'
        cases.append(case)

    return cases


def _generate_reserved_param_exceptions(factors):
    """为 torchapi 预留参数（exist=[false]）生成传入非None的异常用例。

    torchapi 文档中标注"当前版本暂不支持该参数"的参数，在 YAML 中 exist=[false]。
    为此类参数生成 reserved_param_used 异常：传入非 None 值。
    """
    cases = []
    for pname, pdef in factors.items():
        if not isinstance(pdef, dict):
            continue
        if pdef.get('io_type') != 'input':
            continue
        exist_vals = pdef.get('factors', {}).get(f'{pname}.exist', [])
        if exist_vals == [False]:
            case = _build_exception_base(factors)
            case[f'{pname}.exist'] = True
            case['_expected_error'] = 'ACL_ERROR_INVALID_PARAM'
            case['_exception_type'] = 'reserved_param_used'
            cases.append(case)
    return cases


def _generate_testcase_name(operator_name, level, idx, case):
    """语义化命名：映射 _category / _exception_type → 关键字"""
    category = case.get('_category', '')
    exc_type = case.get('_exception_type', '')
    keyword = CASE_KEYWORD_MAP.get(exc_type) or CASE_KEYWORD_MAP.get(category, '')
    seq = idx + 1
    if keyword:
        return f"{operator_name}_{level}{keyword}{seq:03d}"
    return f"{operator_name}_{level}_{seq:03d}"


def _result_to_values(result, factor=None, engine=None):
    from solver.registry import Candidates, SKIP, NOT_APPLICABLE
    if isinstance(result, Candidates):
        return list(result)
    if result is NOT_APPLICABLE:
        return []
    if result is SKIP:
        if factor and engine:
            domain = engine.get_factor_domain(factor)
            if domain:
                return list(domain)
        return []
    if result is None:
        return []
    return [result]


def _restore_type(v):
    if isinstance(v, tuple):
        return list(v)
    return v


def _compute_solved_domain(factor, graph, engine, max_source_values=100, _cache=None):
    if _cache is not None and factor in _cache:
        return _cache[factor]

    rule_info = graph.all_rules.get(factor)
    if rule_info is None:
        result = []
        if _cache is not None:
            _cache[factor] = result
        return result

    if "function" not in rule_info:
        domain = engine.get_factor_domain(factor)
        if _cache is not None:
            _cache[factor] = domain
        return domain

    sources = rule_info["sources"]
    func = rule_info["function"]

    source_domains = {}
    for s in sources:
        if s in graph.all_rules:
            domain = _compute_solved_domain(s, graph, engine, max_source_values, _cache)
        else:
            domain = engine.get_factor_domain(s)
        if domain:
            source_domains[s] = domain[:max_source_values]

    if len(source_domains) != len(sources):
        result = []
        if _cache is not None:
            _cache[factor] = result
        return result

    reachable = set()
    source_names = sorted(source_domains.keys())
    source_lists = [source_domains[n] for n in source_names]

    for combo in itertools.product(*source_lists):
        context = dict(zip(source_names, combo))
        source_values = [context[s] for s in sources]
        try:
            result = func(*source_values)
        except (AssertionError, Exception):
            continue
        for v in _result_to_values(result):
            reachable.add(make_hashable(v))

    result = [_restore_type(v) for v in reachable]
    if _cache is not None:
        _cache[factor] = result
    return result


def _collect_pairwise_factors(factors, engine, graph, solved_domain_cache=None):
    pair_factors = {}

    for param_name, param_info in factors.items():
        if not isinstance(param_info, dict) or 'factors' not in param_info:
            continue
        param_type = param_info.get('type', '')

        for factor_name, values in param_info['factors'].items():
            if '.shape' in factor_name or '.value_range' in factor_name:
                continue

            if factor_name not in engine.constraints and factor_name not in engine.builtin_rules:
                if _is_discrete_factor(factor_name, values, param_type):
                    pair_factors[factor_name] = values
                continue

            domain = _compute_solved_domain(factor_name, graph, engine, _cache=solved_domain_cache)
            if not domain and isinstance(values, list) and len(values) > 1:
                domain = values
            if domain and len(domain) > 1:
                pair_factors[factor_name] = domain

    return pair_factors


def _get_factor_domain(factor, engine, graph, _cache=None):
    domain = engine.get_factor_domain(factor)
    if domain:
        return domain
    if factor in graph.all_rules:
        return _compute_solved_domain(factor, graph, engine, _cache=_cache)
    return []


def _make_hashable(v):
    if isinstance(v, list):
        return tuple(v)
    if isinstance(v, dict):
        return tuple(sorted(v.items()))
    return v


def _ipo_generate(factor_names, domains):
    f1, f2 = factor_names[0], factor_names[1]
    array = [{f1: v1, f2: v2} for v1 in domains[f1] for v2 in domains[f2]]

    for fi_idx in range(2, len(factor_names)):
        fi = factor_names[fi_idx]
        fi_domain = domains[fi]

        existing_factors = factor_names[:fi_idx]
        uncovered = set()
        for ej in existing_factors:
            for vi in fi_domain:
                for vj in domains[ej]:
                    uncovered.add((_make_hashable(ej), _make_hashable(vj), _make_hashable(fi), _make_hashable(vi)))

        for row in array:
            best_val = None
            best_cover = -1
            for vi in fi_domain:
                cover_count = 0
                for ej in existing_factors:
                    pair = (_make_hashable(ej), _make_hashable(row[ej]), _make_hashable(fi), _make_hashable(vi))
                    if pair in uncovered:
                        cover_count += 1
                if cover_count > best_cover:
                    best_cover = cover_count
                    best_val = vi
            if best_val is not None:
                row[fi] = best_val
                for ej in existing_factors:
                    uncovered.discard((_make_hashable(ej), _make_hashable(row[ej]), _make_hashable(fi), _make_hashable(best_val)))

        while uncovered:
            h_ej, h_vj, h_fi, h_vi = next(iter(uncovered))
            ej = existing_factors[0] if h_ej not in factor_names else factor_names[factor_names.index(h_ej)] if h_ej in factor_names else str(h_ej)
            fi_name = fi
            ej_idx = factor_names.index(h_ej) if h_ej in [_make_hashable(fn) for fn in factor_names] else 0
            ej = factor_names[ej_idx]
            vj = domains[ej][[_make_hashable(d) for d in domains[ej]].index(h_vj)] if h_vj in [_make_hashable(d) for d in domains[ej]] else domains[ej][0]
            vi = domains[fi][[_make_hashable(d) for d in domains[fi]].index(h_vi)] if h_vi in [_make_hashable(d) for d in domains[fi]] else domains[fi][0]
            new_row = {ej: vj, fi_name: vi}
            for fk in factor_names[:fi_idx + 1]:
                if fk not in new_row:
                    new_row[fk] = domains[fk][0]
            for ek in existing_factors:
                uncovered.discard((_make_hashable(ek), _make_hashable(new_row[ek]), _make_hashable(fi_name), _make_hashable(vi)))
            for vk in fi_domain:
                uncovered.discard((_make_hashable(ej), _make_hashable(vj), _make_hashable(fi_name), _make_hashable(vk)))
            array.append(new_row)

    return array


def enumerate_independent_pairwise(independent_factors):
    if len(independent_factors) < 2:
        return []

    factor_names = sorted(
        independent_factors.keys(),
        key=lambda f: len(independent_factors[f]),
        reverse=True
    )

    covering_array = _ipo_generate(factor_names, independent_factors)

    targets = []
    for row in covering_array:
        locked = {f: row[f] for f in factor_names}
        targets.append(CoverageTarget(
            locked=locked,
            category='pairwise',
            label=' × '.join(f'{k}={v}' for k, v in sorted(locked.items())),
        ))
    return targets


def _identify_other_sources(ancestor, sources, graph):
    ancestor_set = graph.get_ancestors(ancestor) | {ancestor}
    desc = set()
    for f in list(ancestor_set):
        for t in graph.source_to_targets.get(f, []):
            desc.add(t)
    ancestor_set = ancestor_set | desc

    other = [s for s in sources if s not in ancestor_set]
    return other


def _enumerate_other_contexts(other_sources, engine, graph, _cache=None, max_per_source=100):
    if not other_sources:
        yield {}
        return

    domains = []
    for s in other_sources:
        d = _get_factor_domain(s, engine, graph, _cache)
        if d:
            domains.append(d[:max_per_source])
        else:
            domains.append([None])

    for combo in itertools.product(*domains):
        yield dict(zip(other_sources, combo))


def enumerate_ancestor_descendant_pairwise(f1, f2, graph, engine, _cache=None):
    if f1 in graph.get_ancestors(f2):
        ancestor, descendant = f1, f2
    else:
        ancestor, descendant = f2, f1

    rule_info = graph.all_rules.get(descendant)
    if rule_info is None:
        return []

    func = rule_info["function"]
    sources = rule_info["sources"]

    ancestor_domain = _get_factor_domain(ancestor, engine, graph, _cache)
    if not ancestor_domain:
        return []

    other_sources = _identify_other_sources(ancestor, sources, graph)

    targets = []
    seen_pairs = set()

    for av in ancestor_domain:
        for ctx in _enumerate_other_contexts(other_sources, engine, graph, _cache):
            ctx[ancestor] = av

            source_values = [ctx.get(s) for s in sources]
            if any(v is None for v in source_values):
                continue

            try:
                result = func(*source_values)
            except (AssertionError, Exception):
                continue

            descendant_vals = _result_to_values(result)
            for dv in descendant_vals:
                pair_key = (str(av), str(dv))
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    targets.append(CoverageTarget(
                        locked={ancestor: av, descendant: dv},
                        category='pairwise',
                        label=f'{ancestor}={av} → {descendant}={dv}',
                    ))

    return targets


def _select_nearest_common_ancestor(common_ancestors, graph):
    best = None
    best_level = -1
    for a in common_ancestors:
        level = len(graph.get_ancestors(a))
        if level > best_level:
            best_level = level
            best = a
    return best


def _derive_reachable_values(ancestor, ancestor_value, target, graph, engine):
    path = graph.find_shortest_constraint_path(ancestor, target)
    if not path:
        return []

    path_rules = []
    for factor in path[1:]:
        rule_info = graph.all_rules.get(factor)
        if rule_info is None:
            return []
        if "function" not in rule_info:
            return []
        path_rules.append((factor, rule_info))

    reachable = set()
    call_count = [0]
    MAX_DFS_CALLS = 500

    def _dfs(level, context):
        if call_count[0] >= MAX_DFS_CALLS:
            return
        call_count[0] += 1

        if level == len(path_rules):
            val = context.get(target)
            if val is not None:
                reachable.add(make_hashable(val))
            return

        factor, rule_info = path_rules[level]
        sources = rule_info["sources"]
        func = rule_info["function"]

        missing = [s for s in sources if s not in context]
        if missing:
            missing_domains = []
            for s in missing:
                d = _get_factor_domain(s, engine, graph)
                if d:
                    missing_domains.append((s, d[:3]))
                else:
                    return

            for combo in itertools.product(*[d for _, d in missing_domains]):
                if call_count[0] >= MAX_DFS_CALLS:
                    return
                new_context = dict(context)
                new_context.update(dict(zip([s for s, _ in missing_domains], combo)))
                source_values = [new_context.get(s) for s in sources]
                try:
                    result = func(*source_values)
                except (AssertionError, Exception):
                    continue
                for v in _result_to_values(result, factor=factor, engine=engine):
                    new_ctx = dict(new_context)
                    new_ctx[factor] = v
                    _dfs(level + 1, new_ctx)
        else:
            source_values = [context.get(s) for s in sources]
            try:
                result = func(*source_values)
            except (AssertionError, Exception):
                return
            for v in _result_to_values(result):
                if call_count[0] >= MAX_DFS_CALLS:
                    return
                new_context = dict(context)
                new_context[factor] = v
                _dfs(level + 1, new_context)

    _dfs(0, {ancestor: ancestor_value})
    return [_restore_type(v) for v in reachable]


def enumerate_common_ancestor_pairwise(f1, f2, graph, engine, _cache=None):
    anc_f1 = graph.get_ancestors(f1)
    anc_f2 = graph.get_ancestors(f2)
    common = anc_f1 & anc_f2

    if not common:
        return []

    best_ancestor = _select_nearest_common_ancestor(common, graph)
    if best_ancestor is None:
        return []

    ancestor_domain = _get_factor_domain(best_ancestor, engine, graph, _cache)
    if not ancestor_domain:
        return []

    targets = []
    seen_pairs = set()

    for av in ancestor_domain:
        vals_f1 = _derive_reachable_values(best_ancestor, av, f1, graph, engine)
        vals_f2 = _derive_reachable_values(best_ancestor, av, f2, graph, engine)

        for v1 in vals_f1:
            for v2 in vals_f2:
                pair_key = (str(v1), str(v2))
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    targets.append(CoverageTarget(
                        locked={best_ancestor: av, f1: v1, f2: v2},
                        category='pairwise',
                        label=f'{best_ancestor}={av} → {f1}={v1}, {f2}={v2}',
                    ))

    return targets


def enumerate_mixed_pairwise(f1, f2, pair_factors, graph, engine, _cache=None):
    domain1 = _get_factor_domain(f1, engine, graph, _cache)
    domain2 = _get_factor_domain(f2, engine, graph, _cache)
    if not domain1 or not domain2:
        return []

    targets = []
    seen_pairs = set()
    for v1 in domain1:
        for v2 in domain2:
            pair_key = (str(v1), str(v2))
            if pair_key not in seen_pairs:
                seen_pairs.add(pair_key)
                targets.append(CoverageTarget(
                    locked={f1: v1, f2: v2},
                    category='pairwise',
                    label=f'{f1}={v1} × {f2}={v2}',
                ))
    return targets


def enumerate_constraint_aware_pairwise(factors, engine, graph):
    solved_domain_cache = {}

    pair_factors = _collect_pairwise_factors(factors, engine, graph, solved_domain_cache)
    factor_names = sorted(pair_factors.keys())

    anchor_factors = set()
    solved_factors = set()
    for fn in factor_names:
        if fn in engine.constraints or fn in engine.builtin_rules:
            solved_factors.add(fn)
        else:
            anchor_factors.add(fn)

    anchor_ind_pairs = set()
    dependent_pairs = []
    mixed_pairs = []

    for i in range(len(factor_names)):
        for j in range(i + 1, len(factor_names)):
            f1, f2 = factor_names[i], factor_names[j]
            relation = graph.classify_pair(f1, f2)

            if relation == "independent":
                if f1 in anchor_factors and f2 in anchor_factors:
                    anchor_ind_pairs.add((f1, f2))
                else:
                    mixed_pairs.append((f1, f2))
            else:
                dependent_pairs.append((f1, f2, relation))

    anchor_set = set()
    for f1, f2 in anchor_ind_pairs:
        anchor_set.add(f1)
        anchor_set.add(f2)

    targets = []

    if len(anchor_set) >= 2:
        ind_factors = {f: pair_factors[f] for f in sorted(anchor_set)}
        targets.extend(enumerate_independent_pairwise(ind_factors))

    for f1, f2, relation in dependent_pairs:
        if relation == "ancestor_descendant":
            ad_targets = enumerate_ancestor_descendant_pairwise(f1, f2, graph, engine, solved_domain_cache)
            if not ad_targets:
                ad_targets = enumerate_mixed_pairwise(f1, f2, pair_factors, graph, engine, solved_domain_cache)
            targets.extend(ad_targets)
        elif relation == "common_ancestor":
            ca_targets = enumerate_common_ancestor_pairwise(f1, f2, graph, engine, solved_domain_cache)
            if not ca_targets:
                ca_targets = enumerate_mixed_pairwise(f1, f2, pair_factors, graph, engine, solved_domain_cache)
            targets.extend(ca_targets)

    for f1, f2 in mixed_pairs:
        targets.extend(
            enumerate_mixed_pairwise(f1, f2, pair_factors, graph, engine, solved_domain_cache)
        )

    return targets


def enumerate_length_boundary_targets(factors):
    targets = []
    for param_name, param_info in factors.items():
        if not isinstance(param_info, dict):
            continue
        if param_info.get('type') not in ARRAY_TYPES:
            continue
        if param_info.get('io_type') != 'input':
            continue
        lr_key = f"{param_name}.length_ranges"
        lr_values = param_info.get('factors', {}).get(lr_key, [])
        if not isinstance(lr_values, list) or not lr_values:
            continue
        if isinstance(lr_values[0], list):
            lo, hi = int(lr_values[0][0]), int(lr_values[0][1])
        else:
            lo, hi = int(lr_values[0]), int(lr_values[1])
        if lo == 0:
            targets.append(CoverageTarget(
                locked={f'{param_name}.length': 0},
                category='boundary', label=f'{param_name}.length=0',
            ))
        if hi > 0:
            targets.append(CoverageTarget(
                locked={f'{param_name}.length': hi},
                category='boundary', label=f'{param_name}.length={hi}',
            ))
    return targets


def enumerate_datarange_targets(factors, engine=None):
    targets = []
    for param_name, param_info in factors.items():
        if not isinstance(param_info, dict):
            continue
        if param_info.get('io_type') != 'input':
            continue
        dtype_key = f"{param_name}.dtype"
        vr_key = f"{param_name}.value_range"
        if dtype_key not in param_info.get('factors', {}):
            continue
        if engine and (vr_key in engine.constraints or vr_key in engine.builtin_rules):
            continue
        for dtype in param_info['factors'][dtype_key]:
            ranges = get_default_value_range(dtype)
            if param_info.get('support_infnan') is False:
                ranges = [r for r in ranges if not _is_infnan_range(r)]
            for rng in ranges:
                targets.append(CoverageTarget(
                    locked={dtype_key: dtype, vr_key: rng},
                    category='infnan' if _is_infnan_range(rng) else 'factor_value',
                    label=f'{param_name} dtype={dtype} range={rng}',
                ))
    return targets


def enumerate_scenario_pairwise_targets(factors, scenarios_file, engine=None):
    if not scenarios_file or not os.path.exists(scenarios_file):
        return []
    scenario_ids = _parse_scenario_ids(scenarios_file)
    if not scenario_ids:
        return []
    solved_factors = set(engine.constraints.keys()) if engine else set()
    discrete_factors = {}
    for param_name, param_info in factors.items():
        if not isinstance(param_info, dict) or 'factors' not in param_info:
            continue
        param_type = param_info.get('type', '')
        for factor_name, values in param_info['factors'].items():
            if factor_name in solved_factors:
                if not _is_discrete_solved_factor(factor_name, values, param_type):
                    continue
            if _is_discrete_factor(factor_name, values, param_type) and len(values) > 1:
                discrete_factors[factor_name] = values
    targets = []
    key_factors = sorted(discrete_factors.keys())[:5]
    for sid in sorted(scenario_ids):
        for fn in key_factors:
            for v in discrete_factors[fn]:
                targets.append(CoverageTarget(
                    locked={fn: v}, category='pairwise',
                    label=f'scenario {sid} x {fn}={v}', scenario_id=sid,
                ))
    return targets


def _identify_anchor_shape_factors(factors, engine):
    anchors = {}
    for param_name, param_info in factors.items():
        if not isinstance(param_info, dict):
            continue
        if param_info.get('type') not in ('aclTensor', 'aclTensorList'):
            continue
        if param_info.get('io_type') != 'input':
            continue
        shape_key = f"{param_name}.shape"
        dim_key = f"{param_name}.dimensions"
        if shape_key in engine.constraints:
            continue
        dim_values = param_info.get('factors', {}).get(dim_key, [])
        if dim_values:
            anchors[param_name] = dim_values
    return anchors


def _is_infnan_range(rng):
    if isinstance(rng, (list, tuple)):
        s = str(rng).lower()
        return 'inf' in s or 'nan' in s
    return False


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


def _enumerate_same_dtype_targets(factors, engine):
    targets = []
    seen_pairs = set()

    for target_factor, info in engine.constraints.items():
        if not target_factor.endswith('.dtype'):
            continue
        sources = info['sources']
        dtype_sources = [s for s in sources if s.endswith('.dtype')]
        if not dtype_sources:
            continue

        target_param = target_factor.rsplit('.', 1)[0]
        target_param_info = factors.get(target_param)
        if not isinstance(target_param_info, dict):
            continue
        if target_param_info.get('io_type') not in ('input', 'output'):
            continue
        target_is_tensor = target_param_info.get('type') in ('aclTensor', 'aclTensorList')
        if not target_is_tensor:
            continue

        for src_dtype in dtype_sources:
            src_param = src_dtype.rsplit('.', 1)[0]
            src_param_info = factors.get(src_param)
            if not isinstance(src_param_info, dict):
                continue
            if src_param_info.get('io_type') != 'input':
                continue
            src_is_tensor = src_param_info.get('type') in ('aclTensor', 'aclTensorList')
            if not src_is_tensor:
                continue

            pair_key = tuple(sorted([src_dtype, target_factor]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            src_domain = engine.get_factor_domain(src_dtype)
            if not src_domain:
                continue

            for dtype_val in src_domain:
                targets.append(CoverageTarget(
                    locked={src_dtype: dtype_val, target_factor: dtype_val},
                    category='factor_value',
                    label=f'same-dtype {src_dtype}={dtype_val} == {target_factor}={dtype_val}',
                ))

    return targets


def _report_scenario_coverage(cases, scenarios, level):
    """报告ET/BD场景在用例中的覆盖情况"""
    if not scenarios:
        return
    covered = []
    uncovered = []
    for sid, locked, description, cat, meta in scenarios:
        found = False
        for case in cases:
            match = True
            for k, v in locked.items():
                if case.get(k) != v:
                    match = False
                    break
            if match:
                found = True
                break
        if found:
            covered.append(sid)
        else:
            uncovered.append(sid)
    if covered:
        print(f"[SCENARIO-COVERAGE] {level} 已覆盖场景: {', '.join(covered)}")
    if uncovered:
        print(f"[WARN] {level} 未覆盖场景: {', '.join(uncovered)}")
        print(f"[WARN] 请检查 @solves 约束函数是否正确支持上述场景的锁定变量")


# ==================== L0 生成 ====================

def generate_L0(engine, factors, param_def, args, verbose=False):
    cases = []
    seen = set()

    targets = []
    targets.extend(_enumerate_same_dtype_targets(factors, engine))
    targets.extend(enumerate_factor_value_targets(factors, engine))
    targets.extend(enumerate_infnan_targets(factors, engine))
    targets.extend(_enumerate_l0_exist_targets(factors))
    targets.extend(_enumerate_l0_dimension_targets(factors))
    targets.extend(_enumerate_l0_format_cross_targets(factors, engine))

    scenarios_file = getattr(args, 'scenarios', None) or getattr(args, 'scenarios_file', None)
    st = enumerate_scenario_targets(factors, engine, scenarios_file)
    targets.extend([t for t in st if t.category != 'exception'])
    targets.extend(enumerate_default_shape_boundary_targets(factors, engine))

    if verbose:
        print(f"[INFO] L0 覆盖目标: {len(targets)} 个")

    for target in targets:
        case = engine.solve_one(target.locked)
        if case is None:
            if verbose:
                print(f"[WARN] L0 未求解: {target.label}")
            continue
        key = _case_key(case)
        if key in seen:
            continue
        seen.add(key)
        case['_function'] = _determine_function(target, case)
        case['_category'] = target.category
        cases.append(case)

    scenarios_file = getattr(args, 'scenarios', None) or getattr(args, 'scenarios_file', None)
    if scenarios_file:
        cases = _verify_and_pad_scenarios(engine, cases, scenarios_file, factors, seen, verbose)

    cases = _verify_and_pad_solved_factor_coverage(engine, cases, factors, seen, verbose)

    if scenarios_file and verbose:
        et_scenarios = _parse_scenarios(scenarios_file, prefix='ET', category='empty_tensor')
        bd_scenarios = _parse_scenarios(scenarios_file, prefix='BD', category='boundary')
        _report_scenario_coverage(cases, et_scenarios + bd_scenarios, 'L0')

    if verbose:
        print(f"[INFO] L0 生成: {len(cases)} 条用例")

    return cases[:200]


def _enumerate_l0_exist_targets(factors):
    targets = []
    for param_name, param_info in factors.items():
        if not isinstance(param_info, dict):
            continue
        exist_key = f"{param_name}.exist"
        if exist_key not in param_info.get('factors', {}):
            continue
        exist_values = param_info['factors'][exist_key]
        if exist_values == [True]:
            continue
        if True in exist_values:
            targets.append(CoverageTarget(locked={exist_key: True}, category='factor_value', label=f'{param_name} exist=True'))
        if False in exist_values:
            targets.append(CoverageTarget(locked={exist_key: False}, category='factor_value', label=f'{param_name} exist=False'))
    return targets


def _enumerate_l0_dimension_targets(factors):
    targets = []
    for param_name, param_info in factors.items():
        if not isinstance(param_info, dict):
            continue
        if param_info.get('type') not in ('aclTensor', 'aclTensorList'):
            continue
        if param_info.get('io_type') != 'input':
            continue
        dim_key = f"{param_name}.dimensions"
        dim_values = param_info.get('factors', {}).get(dim_key, [])
        if isinstance(dim_values, list) and dim_values:
            dim_min, dim_max = min(dim_values), max(dim_values)
            targets.append(CoverageTarget(locked={dim_key: dim_min}, category='factor_value', label=f'{param_name} dim={dim_min}'))
            if dim_max != dim_min:
                targets.append(CoverageTarget(locked={dim_key: dim_max}, category='factor_value', label=f'{param_name} dim={dim_max}'))
    return targets


def _enumerate_l0_format_cross_targets(factors, engine=None):
    solved_factors = set(engine.constraints.keys()) if engine else set()
    targets = []
    for param_name, param_info in factors.items():
        if not isinstance(param_info, dict):
            continue
        if param_info.get('type') not in ('aclTensor', 'aclTensorList'):
            continue
        if param_info.get('io_type') != 'input':
            continue
        fmt_key = f"{param_name}.format"
        if fmt_key in solved_factors:
            continue
        fmt_values = param_info.get('factors', {}).get(fmt_key, [])
        if isinstance(fmt_values, list) and len(fmt_values) > 1:
            for fv in fmt_values:
                targets.append(CoverageTarget(locked={fmt_key: fv}, category='factor_value', label=f'{param_name} format={fv}'))
    return targets


def _verify_and_pad_scenarios(engine, cases, scenario_file, factors, seen, verbose):
    scenario_ids = _parse_scenario_ids(scenario_file)
    if not scenario_ids:
        return cases
    covered = set()
    for case in cases:
        for k, v in case.items():
            if k.startswith('_tag_') and v is not None:
                for sid in scenario_ids:
                    if sid in str(v):
                        covered.add(sid)
    uncovered = scenario_ids - covered
    if not uncovered:
        if verbose:
            print(f"[INFO] L0 场景覆盖: 全部 {len(scenario_ids)} 个已覆盖")
        return cases
    if verbose:
        print(f"[WARN] L0 未覆盖场景: {sorted(uncovered)}")
    for sid in uncovered:
        targeted = _build_targeted_partial_for_scenario(sid, factors)
        if targeted:
            for _ in range(10):
                case = engine.solve_one(targeted)
                if case and _case_covers_scenario(case, sid):
                    key = _case_key(case)
                    if key not in seen:
                        seen.add(key)
                        case['_function'] = 'fuzz'
                        case['_category'] = 'scenario'
                        cases.append(case)
                        break
        if not _case_covers_any(cases, sid):
            for _ in range(20):
                case = engine.solve_one({})
                if case and _case_covers_scenario(case, sid):
                    key = _case_key(case)
                    if key not in seen:
                        seen.add(key)
                        case['_function'] = 'fuzz'
                        case['_category'] = 'scenario'
                        cases.append(case)
                        break
    return cases


def _verify_and_pad_solved_factor_coverage(engine, cases, factors, seen, verbose=False):
    if not engine:
        return cases
    solved_factors = set(engine.constraints.keys())
    same_dtype_locked_factors = set()
    for target_factor, info in engine.constraints.items():
        if target_factor.endswith('.dtype'):
            sources = info['sources']
            dtype_sources = [s for s in sources if s.endswith('.dtype')]
            if dtype_sources and len(dtype_sources) == len(sources):
                same_dtype_locked_factors.add(target_factor)
                for ds in dtype_sources:
                    same_dtype_locked_factors.add(ds)
    gaps = []
    for param_name, param_info in factors.items():
        if not isinstance(param_info, dict) or 'factors' not in param_info:
            continue
        param_type = param_info.get('type', '')
        for factor_name, values in param_info['factors'].items():
            if factor_name not in solved_factors:
                continue
            if factor_name in same_dtype_locked_factors:
                continue
            if not _is_discrete_solved_factor(factor_name, values, param_type):
                continue
            if len(values) <= 1:
                continue
            covered = set()
            for case in cases:
                val = case.get(factor_name)
                if val is not None:
                    covered.add(val)
            uncovered = [v for v in values if v not in covered]
            if uncovered:
                gaps.append((factor_name, uncovered))
    if not gaps:
        return cases
    if verbose:
        gap_desc = ', '.join(f'{fn}: {len(uv)}' for fn, uv in gaps)
        print(f"[INFO] L0 solved factor 值域覆盖补全: {gap_desc} 个值未覆盖")
    for factor_name, uncovered_values in gaps:
        constraint_info = engine.constraints[factor_name]
        sources = constraint_info['sources']
        anchor_sources = []
        visited = set()
        queue = list(sources)
        while queue:
            src = queue.pop(0)
            if src in visited:
                continue
            visited.add(src)
            if src in solved_factors:
                src_sources = engine.constraints[src]['sources']
                queue.extend(src_sources)
                continue
            src_domain = engine.get_factor_domain(src)
            if src_domain and len(src_domain) > 1:
                anchor_sources.append((src, src_domain))
        for uv in uncovered_values:
            generated = False
            if anchor_sources:
                for src_name, src_domain in anchor_sources:
                    if generated:
                        break
                    for sv in src_domain:
                        if generated:
                            break
                        for attempt in range(5):
                            case = engine.solve_one({src_name: sv, factor_name: uv})
                            if case is not None:
                                key = _case_key(case)
                                if key not in seen:
                                    seen.add(key)
                                    case['_function'] = 'solved_coverage'
                                    case['_category'] = 'solved_coverage'
                                    cases.append(case)
                                    generated = True
                                    break
            if not generated:
                for attempt in range(10):
                    case = engine.solve_one({factor_name: uv})
                    if case is not None:
                        key = _case_key(case)
                        if key not in seen:
                            seen.add(key)
                            case['_function'] = 'solved_coverage'
                            case['_category'] = 'solved_coverage'
                            cases.append(case)
                            break

    still_uncovered = []
    for factor_name, uncovered_values in gaps:
        covered = set()
        for case in cases:
            val = case.get(factor_name)
            if val is not None:
                covered.add(val)
        remaining = [v for v in uncovered_values if v not in covered]
        if remaining:
            still_uncovered.append((factor_name, remaining))

    if still_uncovered:
        print("[DOMAIN-COVERAGE-REPORT]")
        for fn, vals in still_uncovered:
            for v in vals:
                print(f"  factor={fn} value={v} classification=primary "
                      f"repair_target=04_constraints.py target={fn}")
        sys.exit(2)

    return cases


def _build_targeted_partial_for_scenario(scenario_id, factors):
    partial = {}
    for param_name, param_info in factors.items():
        if not isinstance(param_info, dict):
            continue
        if param_info.get('type') not in ('aclTensor', 'aclTensorList'):
            continue
        if param_info.get('io_type') != 'input':
            continue
        dim_key = f"{param_name}.dimensions"
        dim_values = param_info.get('factors', {}).get(dim_key, [])
        if isinstance(dim_values, list) and len(dim_values) > 1:
            partial[dim_key] = random.choice(dim_values)
    return partial if partial else None


def _case_covers_scenario(case, sid):
    for k, v in case.items():
        if k.startswith('_tag_') and v is not None and sid in str(v):
            return True
    return False


def _case_covers_any(cases, sid):
    return any(_case_covers_scenario(c, sid) for c in cases)


def _parse_scenario_ids(scenario_file):
    ids = set()
    if not os.path.exists(scenario_file):
        return ids
    with open(scenario_file, 'r', encoding='utf-8') as f:
        for line in f:
            for m in re.finditer(r'(C\d+-S\d+)', line):
                ids.add(m.group(1))
    return ids


_STATIC_ANCHOR_RE = re.compile(r'\.value_range_(?:int|uint|float|bfloat|bool|string)')


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

def _case_key(case):
    return tuple(sorted(
        (k, str(v)) for k, v in case.items()
        if not k.startswith('_') and not _STATIC_ANCHOR_RE.search(k)
    ))


# ==================== L0←L1 提升 ====================

_PROMOTE_THRESHOLD = 20


def _promote_l1_to_fill_l0(l0_cases, l1_cases, threshold=_PROMOTE_THRESHOLD, verbose=False):
    promoted = list(l0_cases)

    l1_values = defaultdict(set)
    for case in l1_cases:
        for k, v in case.items():
            if k.startswith('_function') or k.startswith('_category') or v is None:
                continue
            l1_values[k].add(make_hashable(v))

    finite_factors = {k: v for k, v in l1_values.items() if 1 < len(v) <= threshold}

    l0_covered = defaultdict(set)
    for case in promoted:
        for k in finite_factors:
            v = case.get(k)
            if v is not None:
                l0_covered[k].add(make_hashable(v))

    seen = set(_case_key(c) for c in promoted)

    missing_map = {}
    for factor in sorted(finite_factors.keys()):
        missing = finite_factors[factor] - l0_covered.get(factor, set())
        if missing:
            missing_map[factor] = sorted(missing, key=str)

    if not missing_map:
        return promoted

    if verbose:
        total_missing = sum(len(v) for v in missing_map.values())
        print(f"[INFO] L0 有限值域覆盖缺失: {total_missing} 个值"
              f"（涉及 {len(missing_map)} 个因子）")

    l1_index = defaultdict(list)
    for case in l1_cases:
        for factor in missing_map:
            v = case.get(factor)
            if v is not None:
                h = make_hashable(v)
                if h in missing_map[factor]:
                    l1_index[(factor, h)].append(case)

    promote_count = 0
    for factor in sorted(missing_map.keys()):
        for mv in missing_map[factor]:
            candidates = l1_index.get((factor, mv), [])
            added = False
            for cand in candidates:
                key = _case_key(cand)
                if key in seen:
                    continue
                seen.add(key)
                new_case = dict(cand)
                new_case['_category'] = 'promoted'
                promoted.append(new_case)
                for k2 in finite_factors:
                    v2 = new_case.get(k2)
                    if v2 is not None:
                        l0_covered[k2].add(make_hashable(v2))
                promote_count += 1
                added = True
                break
            if not added and verbose:
                print(f"[WARN] L0 提升: 无法为 {factor}={mv} 找到不重复的 L1 用例")

    budget = 200 - len(l0_cases)
    if len(promoted) > len(l0_cases) + budget:
        promoted = promoted[:len(l0_cases) + budget]

    if verbose and promote_count > 0:
        print(f"[INFO] L0 从 L1 提升 {promote_count} 条用例补齐有限值域覆盖")

    return promoted


# ==================== L1 生成 ====================

def generate_L1(engine, factors, param_def, args):
    cases = []
    seen = set()

    graph = ConstraintGraph(engine.constraints, engine.builtin_rules)
    pw = enumerate_constraint_aware_pairwise(factors, engine, graph)

    bd = enumerate_boundary_targets(factors, engine)
    lb = enumerate_length_boundary_targets(factors)
    dr = enumerate_datarange_targets(factors, engine)
    scenarios_file = getattr(args, 'scenarios', None)
    sp = enumerate_scenario_pairwise_targets(factors, scenarios_file, engine)
    st = [t for t in enumerate_scenario_targets(factors, engine, scenarios_file)
          if t.category != 'exception']
    db = enumerate_default_shape_boundary_targets(factors, engine)

    all_targets = pw + bd + lb + dr + sp + st + db

    if args.verbose:
        print(f"[INFO] L1 目标: {len(all_targets)} (pw={len(pw)} bd={len(bd)} lb={len(lb)} dr={len(dr)} sp={len(sp)} st={len(st)} db={len(db)})")

    for target in all_targets:
        if target.category == 'pairwise':
            case = engine.solve_one_pairwise(target.locked)
        else:
            case = engine.solve_one(target.locked)
        if case is None:
            continue
        key = _case_key(case)
        if key in seen:
            continue
        seen.add(key)
        case['_function'] = _determine_function(target, case)
        case['_category'] = target.category
        cases.append(case)

    tc = args.target_count
    if len(cases) < tc:
        deficit = tc - len(cases)
        cases = _pad_with_random_cases(engine, cases, min(deficit * 3, deficit + 15), seen, args.seed)

    if scenarios_file and args.verbose:
        et_scenarios = _parse_scenarios(scenarios_file, prefix='ET', category='empty_tensor')
        bd_scenarios = _parse_scenarios(scenarios_file, prefix='BD', category='boundary')
        _report_scenario_coverage(cases, et_scenarios + bd_scenarios, 'L1')

    if args.verbose:
        print(f"[INFO] L1 生成: {len(cases)} 条")

    return cases, seen


def _pad_with_random_cases(engine, existing, count, seen, seed):
    padded = list(existing)

    shape_factors = []
    for sf, ri in engine.builtin_rules.items():
        if ri.get('rule') == 'IMPL-SHAPE':
            dim_key = ri['sources'][0]
            shape_factors.append((sf, dim_key))

    key_anchors = {}
    for fn in engine.anchors:
        if _STATIC_ANCHOR_RE.search(fn):
            continue
        domain = engine.get_factor_domain(fn)
        if domain and len(domain) > 1:
            key_anchors[fn] = domain

    anchor_names = sorted(key_anchors.keys())
    anchor_domains = [key_anchors[n] for n in anchor_names]
    anchor_combos = list(itertools.product(*anchor_domains)) if anchor_domains else [()]

    shapes_per_combo = max(1, (count + len(anchor_combos) - 1) // len(anchor_combos))
    base_seed = (seed or 0) + 100000

    for combo_idx, combo_values in enumerate(anchor_combos):
        if len(padded) >= len(existing) + count:
            break

        anchor_partial = dict(zip(anchor_names, combo_values))

        for shape_idx in range(shapes_per_combo + 15):
            if len(padded) >= len(existing) + count:
                break

            partial = dict(anchor_partial)

            if not shape_factors:
                partial['_pad_seed'] = base_seed + combo_idx * 1000 + shape_idx

            for sf, dim_key in shape_factors:
                dim_domain = engine.get_factor_domain(dim_key)
                dims = 1
                if dim_domain:
                    d = dim_domain[shape_idx % len(dim_domain)]
                    dims = int(d) if isinstance(d, int) else 1
                partial[dim_key] = dims
                partial[sf] = generate_random_shape(dims, seed=base_seed + combo_idx * 1000 + shape_idx)

            case = engine.solve_one(partial, max_attempts=10)
            if case is not None:
                key = _case_key(case)
                if key not in seen:
                    seen.add(key)
                    case['_function'] = 'fuzz'
                    case['_category'] = 'random'
                    padded.append(case)

    return padded


def _replenish_l1(case_df, engine, factors, param_def, operator_name, level,
                  deficit, args, dedup_cols, initial_seen=None,
                  csv_mode='aclnn'):
    max_rounds = 5
    seen = set(initial_seen) if initial_seen else set()
    no_progress_count = 0
    for round_idx in range(max_rounds):
        if len(case_df) >= args.target_count:
            break
        if no_progress_count >= 2:
            break
        need = args.target_count - len(case_df)
        extra_raw = _pad_with_random_cases(engine, [], need, seen,
                                           (args.seed or 0) + round_idx * 10000)
        if not extra_raw:
            no_progress_count += 1
            continue
        for c in extra_raw:
            seen.add(_case_key(c))
        if csv_mode == 'kernel':
            extra_df = generate_kernelttk_cases._convert_cases_to_aclnn_kernel(
                extra_raw, param_def, operator_name, level
            )
            extra_df, invalid_count, _ = generate_kernelttk_cases._validate_aclnn_cases(extra_df)
        else:
            extra_df = _convert_cases_to_ttk(extra_raw, param_def, operator_name, level, csv_mode)
            extra_df, invalid_count, _ = validate_ttk_cases(extra_df)
        if len(extra_df) == 0:
            no_progress_count += 1
            continue
        prev_len = len(case_df)
        case_df = pd.concat([case_df, extra_df], ignore_index=True)
        case_df = case_df.drop_duplicates(subset=dedup_cols, keep='first').reset_index(drop=True)
        if len(case_df) == prev_len:
            no_progress_count += 1
        else:
            no_progress_count = 0
        if args.verbose:
            print(f"[INFO] L1 补充 round {round_idx+1}: +{len(extra_df)} 条"
                  f"（{invalid_count} 条无效），去重后共 {len(case_df)} 条")
    return case_df


# ==================== L2 生成 ====================

def generate_L2(engine, factors, param_def, args=None, verbose=False):
    cases = []
    cases.extend(_generate_out_of_domain_cases(factors))
    cases.extend(_generate_constraint_violation_cases(factors, engine))
    cases.extend(_generate_supplementary_exception_cases(factors))
    cases.extend(_generate_dimension_boundary_exceptions(factors))
    cases.extend(_generate_empty_tensor_exceptions(factors))
    cases.extend(_generate_reserved_param_exceptions(factors))

    # 场景驱动的EX异常
    scenarios_file = None
    if args is not None:
        scenarios_file = getattr(args, 'scenarios', None)
    if scenarios_file and os.path.exists(scenarios_file):
        ex_scenarios = _parse_scenarios(scenarios_file, prefix='EX', category='exception')
        for sid, locked, desc, cat, meta in ex_scenarios:
            case = _build_exception_base(factors)
            case.update(locked)
            case['_expected_error'] = meta.get('_expected_error', 'ACL_ERROR_INVALID_PARAM')
            case['_exception_type'] = meta.get('_exception_type', 'constraint_violation')
            case['_scenario_id'] = sid
            cases.append(case)

    cases = _deduplicate(cases)
    cases = cases[:200]

    if engine is not None:
        all_engine_factors = {f for lvl in engine.topology_order.values() for f in lvl}
        for ci, case in enumerate(cases):
            locked = {k: v for k, v in case.items()
                      if not k.startswith('_') and k in all_engine_factors}
            locked['__ci'] = ci
            filled = engine.solve_one(locked, max_attempts=1)
            if filled is None:
                filled = engine.solve_one({'__ci': ci}, max_attempts=1)
            if filled is not None:
                for k, v in filled.items():
                    if k not in case and not k.startswith('_'):
                        case[k] = v

    for case in cases:
        case['_function'] = 'exception'
        case['_category'] = 'exception'
    if verbose:
        print(f"[INFO] L2 生成: {len(cases)} 条异常用例")
    return cases


def _generate_out_of_domain_cases(factors):
    cases = []
    for param_name, param_info in factors.items():
        if not isinstance(param_info, dict) or 'factors' not in param_info:
            continue
        param_type = param_info.get('type', '')
        fs = param_info['factors']
        dtype_key = f"{param_name}.dtype"
        if dtype_key in fs and param_type in ('aclTensor', 'aclTensorList'):
            valid = set(fs[dtype_key])
            for inv in sorted(ALL_DTYPES - valid)[:2]:
                case = _build_exception_base(factors)
                case[dtype_key] = inv
                case['_expected_error'] = 'ACL_ERROR_DTYPES_NOT_MATCH'
                case['_exception_type'] = 'unsupported_dtype'
                cases.append(case)
        fmt_key = f"{param_name}.format"
        if fmt_key in fs:
            valid = set(fs[fmt_key])
            invalid = sorted(ALL_FORMATS - valid)
            if invalid:
                case = _build_exception_base(factors)
                case[fmt_key] = invalid[0]
                case['_expected_error'] = 'ACL_ERROR_FORMAT_NOT_SUPPORT'
                case['_exception_type'] = 'unsupported_format'
                cases.append(case)
    return cases


def _generate_constraint_violation_cases(factors, engine):
    cases = []
    input_tensors = []
    output_tensors = []
    for pn, pi in factors.items():
        if not isinstance(pi, dict):
            continue
        if pi.get('type') in ('aclTensor', 'aclTensorList'):
            if pi.get('io_type') == 'input':
                input_tensors.append(pn)
            elif pi.get('io_type') == 'output':
                output_tensors.append(pn)

    dtype_rel = _analyze_dtype_relations(engine)

    if len(input_tensors) >= 2:
        for i in range(len(input_tensors)):
            for j in range(i + 1, len(input_tensors)):
                if dtype_rel.get((input_tensors[i], input_tensors[j])) == 'equal':
                    _add_dtype_mismatch_case(cases, factors, input_tensors[i], input_tensors[j], 'dtype_mismatch')

    if input_tensors and output_tensors:
        for in_t in input_tensors[:2]:
            for out_t in output_tensors[:2]:
                rel = dtype_rel.get((in_t, out_t), 'independent')
                if rel == 'equal':
                    _add_io_dtype_mismatch_case(cases, factors, in_t, out_t)
                elif rel == 'convertible':
                    _add_unconvertible_dtype_case(cases, factors, engine, in_t, out_t)

    for pn, pi in factors.items():
        if not isinstance(pi, dict):
            continue
        if pi.get('type') == 'aclTensor' and pi.get('io_type') == 'output':
            dk = f"{pn}.dimensions"
            dims = pi.get('factors', {}).get(dk, [2])
            for d in dims[:2]:
                case = _build_exception_base(factors)
                case[f"{pn}.shape"] = [999] * d
                case[f"{pn}.dimensions"] = d
                case['_expected_error'] = 'ACL_ERROR_SHAPE_NOT_MATCH'
                case['_exception_type'] = 'output_shape_mismatch'
                cases.append(case)
        if pi.get('type') == 'aclIntArray':
            case = _build_exception_base(factors)
            case[f"{pn}.value"] = [0, 0]
            case['_expected_error'] = 'ACL_ERROR_INVALID_PARAM'
            case['_exception_type'] = 'array_duplicate_elements'
            cases.append(case)
    return cases


def _analyze_dtype_relations(engine):
    relations = {}
    if engine is None or not hasattr(engine, 'constraints'):
        return relations
    for target, func_info in engine.constraints.items():
        if not target.endswith('.dtype'):
            continue
        sources = func_info['sources']
        func = func_info['function']
        target_param = target.rsplit('.dtype', 1)[0]
        for source in sources:
            if not source.endswith('.dtype') and source != 'dtype.value':
                continue
            source_param = source.rsplit('.dtype', 1)[0] if source.endswith('.dtype') else 'dtype'
            rel = _classify_dtype_relation(func)
            if rel != 'independent':
                relations[(source_param, target_param)] = rel
                relations[(target_param, source_param)] = rel
    return relations


def _classify_dtype_relation(func):
    try:
        source_code = inspect.getsource(func)
    except (OSError, TypeError):
        return 'independent'
    if 'get_convertible_source_dtypes' in source_code or 'Candidates' in source_code:
        return 'convertible'
    for line in source_code.split('\n'):
        stripped = line.strip()
        if stripped.startswith('return ') and 'Candidates' not in stripped:
            ret = stripped.replace('return ', '').strip()
            if ret and not ret.startswith(('SKIP', 'NOT_APPLICABLE', 'None')):
                return 'equal'
    return 'independent'


def _add_dtype_mismatch_case(cases, factors, pa, pb, exc_type):
    dka, dkb = f"{pa}.dtype", f"{pb}.dtype"
    da = factors[pa].get('factors', {}).get(dka, [])
    db = factors[pb].get('factors', {}).get(dkb, [])
    if da and db:
        diff = set(da) - set(db)
        if diff:
            case = _build_exception_base(factors)
            case[dka] = list(diff)[0]
            case[dkb] = db[0]
            case['_expected_error'] = 'ACL_ERROR_DTYPES_NOT_MATCH'
            case['_exception_type'] = exc_type
            cases.append(case)


def _add_io_dtype_mismatch_case(cases, factors, in_p, out_p):
    idk, odk = f"{in_p}.dtype", f"{out_p}.dtype"
    idt = factors[in_p].get('factors', {}).get(idk, [])
    odt = factors[out_p].get('factors', {}).get(odk, [])
    if idt and odt:
        mismatch = list(set(idt) - set(odt))
        if mismatch:
            case = _build_exception_base(factors)
            case[idk] = mismatch[0]
            case[odk] = odt[0]
            case['_expected_error'] = 'ACL_ERROR_DTYPES_NOT_MATCH'
            case['_exception_type'] = 'io_dtype_mismatch'
            cases.append(case)


def _add_unconvertible_dtype_case(cases, factors, engine, in_p, out_p):
    idk, odk = f"{in_p}.dtype", f"{out_p}.dtype"
    idt = factors[in_p].get('factors', {}).get(idk, [])
    odt = factors[out_p].get('factors', {}).get(odk, [])
    if not idt or not odt:
        return
    constraint = engine.constraints.get(odk)
    if constraint is None:
        return
    func = constraint['function']
    convertible = set()
    for dt in idt:
        try:
            result = func(dt)
            if isinstance(result, list):
                for r in result:
                    convertible.add((dt, r))
            elif isinstance(result, str):
                convertible.add((dt, result))
        except Exception:
            pass
    for idt_v in idt:
        for odt_v in odt:
            if (idt_v, odt_v) not in convertible and idt_v != odt_v:
                case = _build_exception_base(factors)
                case[idk] = idt_v
                case[odk] = odt_v
                case['_expected_error'] = 'ACL_ERROR_DTYPES_NOT_MATCH'
                case['_exception_type'] = 'io_dtype_mismatch'
                cases.append(case)
                return


def _generate_supplementary_exception_cases(factors):
    cases = []
    for pn, pi in factors.items():
        if not isinstance(pi, dict):
            continue
        if pi.get('type') in ('aclIntArray',):
            vk = f"{pn}.value"
            if vk in pi.get('factors', {}):
                case = _build_exception_base(factors)
                case[vk] = [999]
                case['_expected_error'] = 'ACL_ERROR_INVALID_PARAM'
                case['_exception_type'] = 'dim_value_out_of_range'
                cases.append(case)

    for pn, pi in factors.items():
        if not isinstance(pi, dict):
            continue
        ek = f"{pn}.exist"
        ev = pi.get('factors', {}).get(ek, [])
        if ev == [True]:
            case = _build_exception_base(factors)
            case[ek] = False
            case['_expected_error'] = 'ACL_ERROR_INVALID_PARAM'
            case['_exception_type'] = 'required_param_missing'
            cases.append(case)
            break

    array_params = [pn for pn, pi in factors.items()
                    if isinstance(pi, dict) and pi.get('type') in ARRAY_TYPES and pi.get('io_type') == 'input']
    if len(array_params) >= 2:
        case = _build_exception_base(factors)
        case[f"{array_params[0]}.length"] = 2
        case[f"{array_params[1]}.length"] = 5
        case['_expected_error'] = 'ACL_ERROR_INVALID_PARAM'
        case['_exception_type'] = 'array_length_mismatch'
        cases.append(case)

    format_dim_map = {'NCHW': 4, 'NHWC': 4, 'NC1HWC0': 5}
    for pn, pi in factors.items():
        if not isinstance(pi, dict):
            continue
        if pi.get('type') not in ('aclTensor', 'aclTensorList'):
            continue
        if pi.get('io_type') != 'input':
            continue
        fk = f"{pn}.format"
        dk = f"{pn}.dimensions"
        fv = pi.get('factors', {}).get(fk, [])
        dv = pi.get('factors', {}).get(dk, [])
        for fmt in fv:
            if fmt in format_dim_map:
                req_dim = format_dim_map[fmt]
                if isinstance(dv, list):
                    mismatch = [d for d in dv if d != req_dim]
                    if mismatch:
                        case = _build_exception_base(factors)
                        case[fk] = fmt
                        case[dk] = mismatch[0]
                        case['_expected_error'] = 'ACL_ERROR_FORMAT_NOT_SUPPORT'
                        case['_exception_type'] = 'dtype_format_incompatible'
                        cases.append(case)
                break
    return cases


def _build_exception_base(factors):
    base = {}
    for pn, pi in factors.items():
        if not isinstance(pi, dict) or 'factors' not in pi:
            continue
        for fn, vals in pi['factors'].items():
            if isinstance(vals, list) and vals:
                base[fn] = random.choice(vals)
    return base


def _deduplicate(cases):
    seen = set()
    unique = []
    for case in cases:
        key = tuple(sorted((k, str(v)) for k, v in case.items() if not k.startswith('_')))
        if key not in seen:
            seen.add(key)
            unique.append(case)
    return unique


# ==================== function 判定 ====================

def _determine_function(target, case):
    if target.category == 'exception':
        return 'exception'
    if target.category == 'boundary':
        return 'boundary'
    if target.category == 'infnan' or _has_infnan_in_case(case):
        return 'INFNAN'
    if _is_broadcast_case(case):
        return 'broadcast'
    return 'fuzz'


def _is_broadcast_case(case):
    shapes = {}
    for k, v in case.items():
        if not k.endswith('.shape') or v is None:
            continue
        if k.endswith('.shape_list'):
            continue
        pn = k.rsplit('.shape', 1)[0]
        ek = f"{pn}.exist"
        if ek in case and case[ek] is False:
            continue
        if isinstance(v, list):
            shapes[pn] = v
    vals = list(shapes.values())
    if len(vals) < 2:
        return False
    return not all(s == vals[0] for s in vals)


def _has_infnan_in_case(case):
    for k, v in case.items():
        if 'value_range' in k:
            s = str(v).lower()
            if 'inf' in s or 'nan' in s:
                return True
    return False



# ==================== TTK 格式转换（保留原有逻辑）====================

def _is_safe_na(val):
    if isinstance(val, (list, tuple, dict)):
        return False
    try:
        result = pd.isna(val)
        return bool(result) if not isinstance(result, (list, tuple, np.ndarray)) else False
    except (ValueError, TypeError):
        return False


def parse_list_value(value):
    """解析列表值"""
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


_EXCEPTION_LABELS = {
    'unsupported_dtype': 'dtype不在合法域',
    'unsupported_format': 'format不支持',
    'dtype_mismatch': '输入tensor dtype不匹配',
    'io_dtype_mismatch': '输入输出dtype不可转换',
    'output_shape_mismatch': '输出shape与期望不匹配',
    'array_duplicate_elements': '数组元素重复',
    'array_length_mismatch': '数组长度不匹配',
    'dim_boundary_underflow': '维度下溢',
    'dim_boundary_overflow': '维度上溢',
    'dim_value_out_of_range': '维度值越界',
    'required_param_missing': '必选参数缺失',
    'dtype_format_incompatible': 'dtype与format不兼容',
    'shape_boundary': 'shape边界异常',
    'constraint_violation': '约束违反',
    'enum_out_of_range': '枚举值越界',
    'empty_tensor': '空tensor不支持',
}


def _build_remark(row, param_names):
    exc_type = row.get('_exception_type', '')
    expected = row.get('_expected_error', '')
    sid = row.get('_scenario_id', '')

    parts = []
    if sid:
        parts.append(sid)

    label = _EXCEPTION_LABELS.get(exc_type, exc_type)
    parts.append(label)

    details = []
    for pn in param_names:
        for attr in ('dtype', 'format', 'shape', 'dimensions', 'value'):
            key = f"{pn}.{attr}"
            if key not in row.index:
                continue
            val = row.get(key)
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            details.append(f"{key}={val}")
    if details:
        parts.append('; '.join(details[:3]))

    if expected:
        parts.append(f"expect {expected}")

    return '; '.join(parts)


def convert_to_ttk_format(df, param_def, operator_name, case_level, csv_mode='aclnn'):
    """
    转换为TTK用例CSV格式
    
    Args:
        df: 因子值 DataFrame
        param_def: 参数定义（由 _build_param_def_from_factors 构建）
        operator_name: 算子名称
        case_level: 用例级别（L0/L1）
    
    Returns:
        DataFrame: TTK格式的用例表
    """
    cases = []
    
    _skip_keys = {'operator_name', 'aclnn_name', 'parameters'}
    param_names = [k for k in param_def.keys() if k not in _skip_keys]
    
    for idx, row in df.iterrows():
        case = {
            'testcase_name': f"{operator_name}_{case_level}_{idx+1:03d}",
            'api_name': operator_name,
            'tensor_view_shapes': '',
            'tensor_dtypes': '',
            'tensor_formats': '',
            'scalar_dtypes': '',
            'attributes': '',
            'output_tensor_indexes': '',
            'precision_tolerances': '',
            'absolute_precision': '',
            'input_data_ranges': '',
            'scalar_data_ranges': '',
        }
        
        input_shapes = []
        input_dtypes = []
        input_formats = []
        input_ranges = []
        output_shapes = []
        output_dtypes = []
        output_formats = []
        output_indexes = []
        in_place_positions = []
        scalar_dtypes_list = []
        scalar_ranges_list = []
        attrs_dict = {}
        
        for param_name, param_info in param_def.items():
            if param_name in _skip_keys or not isinstance(param_info, dict):
                continue
            io_type = param_info.get('io_type', 'input')
            param_type = param_info.get('type', '')
            exist_col = f"{param_name}.exist"
            is_absent = (exist_col in row.index and row[exist_col] == False)
            
            if param_type == 'aclTensor' and io_type == 'input':
                if is_absent:
                    input_shapes.append(None)
                    dtype = row.get(f"{param_name}.dtype")
                    if dtype is None or (isinstance(dtype, float) and pd.isna(dtype)):
                        p_info = param_def.get(param_name, {})
                        dtypes_list = [
                            d['dtype'] for d in p_info.get('dtype_with_values', [])
                        ] or [
                            d['dtype'] for d in p_info.get('dtype_with_ranges', [])
                        ]
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
                    in_place_positions.append(len(input_shapes) - 1)
            
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
                    raw_shape_list = row.get(f"{param_name}.shape_list", '[]')
                    if raw_shape_list is None or (isinstance(raw_shape_list, float) and pd.isna(raw_shape_list)):
                        raw_shape_list = '[]'
                    shape_list = parse_list_value(raw_shape_list)
                    if not isinstance(shape_list, list):
                        shape_list = []
                    dtype = row.get(f"{param_name}.dtype", 'float32')
                    if isinstance(dtype, float) and pd.isna(dtype):
                        dtype = 'float32'
                    dtype = normalize_dtype(dtype) or dtype
                    value_range = _resolve_value_range(row, param_name, dtype)
                    fmt = row.get(f"{param_name}.format", 'ND')
                    if isinstance(fmt, float) and pd.isna(fmt):
                        fmt = 'ND'
                    
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
                    in_place_positions.append(len(input_shapes) - 1)
            
            elif param_type == 'aclTensor' and io_type == 'output':
                actual_pos = len(input_shapes) + len(output_shapes)
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
                    output_indexes.append(actual_pos)
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
                    output_indexes.append(actual_pos)
            
            elif param_type == 'aclTensorList' and io_type == 'output':
                actual_pos = len(input_shapes) + len(output_shapes)
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
                    output_indexes.append(actual_pos)
                else:
                    shape_list = parse_list_value(row.get(f"{param_name}.shape_list", '[]'))
                    if not isinstance(shape_list, list) or len(shape_list) == 0:
                        shape_list = [[]]
                    dtype = row.get(f"{param_name}.dtype", 'float32')
                    if pd.isna(dtype):
                        dtype = 'float32'
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
                    output_indexes.append(actual_pos)
            
            elif param_type == 'aclScalar':
                dtype = row.get(f"{param_name}.dtype", 'float')
                if is_absent:
                    scalar_dtypes_list.append(None)
                else:
                    scalar_dtypes_list.append(dtype)
                    value = row.get(f"{param_name}.value", '')
                    if _is_valid_value(value):
                        attrs_dict[param_name] = format_ttk_attr_value(value, param_type)
            
            elif param_type in ['aclIntArray', 'aclFloatArray', 'aclBoolArray', 'aclScalarList']:
                if not is_absent:
                    value = row.get(f"{param_name}.value", '')
                    if isinstance(value, (list, tuple, np.ndarray)) and len(value) == 0:
                        attrs_dict[param_name] = []
                    elif _is_valid_value(value):
                        attrs_dict[param_name] = format_ttk_attr_value(value, param_type)
            
            elif param_type in ['int', 'int4_t', 'int8_t', 'int16_t', 'int32_t', 'int64_t',
                                'uint1_t', 'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t',
                                'int4', 'int8', 'int16', 'int32', 'int64',
                                'uint1', 'uint8', 'uint16', 'uint32', 'uint64',
                                'float', 'double', 'float16', 'bfloat16', 'float32', 'bool', 'char', 'char*', 'string']:
                if not is_absent:
                    value = row.get(f"{param_name}.value", '')
                    if _is_valid_value(value):
                        attrs_dict[param_name] = format_ttk_attr_value(value, param_type)
            
            elif param_type == 'aclDataType':
                if not is_absent:
                    value = row.get(f"{param_name}.value", '')
                    if _is_valid_value(value):
                        normalized = normalize_dtype(str(value))
                        if normalized and normalized in ACL_DTYPE_ENUM_MAP:
                            attrs_dict[param_name] = ACL_DTYPE_ENUM_MAP[normalized]
                        else:
                            attrs_dict[param_name] = format_ttk_attr_value(value, param_type)
        
        all_tensor_shapes = input_shapes + output_shapes
        all_tensor_dtypes = input_dtypes + output_dtypes
        all_tensor_formats = input_formats + output_formats
        case['tensor_view_shapes'] = format_ttk_tuple(all_tensor_shapes)
        case['tensor_dtypes'] = format_ttk_tuple_str(all_tensor_dtypes)
        case['tensor_formats'] = format_ttk_tuple_str(all_tensor_formats)
        
        if scalar_dtypes_list:
            case['scalar_dtypes'] = format_ttk_tuple_str(scalar_dtypes_list)
        
        if attrs_dict:
            case['attributes'] = format_ttk_dict(attrs_dict)
        
        all_output_positions = sorted(set(output_indexes + in_place_positions))
        if all_output_positions:
            case['output_tensor_indexes'] = format_ttk_tuple(all_output_positions)
        
        if input_ranges:
            case['input_data_ranges'] = format_ttk_tuple(input_ranges)
        
        if scalar_ranges_list:
            case['scalar_data_ranges'] = format_ttk_tuple(scalar_ranges_list)
        
        if case_level == 'L2' and row.get('_exception_type'):
            case['remark'] = _build_remark(row, param_names)
        else:
            case['remark'] = ''
        
        cases.append(case)
    
    if csv_mode == 'kernel':
        # Kernel mode: 26 columns
        for case in cases:
            case['op_name'] = operator_name
            case['tensor_storage_shapes'] = ''
            case['tensor_view_offsets'] = ''
            case['tensor_view_strides'] = ''
            case['input_ori_shapes'] = case.get('tensor_view_shapes', '')
            case['output_ori_shapes'] = ''
            case['output_shapes'] = ''
            case['output_storage_shapes'] = ''
            case['output_view_offsets'] = ''
            case['output_view_strides'] = ''
            case['golden_api'] = ''
            case['is_enabled'] = True
            case['remark'] = ''
            case['soc_series'] = ''
            case['priority'] = 0
            case['network_name'] = ''
            case.pop('scalar_dtypes', None)
            case.pop('scalar_data_ranges', None)
            case.pop('api_name', None)
        columns = [
            'testcase_name', 'op_name', 'tensor_view_shapes', 'tensor_dtypes',
            'tensor_formats', 'tensor_storage_shapes', 'tensor_view_offsets',
            'tensor_view_strides', 'output_tensor_indexes', 'attributes',
            'golden_api', 'input_data_ranges', 'precision_tolerances',
            'absolute_precision', 'is_enabled', 'remark', 'soc_series',
            'priority', 'network_name', 'input_ori_shapes', 'output_ori_shapes',
            'output_shapes', 'output_storage_shapes', 'output_view_offsets',
            'output_view_strides'
        ]
    else:
        # ACLNN mode: 13 columns
        columns = [
            'testcase_name', 'api_name', 'tensor_view_shapes', 'tensor_dtypes',
            'tensor_formats',
            'scalar_dtypes', 'attributes', 'output_tensor_indexes',
            'precision_tolerances', 'absolute_precision', 'input_data_ranges',
            'scalar_data_ranges', 'remark'
        ]

    return pd.DataFrame(cases)[columns]


# ==================== TTK 用例自检与修复 ====================

def _preprocess_ranges_for_eval(s):
    s = s.replace('float("inf")', '999.0')
    s = s.replace('float("-inf")', '-999.0')
    s = s.replace('float("nan")', '0.0')
    s = s.replace('inf', '999.0')
    s = s.replace('-inf', '-999.0')
    s = s.replace('nan', '0.0')
    return s


def validate_ttk_cases(df, verbose=False):
    valid_mask = pd.Series([True] * len(df), index=df.index)
    detail_counts = {}

    checks = {
        'tensor_view_shapes': ['nan'],
        'tensor_dtypes': ['nan', 'None'],
        'tensor_formats': ['nan', 'None'],
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

    # 长度一致性校验: shapes/dtypes/formats 逐组对齐, data_ranges 与输入 shapes 对齐
    required_cols = ['tensor_view_shapes', 'tensor_dtypes', 'tensor_formats']
    if all(c in df.columns for c in required_cols):
        for row_idx, row in df.iterrows():
            if not valid_mask.loc[row_idx]:
                continue
            try:
                shapes_groups = literal_eval(str(row['tensor_view_shapes']))
                dtypes_groups = literal_eval(str(row['tensor_dtypes']))
                formats_groups = literal_eval(str(row['tensor_formats']))
            except Exception:
                detail_counts['tensor字段解析失败'] = detail_counts.get('tensor字段解析失败', 0) + 1
                valid_mask[row_idx] = False
                continue

            if not (isinstance(shapes_groups, tuple) and isinstance(dtypes_groups, tuple)
                    and isinstance(formats_groups, tuple)):
                detail_counts['tensor字段非tuple'] = detail_counts.get('tensor字段非tuple', 0) + 1
                valid_mask[row_idx] = False
                continue

            if not (len(shapes_groups) == len(dtypes_groups) == len(formats_groups)):
                detail_counts['tensor组数不一致'] = detail_counts.get('tensor组数不一致', 0) + 1
                valid_mask[row_idx] = False
                continue

            mismatch = False
            for gi in range(len(shapes_groups)):
                d = dtypes_groups[gi]
                s = shapes_groups[gi]
                if isinstance(d, str) or s is None:
                    continue
                s_len = len(s)
                d_len = len(d)
                f = formats_groups[gi]
                f_len = len(f) if isinstance(f, (list, tuple)) else 1
                if not (s_len == d_len == f_len):
                    detail_counts[f'组{gi}长度不一致(shape={s_len},dtype={d_len},fmt={f_len})'] = \
                        detail_counts.get(f'组{gi}长度不一致(shape={s_len},dtype={d_len},fmt={f_len})', 0) + 1
                    mismatch = True
            if mismatch:
                valid_mask[row_idx] = False
                continue

            output_idx_str = str(row.get('output_tensor_indexes', ''))
            if output_idx_str and output_idx_str not in ('', 'nan', 'None', '()'):
                try:
                    output_indices = literal_eval(output_idx_str)
                except Exception:
                    output_indices = []
                if output_indices:
                    max_idx = max(output_indices)
                    if max_idx >= len(shapes_groups):
                        detail_counts[f'output_tensor_indexes越界({max_idx}>={len(shapes_groups)})'] = \
                            detail_counts.get(f'output_tensor_indexes越界({max_idx}>={len(shapes_groups)})', 0) + 1
                        valid_mask[row_idx] = False
                        continue

            ranges_str = str(row.get('input_data_ranges', ''))
            if ranges_str and ranges_str not in ('', 'nan', 'None', '()'):
                try:
                    ranges_groups = literal_eval(_preprocess_ranges_for_eval(ranges_str))
                except Exception:
                    detail_counts['input_data_ranges解析失败'] = detail_counts.get('input_data_ranges解析失败', 0) + 1
                    valid_mask[row_idx] = False
                    continue
                if len(ranges_groups) > len(shapes_groups):
                    detail_counts[f'data_ranges组数({len(ranges_groups)})>shapes总组数({len(shapes_groups)})'] = \
                        detail_counts.get(f'data_ranges组数({len(ranges_groups)})>shapes总组数({len(shapes_groups)})', 0) + 1
                    valid_mask[row_idx] = False
                    continue
                num_input = len(ranges_groups)
                range_mismatch = False
                for gi in range(num_input):
                    r = ranges_groups[gi]
                    s = shapes_groups[gi]
                    if not isinstance(r, (list, tuple)) or isinstance(r, str) or s is None:
                        continue
                    d = dtypes_groups[gi] if gi < len(dtypes_groups) else None
                    if isinstance(d, str):
                        continue
                    r_len = len(r)
                    s_len = len(s)
                    if r_len != s_len:
                        detail_counts[f'输入组{gi}data_ranges长度({r_len})!=shapes长度({s_len})'] = \
                            detail_counts.get(f'输入组{gi}data_ranges长度({r_len})!=shapes长度({s_len})', 0) + 1
                        range_mismatch = True
                if range_mismatch:
                    valid_mask[row_idx] = False

    valid_df = df[valid_mask].reset_index(drop=True)
    invalid_count = int((~valid_mask).sum())
    details = ', '.join(f'{k}:{v}' for k, v in detail_counts.items()) if detail_counts else ''

    if verbose and invalid_count > 0:
        print(f"[WARN] 自检发现 {invalid_count} 条无效用例，详情: {details}")

    return valid_df, invalid_count, details


def repair_invalid_cases(engine, factors, param_def, operator_name, level,
                         dropped_count, base_seed, verbose=False):
    if dropped_count <= 0 or engine is None:
        return pd.DataFrame()

    key_anchors = {}
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

    repaired_df = _convert_cases_to_ttk(repaired, param_def, operator_name, level)
    repaired_df, invalid_count, _ = validate_ttk_cases(repaired_df, verbose=False)
    if verbose and invalid_count > 0:
        print(f"[WARN] 修复用例中 {invalid_count} 条仍不合法，已丢弃")

    if len(repaired_df) > 1:
        feature_cols = ['tensor_view_shapes', 'tensor_dtypes', 'tensor_formats', 'attributes']
        if all(c in repaired_df.columns for c in feature_cols):
            features = repaired_df[feature_cols].astype(str).agg('|'.join, axis=1)
            if features.nunique() == 1:
                if verbose:
                    print(f"[WARN] 修复用例多样性不足：{len(repaired_df)}条修复用例的tensor字段完全相同")
                return pd.DataFrame()

    return repaired_df


def ttk_self_check_and_repair(case_df, engine, factors, param_def,
                               operator_name, level, seed=None, verbose=False,
                               csv_mode='aclnn'):
    max_rounds = 3
    for round_idx in range(max_rounds):
        valid_df, invalid_count, details = validate_ttk_cases(case_df, verbose)

        if invalid_count == 0:
            if verbose:
                print(f"[INFO] 用例自检通过，无需修复 (round {round_idx + 1})")
            return valid_df

        if verbose:
            print(f"[WARN] 自检发现 {invalid_count} 条无效用例，"
                  f"详情: {details} (round {round_idx + 1}/{max_rounds})")

        base_seed = (seed or 0) + round_idx * 1000
        repaired_df = repair_invalid_cases(
            engine, factors, param_def, operator_name, level,
            invalid_count, base_seed, verbose=verbose,
        )

        if len(repaired_df) > 0:
            case_df = pd.concat([valid_df, repaired_df], ignore_index=True)
        else:
            case_df = valid_df
    else:
        case_df, final_invalid, _ = validate_ttk_cases(case_df, verbose=False)
        if verbose:
            print(f"[WARN] 自检修复达上限，保留 {len(case_df)} 条合法用例")

    return case_df


def _format_number(x):
    if isinstance(x, float):
        if x == float('inf'):
            return 'inf'
        elif x == float('-inf'):
            return '-inf'
        elif x != x:
            return 'nan'
    elif isinstance(x, str):
        if x == 'inf':
            return 'inf'
        elif x == '-inf':
            return '-inf'
        elif x == 'nan':
            return 'nan'
    return str(x)


def format_ttk_tuple(items):
    """格式化TTK元组格式（递归，支持 None、嵌套子元组、特殊浮点值）"""
    if not items:
        return "()"
    formatted = []
    for item in items:
        if item is None:
            formatted.append("None")
        elif isinstance(item, (list, tuple)):
            formatted.append(format_ttk_tuple(item))
        else:
            formatted.append(_format_number(item))
    return f"({','.join(formatted)},)"


def format_ttk_tuple_str(items):
    """格式化字符串元组（支持嵌套子元组、None占位）"""
    if not items:
        return ""
    formatted = []
    for item in items:
        if item is None:
            formatted.append("None")
        elif isinstance(item, (list, tuple)):
            inner = ",".join(f"'{x}'" for x in item)
            formatted.append(f"({inner},)")
        else:
            formatted.append(f"'{item}'")
    return f"({','.join(formatted)},)"


def _python_literal_value(v):
    if v is None:
        return 'None'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int,)):
        return str(v)
    if isinstance(v, float):
        if v == float('inf'):
            return 'inf'
        elif v == float('-inf'):
            return '-inf'
        elif v != v:
            return 'nan'
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


def format_ttk_dict(d):
    """格式化字典为 JSON 兼容字符串"""
    if not d:
        return ""
    items = ",".join(f'"{k}":{_python_literal_value(v)}' for k, v in d.items())
    return "{" + items + "}"


def format_ttk_attr_value(value, param_type):
    """格式化TTK属性值"""
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

if __name__ == '__main__':
    main()
