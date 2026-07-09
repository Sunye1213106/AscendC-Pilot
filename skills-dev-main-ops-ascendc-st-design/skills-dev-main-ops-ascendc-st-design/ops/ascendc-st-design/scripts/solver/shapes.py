import math
import random


def generate_broadcast_compatible_shapes(ndim, count, max_dim=8):
    """
    生成 count 个互相广播兼容的 shape。

    生成策略：
    1. 先随机生成一个 base_shape
    2. 后续每个 shape 基于 base_shape，每个维度随机选择保持原值或退化为 1
    3. 保证所有 shape 互相广播兼容（维度相等或某一方为 1）

    Args:
        ndim: shape 的维度数
        count: 需要生成的 shape 数量
        max_dim: 单个维度的最大值

    Returns:
        list[list[int]]: 互相广播兼容的 shape 列表
    """
    if count <= 0:
        return []
    if ndim <= 0:
        return [[] for _ in range(count)]

    base_shape = [random.randint(1, max_dim) for _ in range(ndim)]
    shapes = [list(base_shape)]
    for _ in range(count - 1):
        shape = [random.choice([1, d]) for d in base_shape]
        shapes.append(shape)
    return shapes


def reduce_shape(input_shape, dim, keepdim):
    ndim = len(input_shape)
    if not dim:
        return [1] * ndim if keepdim else []
    norm_dims = set(d + ndim if d < 0 else d for d in dim)
    if keepdim:
        return [1 if i in norm_dims else s for i, s in enumerate(input_shape)]
    return [s for i, s in enumerate(input_shape) if i not in norm_dims]


def identity_shape(input_shape):
    return list(input_shape)


def transpose_shape(input_shape, perm):
    return [input_shape[p] for p in perm]


def slice_shape(input_shape, dim, start, end, step=1):
    result = list(input_shape)
    ndim = len(result)
    if dim < 0:
        dim += ndim
    length = end - start
    if step > 1:
        length = math.ceil(length / step)
    result[dim] = max(0, length)
    return result


def concat_shape(input_shapes, dim):
    if not input_shapes:
        return []
    result = list(input_shapes[0])
    for shape in input_shapes[1:]:
        result[dim] += shape[dim]
    return result


def stack_shape(input_shape, count, dim):
    result = list(input_shape)
    result.insert(dim, count)
    return result


def flatten_shape(input_shape, start_dim=0, end_dim=-1):
    ndim = len(input_shape)
    if end_dim < 0:
        end_dim += ndim
    if start_dim == 0 and end_dim == ndim - 1:
        product = 1
        for d in input_shape:
            product *= d
        return [product]
    result = list(input_shape[:start_dim])
    flat = 1
    for i in range(start_dim, end_dim + 1):
        flat *= input_shape[i]
    result.append(flat)
    result.extend(input_shape[end_dim + 1:])
    return result


def broadcast_expand_shape(input_shape, sizes):
    return list(sizes)


def tile_repeat_shape(input_shape, repeats):
    return [s * r for s, r in zip(input_shape, repeats)]


def topk_shape(input_shape, k, dim):
    ndim = len(input_shape)
    if dim < 0:
        dim += ndim
    result = list(input_shape)
    result[dim] = k
    return result


def sort_shape(input_shape):
    return list(input_shape)


def broadcast_ternary_shape(shape_a, shape_b, shape_c):
    from utils import get_broadcast_result
    ab = get_broadcast_result([shape_a, shape_b])
    if ab is None:
        return None
    return get_broadcast_result([ab, shape_c])


def broadcast_shapes(source_shape):
    from utils import (
        generate_broadcast_shapes,
        generate_unidirectional_broadcast_shapes,
        can_broadcast_to,
    )
    results = [list(source_shape)]
    for _ in range(4):
        try:
            shape = generate_broadcast_shapes(source_shape)
            if shape != source_shape:
                results.append(shape)
        except Exception:
            pass
    for _ in range(3):
        try:
            shape = generate_unidirectional_broadcast_shapes(source_shape)
            if shape != source_shape and shape not in results:
                results.append(shape)
        except Exception:
            pass
    return results
