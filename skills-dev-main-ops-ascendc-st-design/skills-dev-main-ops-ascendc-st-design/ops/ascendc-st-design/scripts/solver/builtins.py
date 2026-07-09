import random

from utils import generate_random_shape, get_default_value_range, generate_random_value_by_dtype, param_excludes_infnan


def register_builtin_rules(test_factors, intermediate_factors, explicit_constraints):
    builtin_rules = {}

    for param_name, param_data in test_factors.items():
        if not isinstance(param_data, dict):
            continue
        factors = param_data.get("factors", {})
        io_type = param_data.get("io_type", "input")
        param_type = param_data.get("type", "")
        is_output = io_type == "output"

        if param_type in ("aclTensor", "aclTensorList"):
            _register_tensor_builtins(
                param_name, param_data, factors, is_output, param_type,
                explicit_constraints, builtin_rules,
            )
        elif param_type in (
            "aclIntArray", "aclFloatArray", "aclBoolArray", "aclScalarList",
        ):
            _register_array_builtins(
                param_name, param_data, factors, is_output,
                explicit_constraints, builtin_rules,
            )
        elif param_type not in ("bool", "string") and not is_output:
            _register_scalar_builtins(
                param_name, param_data, factors, param_type,
                explicit_constraints, builtin_rules,
            )

    for name, data in intermediate_factors.items():
        attr_factors = data.get("factors", {})
        if isinstance(attr_factors, dict):
            for attr_key in attr_factors:
                if attr_key not in explicit_constraints and attr_key not in builtin_rules:
                    pass

    return builtin_rules


def _register_tensor_builtins(
    param_name, param_data, factors, is_output, param_type,
    explicit_constraints, builtin_rules,
):
    shape_key = f"{param_name}.shape"
    dim_key = f"{param_name}.dimensions"
    vr_key = f"{param_name}.value_range"
    val_key = f"{param_name}.value"
    dtype_key = f"{param_name}.dtype"

    if shape_key not in explicit_constraints and shape_key not in factors:
        if dim_key in factors or dim_key in explicit_constraints:
            builtin_rules[shape_key] = {
                "sources": [dim_key],
                "target": shape_key,
                "rule": "IMPL-SHAPE",
            }

    if param_type == "aclTensorList":
        len_key = f"{param_name}.length"
        lr_key = f"{param_name}.length_ranges"
        if lr_key in factors or lr_key in explicit_constraints:
            if len_key not in explicit_constraints:
                builtin_rules[len_key] = {
                    "sources": [lr_key],
                    "target": len_key,
                    "rule": "IMPL-LENGTH",
                }

        sl_key = f"{param_name}.shape_list"
        if sl_key not in explicit_constraints and len_key in builtin_rules:
            builtin_rules[sl_key] = {
                "sources": [len_key, dim_key] if dim_key in factors else [len_key],
                "target": sl_key,
                "rule": "IMPL-SHAPE-LIST",
            }

    if not is_output and vr_key not in explicit_constraints:
        if val_key not in explicit_constraints:
            if dtype_key in factors or dtype_key in explicit_constraints:
                sources = [dtype_key]
                dtype_vals = factors.get("dtype", [])
                if isinstance(dtype_vals, str):
                    dtype_vals = [dtype_vals]
                if isinstance(dtype_vals, list):
                    for dt in dtype_vals:
                        vr_dt_key = f"{param_name}.value_range_{dt}"
                        if vr_dt_key in explicit_constraints:
                            sources.append(vr_dt_key)
                builtin_rules[vr_key] = {
                    "sources": sources,
                    "target": vr_key,
                    "rule": "IMPL-RANGE",
                }


def _register_array_builtins(
    param_name, param_data, factors, is_output,
    explicit_constraints, builtin_rules,
):
    len_key = f"{param_name}.length"
    lr_key = f"{param_name}.length_ranges"
    vr_key = f"{param_name}.value_range"
    val_key = f"{param_name}.value"
    dtype_key = f"{param_name}.dtype"

    if lr_key in factors or lr_key in explicit_constraints:
        if len_key not in explicit_constraints:
            builtin_rules[len_key] = {
                "sources": [lr_key],
                "target": len_key,
                "rule": "IMPL-LENGTH",
            }

    if not is_output and vr_key not in explicit_constraints:
        if val_key not in explicit_constraints:
            if dtype_key in factors or dtype_key in explicit_constraints:
                sources = [dtype_key]
                dtype_vals = factors.get(dtype_key, [])
                if isinstance(dtype_vals, str):
                    dtype_vals = [dtype_vals]
                if isinstance(dtype_vals, list):
                    for dt in dtype_vals:
                        vr_dt_key = f"{param_name}.value_range_{dt}"
                        if vr_dt_key in explicit_constraints:
                            sources.append(vr_dt_key)
                builtin_rules[vr_key] = {
                    "sources": sources,
                    "target": vr_key,
                    "rule": "IMPL-RANGE",
                }

    if not is_output and val_key not in explicit_constraints:
        has_length = len_key in builtin_rules or len_key in explicit_constraints
        has_vr = vr_key in builtin_rules or vr_key in explicit_constraints
        if has_length and has_vr:
            builtin_rules[val_key] = {
                "sources": [len_key, vr_key, dtype_key] if dtype_key in factors else [len_key, vr_key],
                "target": val_key,
                "rule": "IMPL-ARRAY-VALUE",
            }


def _register_scalar_builtins(
    param_name, param_data, factors, param_type,
    explicit_constraints, builtin_rules,
):
    vr_key = f"{param_name}.value_range"
    val_key = f"{param_name}.value"
    dtype_key = f"{param_name}.dtype"

    if vr_key not in explicit_constraints and vr_key not in factors:
        if val_key not in explicit_constraints and val_key not in factors:
            if dtype_key in factors or dtype_key in explicit_constraints:
                sources = [dtype_key]
                dtype_vals = factors.get("dtype", [])
                if isinstance(dtype_vals, str):
                    dtype_vals = [dtype_vals]
                if isinstance(dtype_vals, list):
                    for dt in dtype_vals:
                        vr_dt_key = f"{param_name}.value_range_{dt}"
                        if vr_dt_key in explicit_constraints:
                            sources.append(vr_dt_key)
                builtin_rules[vr_key] = {
                    "sources": sources,
                    "target": vr_key,
                    "rule": "IMPL-RANGE",
                }

    if val_key not in explicit_constraints and val_key not in factors:
        has_vr = vr_key in builtin_rules or vr_key in explicit_constraints or vr_key in factors
        has_dtype_vr = any(
            f"{param_name}.value_range_{dt}" in factors
            for dt in (factors.get(dtype_key, []) if isinstance(factors.get(dtype_key, []), list) else [factors.get(dtype_key, "")])
            if dt
        )
        has_vr = has_vr or has_dtype_vr
        if has_vr:
            sources = [vr_key]
            if dtype_key in factors:
                sources.append(dtype_key)
            builtin_rules[val_key] = {
                "sources": sources,
                "target": val_key,
                "rule": "IMPL-SCALAR-VALUE",
            }


def solve_builtin(rule_info, context, test_factors):
    rule = rule_info["rule"]
    target = rule_info["target"]
    sources = rule_info["sources"]

    source_values = [context.get(s) for s in sources]
    if any(v is None for v in source_values):
        return None

    if rule == "IMPL-SHAPE":
        return _solve_impl_shape(source_values, context, target)
    elif rule == "IMPL-RANGE":
        return _solve_impl_range(source_values, context, target, test_factors)
    elif rule == "IMPL-LENGTH":
        return _solve_impl_length(source_values, context, target)
    elif rule == "IMPL-SHAPE-LIST":
        return _solve_impl_shape_list(source_values, context, target)
    elif rule == "IMPL-ARRAY-VALUE":
        return _solve_impl_array_value(source_values, context, target)
    elif rule == "IMPL-SCALAR-VALUE":
        return _solve_impl_scalar_value(source_values, context, target)
    return None


def _solve_impl_shape(source_values, context, target):
    dimensions = source_values[0]
    if isinstance(dimensions, int) and dimensions == 0:
        return []
    if isinstance(dimensions, int) and dimensions > 0:
        return generate_random_shape(dimensions)
    return None


def _solve_impl_range(source_values, context, target, test_factors):
    dtype = source_values[0]
    if dtype is None:
        return None
    param_name = target.split(".")[0]
    param_data = test_factors.get(param_name, {})
    factors = param_data.get("factors", {})

    key = f"{param_name}.value_range_{dtype}"
    if key in factors:
        return factors[key]

    key = f"{param_name}.value_range"
    if key in factors:
        return factors[key]

    vr_dtype_key = f"{param_name}.value_range_{dtype}"
    if vr_dtype_key in context and context[vr_dtype_key] is not None:
        return context[vr_dtype_key]

    exclude_infnan = param_excludes_infnan(param_data)
    return get_default_value_range(dtype, exclude_infnan=exclude_infnan)


def _solve_impl_length(source_values, context, target):
    length_ranges = source_values[0]
    if not isinstance(length_ranges, list) or not length_ranges:
        return None
    if isinstance(length_ranges[0], list):
        selected_range = random.choice(length_ranges)
        return random.randint(int(selected_range[0]), int(selected_range[1]))
    return random.randint(int(length_ranges[0]), int(length_ranges[1]))


def _solve_impl_shape_list(source_values, context, target):
    length_val = source_values[0]
    dimensions_val = source_values[1] if len(source_values) > 1 else None
    if not isinstance(length_val, int):
        return None
    if length_val == 0:
        return []
    if dimensions_val is not None and isinstance(dimensions_val, int) and dimensions_val >= 0:
        from solver.shapes import generate_broadcast_compatible_shapes
        return generate_broadcast_compatible_shapes(dimensions_val, length_val)
    return None


def _select_range(value_range):
    if not isinstance(value_range, list) or len(value_range) == 0:
        return None
    if isinstance(value_range[0], list):
        return random.choice(value_range)
    if len(value_range) == 2:
        return value_range
    return None


def _solve_impl_array_value(source_values, context, target):
    length_val = source_values[0]
    value_range = source_values[1]
    dtype_value = source_values[2] if len(source_values) > 2 else "int64"

    if not isinstance(length_val, int):
        return None

    selected = _select_range(value_range)
    if selected is None:
        return None

    return [generate_random_value_by_dtype(dtype_value, selected) for _ in range(length_val)]


def _solve_impl_scalar_value(source_values, context, target):
    value_range = source_values[0]
    dtype_value = source_values[1] if len(source_values) > 1 else "int64"

    selected = _select_range(value_range)
    if selected is None:
        return None

    return generate_random_value_by_dtype(dtype_value, selected)
