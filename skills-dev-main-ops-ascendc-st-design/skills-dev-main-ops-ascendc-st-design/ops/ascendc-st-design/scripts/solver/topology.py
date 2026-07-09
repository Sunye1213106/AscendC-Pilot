import sys
from collections import defaultdict, deque


def build_topology(
    explicit_constraints,
    builtin_rules,
    all_factors,
    intermediate_factors,
    exist_domains=None,
):
    in_degree = defaultdict(int)
    graph = defaultdict(list)

    all_known = set(all_factors)
    for factor in all_known:
        if factor not in in_degree:
            in_degree[factor] = 0

    for target, rule_info in explicit_constraints.items():
        for source in rule_info["sources"]:
            if source not in all_known:
                print(
                    f"[WARN] @solves('{target}') references unknown source '{source}', ignoring edge",
                    file=sys.stderr,
                )
                continue
            graph[source].append(target)
            in_degree[target] += 1

    for target, rule_info in builtin_rules.items():
        for source in rule_info["sources"]:
            if source in all_known:
                graph[source].append(target)
                in_degree[target] += 1

    _check_exist_source_guard(explicit_constraints, all_known, exist_domains)

    queue = deque()
    for factor in all_known:
        if in_degree.get(factor, 0) == 0:
            queue.append(factor)

    order = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for neighbor in graph.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    remaining = [f for f in all_known if f not in set(order)]
    if remaining:
        visited = set()
        cycle_members = []
        for f in remaining:
            if f not in visited:
                path = set()
                current = f
                while current and current not in path:
                    path.add(current)
                    next_nodes = [
                        n for n in graph.get(current, []) if n in set(remaining)
                    ]
                    current = next_nodes[0] if next_nodes else None
                if current and current in path:
                    cycle_start = current
                    cycle = []
                    c = cycle_start
                    while True:
                        cycle.append(c)
                        visited.add(c)
                        next_nodes = [
                            n
                            for n in graph.get(c, [])
                            if n in set(remaining) and n not in visited
                        ]
                        if not next_nodes:
                            break
                        c = next_nodes[0]
                        if c == cycle_start:
                            break
                    cycle_members.append(cycle)

        error_msg = "Cycle detected in factor dependency graph:\n"
        for cycle in cycle_members:
            cycle_str = " -> ".join(cycle + [cycle[0]])
            error_msg += f"  {cycle_str}\n"

        error_msg += "\nSuggested fixes:\n"
        error_msg += "  Remove one @solves from the cycle to break it.\n"
        error_msg += "  See constraint-writing-guide.md §2 for priority rules."
        raise ValueError(error_msg)

    levels = {}
    level_map = {}
    for factor in order:
        max_parent_level = -1
        for source in _get_sources(factor, explicit_constraints, builtin_rules):
            if source in level_map:
                max_parent_level = max(max_parent_level, level_map[source])
        my_level = max_parent_level + 1
        level_map[factor] = my_level
        if my_level not in levels:
            levels[my_level] = []
        levels[my_level].append(factor)

    intermediate_set = set()
    for name, data in intermediate_factors.items():
        attr_names = data.get("factors", {})
        if isinstance(attr_names, dict):
            for attr_key in attr_names.keys():
                intermediate_set.add(attr_key)
            has_value = any(k.endswith('.value') for k in attr_names)
            has_range = any(k.endswith('.value_range') for k in attr_names)
            if has_range and not has_value:
                intermediate_set.add(f"{name}.value")
        else:
            intermediate_set.add(f"{name}.value")

    anchors = []
    derivation_order = {}
    for level_idx in sorted(levels.keys()):
        level_factors = levels[level_idx]
        factor_list = []

        if level_idx == 0:
            pure_intermediates = []
            param_anchors = []
            for f in level_factors:
                if f in intermediate_set and f not in explicit_constraints:
                    pure_intermediates.append(f)
                elif f not in explicit_constraints and f not in builtin_rules:
                    param_anchors.append(f)

            if pure_intermediates:
                derivation_order[f"level_{level_idx}_intermediate"] = pure_intermediates
            if param_anchors:
                derivation_order[f"level_{level_idx}_anchors"] = param_anchors

            for f in level_factors:
                if f in explicit_constraints or f in builtin_rules:
                    factor_list.append(f)
        else:
            factor_list = level_factors

        if factor_list:
            derivation_order[f"level_{level_idx}"] = factor_list

    all_anchors = []
    for key in sorted(derivation_order.keys()):
        if "_intermediate" in key or "_anchors" in key:
            all_anchors.extend(derivation_order[key])

    return all_anchors, derivation_order, intermediate_set


def _get_sources(factor, explicit_constraints, builtin_rules):
    if factor in explicit_constraints:
        return explicit_constraints[factor]["sources"]
    if factor in builtin_rules:
        return builtin_rules[factor]["sources"]
    return []


def _check_exist_source_guard(explicit_constraints, all_known, exist_domains=None):
    _exist_guard_attrs = ('value', 'shape', 'dtype', 'format', 'dimensions', 'length')
    if exist_domains is None:
        exist_domains = {}
    errors = []
    for target, rule_info in explicit_constraints.items():
        if not target.endswith('.exist'):
            continue
        sources = rule_info["sources"]
        func_name = rule_info.get("function", rule_info.get("func"))
        if func_name:
            func_name = func_name.__name__
        else:
            func_name = "<unknown>"
        for source in sources:
            dot_pos = source.rfind('.')
            if dot_pos < 0:
                continue
            attr = source[dot_pos + 1:]
            if attr not in _exist_guard_attrs:
                continue
            param_name = source[:dot_pos]
            exist_key = f"{param_name}.exist"
            if exist_key in all_known and exist_key not in sources:
                domain = exist_domains.get(param_name)
                if domain is not None and all(v is True for v in domain):
                    continue
                errors.append(
                    f"  @solves('{target}') in {func_name}: "
                    f"reads '{source}' but missing '{exist_key}' in sources. "
                    f"When {exist_key}=False, {source} is undefined."
                )
    if errors:
        msg = "Exist-source guard violation detected:\n"
        for e in errors:
            msg += f"{e}\n"
        msg += "\nSuggested fix: add the missing .exist factor to sources "
        msg += "and return False/NOT_APPLICABLE when exist=False.\n"
        msg += "See constraint-writing-guide.md for optional parameter patterns."
        raise ValueError(msg)
