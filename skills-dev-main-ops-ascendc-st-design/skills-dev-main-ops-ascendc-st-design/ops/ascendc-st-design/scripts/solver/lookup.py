"""
查找表标准工具函数。

用于将 01_parameter_description.md R{n} 约束中的映射表转录为 Python 数据结构。
LLM 只需逐行抄写原始表格，由本函数自动完成笛卡尔积展开和完整性校验。

用法:
    from solver.lookup import expand_lookup

    _RAW_ROWS = [
        (['complex32'], ['complex64']),
        (['float32', 'float16', 'bfloat16'], ['float4_e2m1', 'float4_e1m2']),
        ...
    ]
    _LOOKUP = expand_lookup(
        _RAW_ROWS,
        expected_row_count=13,
        source_domain={'complex32', 'float32', ...},
        target_domain={'complex64', 'float4_e2m1', ...},
    )
"""

from collections import defaultdict


def expand_lookup(rows, expected_row_count=None, source_domain=None, target_domain=None):
    """将原始行格式查找表展开为 {source: [targets]} 字典。

    原始行格式为 (source_list, target_list) 的列表，对应文档中映射表的每一行。
    多值单元格（如 FLOAT32/FLOAT16/BFLOAT16）以列表形式保存，由本函数自动展开为
    笛卡尔积。LLM 只需逐行抄写，无需手工展开。

    Args:
        rows: 原始行列表，每行为 (source_list, target_list)。
              source_list 和 target_list 均为字符串列表，对应文档表格中
              用 '/' 分隔的多个值。
        expected_row_count: 预期行数（即 R{n} 原始映射表的行数）。
            若指定，加载时自动校验行数是否一致，防止抄写遗漏或重复。
        source_domain: source 的合法值集合（set 或 list）。
            若指定，校验每个 source 值是否在域内，防止拼写错误。
        target_domain: target 的合法值集合（set 或 list）。
            若指定，校验每个 target 值是否在域内，防止拼写错误。

    Returns:
        dict: {source: sorted([target_list])}，每个 source 映射到排序后的 target 列表。

    Raises:
        AssertionError: 行数不匹配、source/target 值不在域内时触发。

    Example:
        >>> rows = [
        ...     (['a', 'b'], ['x', 'y']),
        ...     (['c'], ['x']),
        ... ]
        >>> expand_lookup(rows)
        {'a': ['x', 'y'], 'b': ['x', 'y'], 'c': ['x']}
    """
    if expected_row_count is not None:
        assert len(rows) == expected_row_count, (
            f"lookup table row count mismatch: got {len(rows)}, "
            f"expected {expected_row_count}. "
            f"Check _RAW_LOOKUP_ROWS against R{{n}} original table."
        )

    source_domain_set = set(source_domain) if source_domain is not None else None
    target_domain_set = set(target_domain) if target_domain is not None else None

    result = defaultdict(set)

    for row_idx, (sources, targets) in enumerate(rows):
        assert isinstance(sources, list), (
            f"row {row_idx}: sources must be list, got {type(sources)}"
        )
        assert isinstance(targets, list), (
            f"row {row_idx}: targets must be list, got {type(targets)}"
        )
        assert len(sources) > 0, f"row {row_idx}: sources is empty"
        assert len(targets) > 0, f"row {row_idx}: targets is empty"

        for s in sources:
            if source_domain_set is not None:
                assert s in source_domain_set, (
                    f"row {row_idx}: source '{s}' not in source_domain"
                )
            for t in targets:
                if target_domain_set is not None:
                    assert t in target_domain_set, (
                        f"row {row_idx}: target '{t}' not in target_domain"
                    )
                result[s].add(t)

    return {k: sorted(v) for k, v in result.items()}
