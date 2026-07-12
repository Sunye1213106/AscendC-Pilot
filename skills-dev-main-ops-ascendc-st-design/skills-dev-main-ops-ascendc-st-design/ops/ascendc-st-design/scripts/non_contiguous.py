#!/usr/bin/env python3
"""
非连续 Tensor 参数注入模块（简约版）

在连续用例 CSV 生成后，作为后处理步骤为每个用例注入非连续 Tensor 参数。
支持 4 种非连续场景：transpose, broadcast, slice, asstrided
每个支持非连续的 tensor 对每种适用场景各生成一条用例。
4 种场景使用不同的 shape（不同维度/不同值），确保覆盖多样性。
support_non_contiguous 由参数清洗步骤从 MD 文档自动识别，写入 YAML。
"""

from ast import literal_eval
from typing import List, Dict, Any, Optional, Set
import pandas as pd
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import generate_random_shape

SCENES = ['transpose', 'broadcast', 'slice', 'asstrided']

NC_ACLNN_COLUMNS = [
    'testcase_name', 'api_name', 'tensor_view_shapes', 'tensor_dtypes',
    'tensor_formats', 'tensor_stroage_shapes', 'tensor_view_offsets',
    'tensor_view_strides', 'scalar_dtypes', 'attributes',
    'output_tensor_indexes', 'precision_tolerances', 'absolute_precision',
    'input_data_ranges', 'scalar_data_ranges', 'remark'
]

_SCENE_REP_DIMS = {
    'transpose': 2,
    'broadcast': 1,
    'slice': 3,
    'asstrided': 4,
}


def _pick_scene_dim(scene, dims_list):
    min_dim = 2 if scene == 'transpose' else 1
    pref_dim = _SCENE_REP_DIMS.get(scene, 2)
    valid_dims = [d for d in dims_list if d >= min_dim]
    if not valid_dims:
        return max(dims_list) if dims_list else min_dim
    if pref_dim in valid_dims:
        return pref_dim
    closest = min(valid_dims, key=lambda d: abs(d - pref_dim))
    return closest


def _compute_continuous_strides(view_shape: List[int]) -> List[int]:
    strides = []
    stride = 1
    for dim in reversed(view_shape):
        strides.insert(0, stride)
        stride *= dim
    return strides


def generate_continuous_params(view_shape: List[int]) -> Dict[str, Any]:
    return {
        'storage_shape': list(view_shape),
        'offset': 0,
        'strides': _compute_continuous_strides(view_shape),
    }


def generate_transpose_params(view_shape: List[int]) -> Optional[Dict[str, Any]]:
    if len(view_shape) < 2:
        return None
    storage_shape = list(view_shape[::-1])
    storage_strides = _compute_continuous_strides(storage_shape)
    view_strides = list(storage_strides[::-1])
    return {
        'storage_shape': storage_shape,
        'offset': 0,
        'strides': view_strides,
    }


def generate_broadcast_params(view_shape: List[int]) -> Dict[str, Any]:
    return {
        'storage_shape': [1],
        'offset': 0,
        'strides': [0] * len(view_shape),
    }


def generate_slice_params(view_shape: List[int]) -> Optional[Dict[str, Any]]:
    if len(view_shape) == 0:
        return None
    axis = 0
    start = 2
    step = 2
    storage_shape = list(view_shape)
    required_size = start + view_shape[axis] * step
    storage_shape[axis] = required_size + 10
    strides = _compute_continuous_strides(storage_shape)
    strides[axis] *= step
    offset = start * strides[axis] // step
    return {
        'storage_shape': storage_shape,
        'offset': offset,
        'strides': strides,
    }


def generate_asstrided_params(view_shape: List[int]) -> Dict[str, Any]:
    if len(view_shape) == 0:
        return generate_broadcast_params(view_shape)
    if len(view_shape) == 1:
        strides = [2]
        max_index = (view_shape[0] - 1) * strides[0]
        storage_size = max_index + 20
        return {
            'storage_shape': [storage_size],
            'offset': 0,
            'strides': strides,
        }
    contiguous_strides = _compute_continuous_strides(view_shape)
    strides = [s * 2 for s in contiguous_strides[:-1]] + [1]
    max_index = sum((d - 1) * s for d, s in zip(view_shape, strides))
    storage_size = max_index + 20
    return {
        'storage_shape': [storage_size],
        'offset': 0,
        'strides': strides,
    }


def _scene_applicable(scene: str, view_shape: List[int]) -> bool:
    if len(view_shape) == 0:
        return False
    if scene == 'transpose' and len(view_shape) < 2:
        return False
    if scene == 'slice' and len(view_shape) == 0:
        return False
    return True


def _Get_shape_constraint(shape_constraints, nc_idx, companion_idx):
    if not shape_constraints:
        return 'independent'
    key = (nc_idx, companion_idx)
    if key in shape_constraints:
        return shape_constraints[key]
    key = (companion_idx, nc_idx)
    if key in shape_constraints:
        return shape_constraints[key]
    return 'independent'


def _Derive_broadcast_compatible_shape(nc_shape, seed=None):
    import random as _rng
    if seed is not None:
        _rng.seed(seed)
    out_shape = list(nc_shape)
    extra_dims = _rng.randint(0, min(2, 8 - len(out_shape)))
    if extra_dims > 0:
        out_shape = [_rng.randint(1, 4) for _ in range(extra_dims)] + out_shape
    else:
        multiplier = _rng.randint(2, 4)
        out_shape = [multiplier] + out_shape
    return out_shape


def _cap_shape_product(shape, max_product):
    prod = 1
    for d in shape:
        prod *= d
    if prod <= max_product:
        return list(shape)
    max_idx = max(range(len(shape)), key=lambda i: shape[i])
    other_prod = 1
    for i, d in enumerate(shape):
        if i != max_idx:
            other_prod *= d
    if other_prod == 0:
        return list(shape)
    capped = list(shape)
    capped[max_idx] = max(1, max_product // other_prod)
    prod2 = 1
    for d in capped:
        prod2 *= d
    if prod2 > max_product:
        second_idx = max(range(len(capped)), key=lambda i: capped[i] if i != max_idx else -1)
        second_other = 1
        for i, d in enumerate(capped):
            if i != second_idx:
                second_other *= d
        if second_other > 0:
            capped[second_idx] = max(1, max_product // second_other)
    return capped


def _apply_scene(scene: str, view_shape: List[int]) -> tuple:
    actual_scene = scene
    if scene == 'transpose':
        params = generate_transpose_params(view_shape)
        if params is None:
            params = generate_asstrided_params(view_shape)
            actual_scene = 'asstrided'
    elif scene == 'broadcast':
        params = generate_broadcast_params(view_shape)
    elif scene == 'slice':
        params = generate_slice_params(view_shape)
        if params is None:
            params = generate_asstrided_params(view_shape)
            actual_scene = 'asstrided'
    else:
        params = generate_asstrided_params(view_shape)
    return params, actual_scene


def _format_tuple(values) -> str:
    if not values:
        return "()"
    return "(" + ",".join(str(v) for v in values) + ",)"


def _format_nested_tuple(lists) -> str:
    if not lists:
        return "()"
    inner = ",".join(_format_tuple(lst) for lst in lists)
    return "(" + inner + ",)"


def _parse_tensor_shapes(shapes_str: str) -> list:
    try:
        parsed = literal_eval(str(shapes_str))
    except (ValueError, SyntaxError):
        return []
    if not isinstance(parsed, tuple):
        return []
    result = []
    for item in parsed:
        if item is None:
            result.append(None)
        elif isinstance(item, tuple):
            if item and isinstance(item[0], tuple):
                result.append([list(sub) for sub in item])
            else:
                result.append(list(item))
        else:
            result.append(None)
    return result


def _parse_output_indexes(indexes_str: str) -> Set[int]:
    try:
        parsed = literal_eval(str(indexes_str))
    except (ValueError, SyntaxError):
        return set()
    if isinstance(parsed, (list, tuple)):
        return set(int(x) for x in parsed)
    return set()


def _build_tensor_param_map(param_def: dict) -> list:
    input_tensors = []
    output_tensors = []
    skip_keys = {'operator_name', 'aclnn_name', 'parameters'}
    for param_name, param_info in param_def.items():
        if param_name in skip_keys or not isinstance(param_info, dict):
            continue
        param_type = param_info.get('type', '')
        if param_type not in ('aclTensor', 'aclTensorList'):
            continue
        io_type = param_info.get('io_type', 'input')
        support_nc = param_info.get('support_non_contiguous', True)
        entry = {
            'name': param_name,
            'is_output': io_type == 'output',
            'support_non_contiguous': support_nc,
            'type': param_type,
        }
        if io_type == 'input':
            input_tensors.append(entry)
        else:
            output_tensors.append(entry)
    return input_tensors + output_tensors


def _is_tensorlist_shape(shape) -> bool:
    return isinstance(shape, list) and shape and isinstance(shape[0], list)


def _compute_continuous_strides_for_entry(shape) -> Any:
    if _is_tensorlist_shape(shape):
        return [_compute_continuous_strides(sub) for sub in shape]
    return _compute_continuous_strides(shape)


def _compute_storage_shape_for_continuous_entry(shape) -> Any:
    if _is_tensorlist_shape(shape):
        return [list(sub) for sub in shape]
    return list(shape)


def has_nc_support(param_def: dict) -> bool:
    skip_keys = {'operator_name', 'aclnn_name', 'parameters'}
    for param_name, param_info in param_def.items():
        if param_name in skip_keys or not isinstance(param_info, dict):
            continue
        if param_info.get('support_non_contiguous', True) and param_info.get('type') in ('aclTensor', 'aclTensorList'):
            return True
    return False


def add_continuous_nc_columns(case_df, param_def):
    """为 DataFrame 添加 3 列 NC 参数列，连续用例行留空。"""
    case_df['tensor_stroage_shapes'] = ''
    case_df['tensor_view_offsets'] = ''
    case_df['tensor_view_strides'] = ''

    cols = list(case_df.columns)
    new_cols = []
    for c in NC_ACLNN_COLUMNS:
        if c in cols:
            new_cols.append(c)
    for c in cols:
        if c not in new_cols:
            new_cols.append(c)
    case_df = case_df[new_cols]

    return case_df


def _select_diverse_dtype_rows(case_df, param_def, num_needed, verbose=False):
    """
    从 L1 DataFrame 中选取具有不同 dtype 组合的行，确保 NC 用例 dtype 多样性。

    优先选取满足 NC shape 要求（所有 NC-supporting tensor 有 ≥2 维）的行，
    然后按 dtype 组合去重，选取 num_needed 条不同 dtype 组合的行。
    如果不同 dtype 组合不足 num_needed 种，则循环复用已有的行。

    Args:
        case_df: L1 全量用例 DataFrame
        param_def: 参数定义
        num_needed: 需要的不同 dtype 组合数量
        verbose: 是否打印进度信息

    Returns:
        list of dict，每个 dict 是一行用例数据
    """
    tensor_params = _build_tensor_param_map(param_def)
    nc_indices = [i for i, tp in enumerate(tensor_params) if tp['support_non_contiguous']]

    nc_valid_rows = []
    for idx, row in case_df.iterrows():
        shapes_str = str(row.get('tensor_view_shapes', ''))
        shapes = _parse_tensor_shapes(shapes_str)
        if not shapes:
            continue
        num_expected = len(tensor_params)
        if len(shapes) > num_expected:
            shapes = shapes[:num_expected]
        elif len(shapes) < num_expected:
            shapes.extend([None] * (num_expected - len(shapes)))
        all_nc_valid = True
        for t_idx in nc_indices:
            s = shapes[t_idx]
            if s is None or _is_tensorlist_shape(s) or len(s) < 2:
                all_nc_valid = False
                break
        if all_nc_valid:
            nc_valid_rows.append(row)

    dtype_cols = ['tensor_dtypes', 'scalar_dtypes']
    seen_combos = set()
    diverse = []
    for row in nc_valid_rows:
        combo_key = tuple(str(row.get(c, '')) for c in dtype_cols)
        if combo_key not in seen_combos:
            seen_combos.add(combo_key)
            diverse.append(row)

    if verbose:
        print(f"[INFO] dtype 多样性选取: {len(nc_valid_rows)} 条 NC-valid 行, "
              f"{len(diverse)} 种不同 dtype 组合, 需要 {num_needed} 条")

    if len(diverse) >= num_needed:
        return [dict(diverse[i]) for i in range(num_needed)]

    if len(diverse) == 0:
        fallback_rows = []
        for idx, row in case_df.iterrows():
            fallback_rows.append(row)
            if len(fallback_rows) >= num_needed:
                break
        if not fallback_rows:
            return [dict(case_df.iloc[0]) for _ in range(num_needed)]
        return [dict(fallback_rows[i % len(fallback_rows)]) for i in range(num_needed)]

    result = []
    for i in range(num_needed):
        result.append(dict(diverse[i % len(diverse)]))
    return result


def inject_non_contiguous_params(case_df, param_def, operator_name, level,
                                 shape_constraints=None, verbose=False):
    """
    基于 L1 用例 DataFrame，为每个 NC-supporting tensor 独立生成 4 场景全覆盖 NC 用例。

    不基于 L1 用例行展开（避免数据爆炸），而是为每个 support_non_contiguous=true
    的 tensor 参数独立生成 transpose/broadcast/slice/asstrided 四种场景用例。
    每个NC用例中只有目标tensor是非连续的，其他tensor保持连续。
    4 种场景使用不同的 shape（不同维度/不同值），确保覆盖多样性。
    每条 NC 用例从 L1 DataFrame 中选取不同 dtype 组合的行作为模板，确保 dtype 多样性。

    Args:
        case_df: L1 全量用例 DataFrame（16列，含连续NC参数）
        param_def: 参数定义（含 support_non_contiguous，由参数清洗步骤从 MD 自动识别）
        operator_name: 算子名称
        level: L0/L1/L2
        verbose: 是否打印进度信息

    Returns:
        16 列 DataFrame，或 None（无 tensor 支持非连续时）
    """
    tensor_params = _build_tensor_param_map(param_def)
    nc_indices = [i for i, tp in enumerate(tensor_params) if tp['support_non_contiguous']]

    if not nc_indices:
        if verbose:
            print("[INFO] 无 tensor 支持非连续，跳过")
        return None

    num_expected = len(tensor_params)
    num_nc_cases = len(nc_indices) * len(SCENES)
    diverse_rows = _select_diverse_dtype_rows(case_df, param_def, num_nc_cases, verbose)

    rows = []
    scene_stats = {}
    case_counter = 0

    op_hash = hash(operator_name) % 10000

    def _is_tensorlist_param(idx):
        return tensor_params[idx]['type'] == 'aclTensorList'

    def _get_tensorlist_length(idx, row_data):
        dtypes_str = str(row_data.get('tensor_dtypes', ''))
        try:
            parsed = literal_eval(dtypes_str)
            if isinstance(parsed, tuple) and idx < len(parsed):
                inner = parsed[idx]
                if isinstance(inner, tuple):
                    return len(inner)
        except Exception:
            pass
        return 1

    for t_idx in nc_indices:
        tp = tensor_params[t_idx]
        param_name = tp['name']
        param_info = param_def.get(param_name, {})
        dims_list = param_info.get('dimensions', [2])
        if not dims_list or not isinstance(dims_list, list):
            dims_list = [2]

        for scene_idx, scene in enumerate(SCENES):
            scene_dim = _pick_scene_dim(scene, dims_list)
            seed_val = op_hash + t_idx * 100 + scene_idx * 7
            nc_shape = generate_random_shape(scene_dim, seed=seed_val)

            if not _scene_applicable(scene, nc_shape):
                continue

            row_data = diverse_rows[case_counter % len(diverse_rows)]

            is_nc_tensorlist = _is_tensorlist_param(t_idx)
            nc_list_len = _get_tensorlist_length(t_idx, row_data) if is_nc_tensorlist else 1

            all_shapes = []
            all_storage_shapes = []
            all_offsets = []
            all_strides = []
            applied_scene = scene

            for i in range(num_expected):
                comp_tp = tensor_params[i]
                comp_param_name = comp_tp['name']
                comp_is_tensorlist = _is_tensorlist_param(i)
                comp_list_len = _get_tensorlist_length(i, row_data) if comp_is_tensorlist else 1

                if i == t_idx:
                    if is_nc_tensorlist:
                        shape_list_i = []
                        storage_list_i = []
                        offset_list_i = []
                        stride_list_i = []
                        for j in range(nc_list_len):
                            sub_seed = seed_val + j * 7
                            sub_shape = generate_random_shape(scene_dim, seed=sub_seed)
                            if not _scene_applicable(scene, sub_shape):
                                sub_shape = list(nc_shape)
                            params, actual_scene = _apply_scene(scene, sub_shape)
                            applied_scene = actual_scene
                            shape_list_i.append(sub_shape)
                            storage_list_i.append(params['storage_shape'])
                            offset_list_i.append(params['offset'])
                            stride_list_i.append(params['strides'])
                        all_shapes.append(shape_list_i)
                        all_storage_shapes.append(storage_list_i)
                        all_offsets.append(offset_list_i)
                        all_strides.append(stride_list_i)
                    else:
                        params, applied_scene = _apply_scene(scene, nc_shape)
                        all_shapes.append(nc_shape)
                        all_storage_shapes.append(params['storage_shape'])
                        all_offsets.append(params['offset'])
                        all_strides.append(params['strides'])
                else:
                    constraint = _Get_shape_constraint(shape_constraints, t_idx, i)
                    if comp_is_tensorlist:
                        if constraint == 'equal':
                            companion_shapes = [list(nc_shape) for _ in range(comp_list_len)]
                        elif constraint == 'broadcast_compatible':
                            bc_shape = _Derive_broadcast_compatible_shape(nc_shape, seed=op_hash + i * 100 + scene_idx * 7)
                            companion_shapes = [bc_shape for _ in range(comp_list_len)]
                        else:
                            comp_param_info = param_def.get(comp_param_name, {})
                            comp_dims_list = comp_param_info.get('dimensions', [2])
                            if not comp_dims_list or not isinstance(comp_dims_list, list):
                                comp_dims_list = [2]
                            comp_min_dim = 1
                            valid_for_scene = [d for d in comp_dims_list if d >= comp_min_dim]
                            if scene_dim in valid_for_scene:
                                comp_seed = op_hash + i * 200 + scene_idx * 10 + 3
                                base_comp_shape = generate_random_shape(scene_dim, seed=comp_seed)
                            else:
                                if not valid_for_scene:
                                    valid_for_scene = comp_dims_list
                                comp_dim = valid_for_scene[0] if valid_for_scene else 2
                                comp_seed = op_hash + i * 200 + scene_idx * 10 + 3
                                base_comp_shape = generate_random_shape(comp_dim, seed=comp_seed)
                            companion_shapes = []
                            for j in range(comp_list_len):
                                sub_seed = comp_seed + j * 3
                                companion_shapes.append(generate_random_shape(len(base_comp_shape), seed=sub_seed))
                        comp_storage_list = []
                        comp_offset_list = []
                        comp_stride_list = []
                        for s in companion_shapes:
                            cont_params = generate_continuous_params(s)
                            comp_storage_list.append(cont_params['storage_shape'])
                            comp_offset_list.append(cont_params['offset'])
                            comp_stride_list.append(cont_params['strides'])
                        all_shapes.append(companion_shapes)
                        all_storage_shapes.append(comp_storage_list)
                        all_offsets.append(comp_offset_list)
                        all_strides.append(comp_stride_list)
                    else:
                        if constraint == 'equal':
                            comp_shape = list(nc_shape)
                        elif constraint == 'broadcast_compatible':
                            comp_shape = _Derive_broadcast_compatible_shape(nc_shape, seed=op_hash + i * 100 + scene_idx * 7)
                        else:
                            comp_param_info = param_def.get(comp_param_name, {})
                            comp_dims_list = comp_param_info.get('dimensions', [2])
                            if not comp_dims_list or not isinstance(comp_dims_list, list):
                                comp_dims_list = [2]
                            comp_min_dim = 1
                            valid_for_scene = [d for d in comp_dims_list if d >= comp_min_dim]
                            if scene_dim in valid_for_scene:
                                comp_seed = op_hash + i * 200 + scene_idx * 10 + 3
                                comp_shape = generate_random_shape(scene_dim, seed=comp_seed)
                            else:
                                if not valid_for_scene:
                                    valid_for_scene = comp_dims_list
                                comp_dim = valid_for_scene[0] if valid_for_scene else 2
                                comp_seed = op_hash + i * 200 + scene_idx * 10 + 3
                                comp_shape = generate_random_shape(comp_dim, seed=comp_seed)
                        cont_params = generate_continuous_params(comp_shape)
                        all_shapes.append(comp_shape)
                        all_storage_shapes.append(cont_params['storage_shape'])
                        all_offsets.append(cont_params['offset'])
                        all_strides.append(cont_params['strides'])

            _DTYPE_BYTES = {
                'float32': 4, 'float16': 2, 'bfloat16': 2,
                'int8': 1, 'int16': 2, 'int32': 4, 'int64': 8,
                'uint8': 1, 'uint16': 2, 'uint32': 4, 'uint64': 8,
                'bool': 1, 'double': 8, 'complex64': 8, 'complex128': 16,
            }
            max_dtype_bytes = 4
            try:
                dtypes_parsed = literal_eval(str(row_data.get('tensor_dtypes', '')))
                if isinstance(dtypes_parsed, tuple):
                    flat = []
                    for item in dtypes_parsed:
                        if isinstance(item, tuple):
                            flat.extend(item)
                        else:
                            flat.append(item)
                    for d in flat:
                        b = _DTYPE_BYTES.get(d, 4)
                        if b > max_dtype_bytes:
                            max_dtype_bytes = b
            except Exception:
                pass
            MAX_DATA_BYTES = 2 * 1024 * 1024 * 1024
            MAX_TOTAL_SIZE = MAX_DATA_BYTES // max_dtype_bytes
            total_tensor_count = 0
            for i in range(num_expected):
                if _is_tensorlist_param(i):
                    total_tensor_count += len(all_shapes[i])
                else:
                    total_tensor_count += 1
            budget_per_tensor = MAX_TOTAL_SIZE // total_tensor_count if total_tensor_count > 0 else MAX_TOTAL_SIZE
            need_recompute = False
            for i in range(num_expected):
                if _is_tensorlist_param(i):
                    for j, sub_shape in enumerate(all_shapes[i]):
                        prod = 1
                        for d in sub_shape:
                            prod *= d
                        if prod > budget_per_tensor:
                            all_shapes[i][j] = _cap_shape_product(sub_shape, budget_per_tensor)
                            need_recompute = True
                else:
                    prod = 1
                    for d in all_shapes[i]:
                        prod *= d
                    if prod > budget_per_tensor:
                        all_shapes[i] = _cap_shape_product(all_shapes[i], budget_per_tensor)
                        need_recompute = True
            if need_recompute:
                for i in range(num_expected):
                    if _is_tensorlist_param(i):
                        new_storage = []
                        new_offset = []
                        new_stride = []
                        for sub_shape in all_shapes[i]:
                            if i == t_idx:
                                params, actual_scene = _apply_scene(applied_scene, sub_shape)
                                applied_scene = actual_scene
                                new_storage.append(params['storage_shape'])
                                new_offset.append(params['offset'])
                                new_stride.append(params['strides'])
                            else:
                                cont = generate_continuous_params(sub_shape)
                                new_storage.append(cont['storage_shape'])
                                new_offset.append(cont['offset'])
                                new_stride.append(cont['strides'])
                        all_storage_shapes[i] = new_storage
                        all_offsets[i] = new_offset
                        all_strides[i] = new_stride
                    else:
                        if i == t_idx:
                            params, applied_scene = _apply_scene(applied_scene, all_shapes[i])
                            all_storage_shapes[i] = params['storage_shape']
                            all_offsets[i] = params['offset']
                            all_strides[i] = params['strides']
                        else:
                            cont = generate_continuous_params(all_shapes[i])
                            all_storage_shapes[i] = cont['storage_shape']
                            all_offsets[i] = cont['offset']
                            all_strides[i] = cont['strides']

            def _format_param_shape(param_shape, is_tensorlist):
                if is_tensorlist:
                    return _format_nested_tuple(param_shape)
                else:
                    return _format_tuple(param_shape)

            def _format_param_offset(param_offset, is_tensorlist):
                if is_tensorlist:
                    inner = ",".join(_format_tuple([v]) for v in param_offset)
                    return "(" + inner + ",)"
                else:
                    return _format_tuple([param_offset])

            tensor_name = tp['name']
            new_row = dict(row_data)
            new_row['testcase_name'] = f"{operator_name}_{level}_nc_{tensor_name}_{applied_scene}"

            formatted_shapes = []
            formatted_storages = []
            formatted_offsets_list = []
            formatted_strides = []
            for i in range(num_expected):
                is_tl = _is_tensorlist_param(i)
                formatted_shapes.append(_format_param_shape(all_shapes[i], is_tl))
                formatted_storages.append(_format_param_shape(all_storage_shapes[i], is_tl))
                formatted_offsets_list.append(_format_param_offset(all_offsets[i], is_tl))
                formatted_strides.append(_format_param_shape(all_strides[i], is_tl))

            new_row['tensor_view_shapes'] = '(' + ','.join(formatted_shapes) + ',)'
            new_row['tensor_stroage_shapes'] = '(' + ','.join(formatted_storages) + ',)'
            new_row['tensor_view_offsets'] = '(' + ','.join(formatted_offsets_list) + ',)'
            new_row['tensor_view_strides'] = '(' + ','.join(formatted_strides) + ',)'
            new_row['remark'] = f'non_contiguous_{tensor_name}_{applied_scene}'

            rows.append(new_row)
            scene_stats[applied_scene] = scene_stats.get(applied_scene, 0) + 1
            case_counter += 1

    if not rows:
        if verbose:
            print("[INFO] 非连续用例生成: 0 条")
        return None

    nc_df = pd.DataFrame(rows, dtype=object)
    for col in NC_ACLNN_COLUMNS:
        if col not in nc_df.columns:
            nc_df[col] = ''
    nc_df = nc_df[NC_ACLNN_COLUMNS]

    if verbose:
        print(f"[INFO] 非连续用例独立生成: {len(nc_df)} 条"
              f"（场景分布: {scene_stats})")

    return nc_df


def save_non_contiguous_output(nc_df, output_dir, operator_name, level, verbose=False):
    from pathlib import Path
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    templates = {
        'L0': f'{operator_name}_l0_non_contiguous.csv',
        'L1': f'{operator_name}_l1_non_contiguous.csv',
        'L2': f'{operator_name}_l2_non_contiguous.csv',
    }
    filename = templates.get(level, f'{operator_name}_{level}_non_contiguous.csv')
    path = output_dir / filename
    nc_df.to_csv(path, index=False)
    if verbose:
        print(f"[INFO] 保存非连续用例: {path} ({len(nc_df)}条)")
