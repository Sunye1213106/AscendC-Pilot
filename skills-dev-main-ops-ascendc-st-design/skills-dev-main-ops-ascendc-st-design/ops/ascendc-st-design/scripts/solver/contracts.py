import math

from utils import normalize_dtype

_strict_shape = True


def set_strict_shape(strict):
    global _strict_shape
    _strict_shape = strict


def validate_shape(value):
    if not isinstance(value, list):
        return False, f"expected list[int], got {type(value).__name__}: {repr(value)}"
    if _strict_shape:
        if len(value) > 8:
            return False, f"shape dimensions {len(value)} > 8"
        product = 1
        for i, x in enumerate(value):
            if not isinstance(x, int):
                return False, f"shape[{i}] is not int: {repr(x)}"
            if x < 0:
                return False, f"shape[{i}] < 0: {x}"
            product *= x
            if product > 2147483648:
                return False, f"shape product {product} > 2147483648"
    else:
        for i, x in enumerate(value):
            if not isinstance(x, int):
                return False, f"shape[{i}] is not int: {repr(x)}"
            if x < 0:
                return False, f"shape[{i}] < 0: {x}"
    return True, None


def validate_shape_list(value):
    if not isinstance(value, list):
        return False, f"expected list[list[int]], got {type(value).__name__}"
    total_elements = 0
    for i, s in enumerate(value):
        if not isinstance(s, list):
            return False, f"shape_list[{i}] is not list: {repr(s)}"
        if _strict_shape and len(s) > 8:
            return False, f"shape_list[{i}] has {len(s)} dimensions (max 8)"
        product = 1
        for j, x in enumerate(s):
            if not isinstance(x, int) or x < 0:
                return False, f"shape_list[{i}][{j}] invalid: {repr(x)}"
            if _strict_shape:
                product *= x
                if product > 2147483648:
                    return False, f"shape_list[{i}] product {product} > 2147483648"
        if _strict_shape:
            total_elements += product
    if _strict_shape and total_elements > 2147483648:
        return False, f"shape_list total elements {total_elements} > 2147483648"
    return True, None


def validate_dtype(value):
    if not isinstance(value, str):
        return False, f"dtype is not str: {type(value).__name__} = {repr(value)}"
    if normalize_dtype(value) is None:
        return False, f"unknown dtype: {value}"
    return True, None


def validate_dtype_list(value):
    if not isinstance(value, list):
        return False, f"expected list[str], got {type(value).__name__}: {repr(value)}"
    for i, d in enumerate(value):
        if not isinstance(d, str):
            return False, f"dtype_list[{i}] is not str: {repr(d)}"
        if normalize_dtype(d) is None:
            return False, f"dtype_list[{i}] unknown dtype: {repr(d)}"
    return True, None


def validate_dimensions(value):
    if not isinstance(value, int):
        return False, f"dimensions is not int: {type(value).__name__} = {repr(value)}"
    if value < 0 or value > 8:
        return False, f"dimensions out of [0,8]: {value}"
    return True, None


def validate_length(value):
    if not isinstance(value, int):
        return False, f"length is not int: {type(value).__name__} = {repr(value)}"
    if value < 0:
        return False, f"length < 0: {value}"
    return True, None


def validate_value_range(value):
    if not isinstance(value, list):
        return False, f"value_range is not list: {type(value).__name__}"
    if len(value) > 0:
        if isinstance(value[0], list):
            for i, rng in enumerate(value):
                if not isinstance(rng, list) or len(rng) != 2:
                    return False, f"value_range[{i}] is not [min,max]: {repr(rng)}"
        elif len(value) != 2:
            return False, f"value_range should be [min,max]: {repr(value)}"
    return True, None


_FACTOR_CONTRACTS = {
    '.shape_list': validate_shape_list,
    '.shape': validate_shape,
    '.dtype_list': validate_dtype_list,
    '.dtype': validate_dtype,
    '.dimensions': validate_dimensions,
    '.length': validate_length,
    '.value_range': validate_value_range,
}

_SORTED_SUFFIXES = sorted(_FACTOR_CONTRACTS.keys(), key=lambda s: -len(s))


def validate_factor(factor_name, value, combo=None):
    """
    校验因子值是否满足类型契约。

    Args:
        factor_name: 因子名（如 'out.shape'）
        value: 待校验的值
        combo: 当前组合 dict，用于 exist-aware 校验

    Returns:
        (ok, error_msg): ok=True 表示合法
    """
    if value is None:
        if combo is not None and is_exist_false(factor_name, combo):
            return True, None
        return False, f"unexpected None for {factor_name} (use NOT_APPLICABLE instead)"

    for suffix in _SORTED_SUFFIXES:
        if factor_name.endswith(suffix):
            return _FACTOR_CONTRACTS[suffix](value)

    return True, None


def get_param_name(factor_name):
    parts = factor_name.rsplit('.', 1)
    return parts[0] if len(parts) == 2 else factor_name


def is_exist_false(factor_name, combo):
    """
    检查因子所属参数是否 exist=False。

    对 combo 中所有 {param}.exist 因子做检查：
    - 找到 factor_name 所属的 param_name
    - 检查 combo 中 {param_name}.exist 是否为 False
    """
    param_name = get_param_name(factor_name)
    exist_key = f'{param_name}.exist'
    if exist_key in combo and combo[exist_key] is False:
        return True
    return False
