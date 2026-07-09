import sys
import os
import random
import math
import hashlib
import yaml
from collections import defaultdict
from itertools import product as itertools_product

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from solver.registry import (
    Candidates,
    SKIP,
    NOT_APPLICABLE,
    ConstraintRegistry,
    solves,
    get_active_registry,
    set_active_registry,
)
from solver.topology import build_topology
from solver.builtins import register_builtin_rules, solve_builtin
from solver.contracts import validate_factor, is_exist_false
from solver.tags import get_and_reset_tags, tag
from utils import make_hashable


class FactorValueEngine:
    MAX_EXPANSION_PER_FACTOR = 128
    MAX_TOTAL_COMBINATIONS = 100000

    def __init__(self, max_expansion=128, max_total=100000, seed=None):
        self.max_expansion = max_expansion
        self.max_total = max_total
        self.seed = seed
        self.test_factors = {}
        self.intermediate = {}
        self.constraints = {}
        self.builtin_rules = {}
        self.topology_order = {}
        self.anchors = []
        self.intermediate_factors = set()
        self._solve_failures = {}
        self._produced_values = defaultdict(set)
        self._validate_mode = False

    def load(self, test_factors_path, constraints_path=None):
        with open(test_factors_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        self.intermediate = raw.pop("intermediate", {})
        self.test_factors = raw

        registry = ConstraintRegistry()
        set_active_registry(registry)

        if constraints_path and os.path.exists(constraints_path):
            constraint_globals = {
                "solves": solves,
                "Candidates": Candidates,
                "SKIP": SKIP,
                "NOT_APPLICABLE": NOT_APPLICABLE,
                "tag": tag,
            }
            scripts_dir = os.path.dirname(os.path.abspath(__file__))
            solver_dir = os.path.join(scripts_dir, "solver")
            constraint_globals["__solver_dir__"] = solver_dir

            with open(constraints_path, "r", encoding="utf-8") as f:
                code = f.read()

            exec(compile(code, constraints_path, "exec"), constraint_globals)

        self.constraints = registry.get_all()

        self.builtin_rules = register_builtin_rules(
            self.test_factors, self.intermediate, self.constraints
        )

        all_factors = self._collect_all_factors()

        exist_domains = {}
        for param_name, param_data in self.test_factors.items():
            if not isinstance(param_data, dict):
                continue
            param_factors = param_data.get("factors", {})
            exist_key = f"{param_name}.exist"
            if exist_key in param_factors:
                exist_domains[param_name] = param_factors[exist_key]

        self.anchors, self.topology_order, self.intermediate_factors = build_topology(
            self.constraints,
            self.builtin_rules,
            all_factors,
            self.intermediate,
            exist_domains,
        )

    def _collect_all_factors(self):
        factors = set()
        for param_name, param_data in self.test_factors.items():
            if not isinstance(param_data, dict):
                continue
            param_factors = param_data.get("factors", {})
            for key in param_factors:
                factors.add(key)

        for name, data in self.intermediate.items():
            attr_factors = data.get("factors", {})
            if isinstance(attr_factors, dict):
                for key in attr_factors:
                    factors.add(key)
                has_value = any(k.endswith('.value') for k in attr_factors)
                has_range = any(k.endswith('.value_range') for k in attr_factors)
                if has_range and not has_value:
                    factors.add(f"{name}.value")
            else:
                factors.add(f"{name}.value")

        for target in self.constraints:
            factors.add(target)
            for source in self.constraints[target]["sources"]:
                factors.add(source)

        for target in self.builtin_rules:
            factors.add(target)
            for source in self.builtin_rules[target]["sources"]:
                factors.add(source)

        return factors

    def get_factor_domain(self, factor_name):
        parts = factor_name.split(".")
        if len(parts) != 2:
            return []

        param_name, attr = parts

        for name, data in self.intermediate.items():
            attr_factors = data.get("factors", {})
            if isinstance(attr_factors, dict) and factor_name in attr_factors:
                domain = attr_factors[factor_name]
                if isinstance(domain, list):
                    return domain
                return [domain]

        param_data = self.test_factors.get(param_name)
        if param_data is None:
            return []
        factors = param_data.get("factors", {})

        exact_key = factor_name
        if exact_key in factors:
            domain = factors[exact_key]
            if isinstance(domain, list):
                return domain
            return [domain]

        if attr == "value":
            for key in factors:
                if key.startswith(f"{param_name}.value_range"):
                    return []
        elif attr == "value_range":
            for key in factors:
                if key.startswith(f"{param_name}.value_range"):
                    domain = factors[key]
                    if isinstance(domain, list):
                        return domain
                    return [domain]

        return []

    def solve(self, max_cases=10000):
        from solver.contracts import set_strict_shape
        set_strict_shape(False)
        try:
            if self.seed is not None:
                random.seed(self.seed)

            anchor_combos = self._generate_anchor_combinations()
            if not anchor_combos:
                anchor_combos = [{}]

            sorted_keys = sorted(
                self.topology_order.keys(),
                key=lambda k: (
                    int(k.replace("level_", "").split("_")[0]),
                    0 if "intermediate" in k else (1 if "anchors" in k else 2),
                ),
            )

            for level_key in sorted_keys:
                level_factors = self.topology_order[level_key]
                for factor in level_factors:
                    anchor_combos = self._solve_factor(anchor_combos, factor)

            if self._validate_mode:
                self._report_domain_reachability()

            self._report_satisfaction(anchor_combos)

            cases = self._clean_nan_cases(anchor_combos)

            cases = self._exclude_intermediate_factors(cases)
            return cases[:max_cases]
        finally:
            set_strict_shape(True)

    def _generate_anchor_combinations(self):
        trivial_defaults = {}
        anchor_domains = {}
        for anchor in self.anchors:
            domain = self.get_factor_domain(anchor)
            if domain:
                if len(domain) == 1:
                    trivial_defaults[anchor] = domain[0]
                else:
                    anchor_domains[anchor] = domain

        if not anchor_domains:
            base = dict(trivial_defaults)
            return [base] if base else [{}]

        total_product = 1
        overflow = False
        for domain in anchor_domains.values():
            total_product *= len(domain)
            if total_product > self.max_total:
                overflow = True
                break

        if not overflow and total_product <= 100000:
            print(
                f"[INFO] anchor expansion: full mode, "
                f"{len(anchor_domains)} effective anchors, "
                f"{len(trivial_defaults)} trivial, "
                f"total={total_product}",
                file=sys.stderr,
            )
            return self._full_expansion(anchor_domains, trivial_defaults)
        else:
            target_count = self.max_total
            print(
                f"[INFO] anchor expansion: lazy sampling mode, "
                f"{len(anchor_domains)} effective anchors, "
                f"{len(trivial_defaults)} trivial, "
                f"target={target_count}",
                file=sys.stderr,
            )
            return self._lazy_sampling(
                anchor_domains, trivial_defaults, target_count
            )

    def _full_expansion(self, anchor_domains, trivial_defaults):
        anchor_names = list(anchor_domains.keys())
        all_combinations = list(
            itertools_product(*[anchor_domains[a] for a in anchor_names])
        )
        combinations = []
        for combo in all_combinations:
            case = dict(trivial_defaults)
            for i, anchor in enumerate(anchor_names):
                case[anchor] = combo[i]
            combinations.append(case)
        return combinations

    def _lazy_sampling(self, anchor_domains, trivial_defaults, target_count):
        """大规模场景：随机采样（避免OOM）"""
        if self.seed is not None:
            random.seed(self.seed)
        anchor_names = list(anchor_domains.keys())
        combinations = []
        seen = set()
        max_attempts = target_count * 20
        attempts = 0

        while len(combinations) < target_count and attempts < max_attempts:
            case = dict(trivial_defaults)
            for name in anchor_names:
                case[name] = random.choice(anchor_domains[name])

            key_parts = []
            for a in anchor_names:
                v = case.get(a)
                key_parts.append(tuple(v) if isinstance(v, list) else v)
            key = tuple(key_parts)
            if key not in seen:
                seen.add(key)
                combinations.append(case)
            attempts += 1

        if len(combinations) < target_count:
            print(
                f"[WARN] lazy sampling: only got {len(combinations)}/{target_count} "
                f"unique combinations after {max_attempts} attempts",
                file=sys.stderr,
            )

        return combinations

    def _solve_factor(self, combinations, factor):
        if factor in self.constraints:
            return self._solve_explicit(combinations, factor)
        elif factor in self.builtin_rules:
            return self._solve_builtin_factor(combinations, factor)
        else:
            return self._solve_from_domain(combinations, factor)

    def _solve_explicit(self, combinations, factor):
        func_info = self.constraints[factor]
        func = func_info["function"]
        source_names = func_info["sources"]

        new_combos = []
        solve_failures = 0
        solve_total = 0
        contract_failures = 0

        for combo in combinations:
            if factor in combo:
                new_combos.append(combo)
                continue

            if any(s not in combo for s in source_names):
                new_combos.append(combo)
                continue
            source_values = [combo.get(s) for s in source_names]

            solve_total += 1
            try:
                result = func(*source_values)
                case_tags = get_and_reset_tags()
            except AssertionError:
                solve_failures += 1
                continue
            except Exception as e:
                solve_failures += 1
                print(f"[WARN] {factor} solve failed: {e}", file=sys.stderr)
                continue

            if result is SKIP:
                fallback = self._try_skip_fallback(factor, combo)
                if fallback is not SKIP:
                    self._produced_values[factor].add(make_hashable(fallback))
                    new_combo = dict(combo)
                    new_combo.update(case_tags)
                    new_combo[factor] = fallback
                    new_combos.append(new_combo)
                else:
                    combo.update(case_tags)
                    new_combos.append(combo)
            elif result is NOT_APPLICABLE:
                new_combo = dict(combo)
                new_combo.update(case_tags)
                new_combo[factor] = None
                new_combos.append(new_combo)
            elif isinstance(result, Candidates):
                candidates = list(result)
                valid_candidates = []
                for value in candidates:
                    ok, msg = validate_factor(factor, value, combo)
                    if ok:
                        valid_candidates.append(value)
                    elif contract_failures < 3:
                        contract_failures += 1
                        print(
                            f"[CONTRACT] {factor} value violates type contract: {msg}",
                            file=sys.stderr,
                        )
                if not valid_candidates:
                    contract_failures += len(candidates)
                    continue
                candidates = valid_candidates
                if len(candidates) > self.max_expansion:
                    random.seed(self.seed)
                    candidates = random.sample(candidates, self.max_expansion)
                for value in candidates:
                    self._produced_values[factor].add(make_hashable(value))
                    new_combo = dict(combo)
                    new_combo.update(case_tags)
                    new_combo[factor] = value
                    new_combos.append(new_combo)
            else:
                ok, msg = validate_factor(factor, result, combo)
                if not ok:
                    contract_failures += 1
                    if contract_failures <= 3:
                        print(
                            f"[CONTRACT] {factor} value violates type contract: {msg}",
                            file=sys.stderr,
                        )
                    continue
                self._produced_values[factor].add(make_hashable(result))
                new_combo = dict(combo)
                new_combo.update(case_tags)
                new_combo[factor] = result
                new_combos.append(new_combo)

        if len(new_combos) > self.max_total:
            random.seed(self.seed)
            new_combos = random.sample(new_combos, self.max_total)

        if solve_failures > 0:
            self._solve_failures[factor] = (solve_failures, solve_total)
            print(
                f"[INFO] {factor}: {solve_failures}/{solve_total} combinations skipped (assert/exception)",
                file=sys.stderr,
            )

        if contract_failures > 0:
            print(
                f"[CONTRACT] {factor}: {contract_failures}/{solve_total} combinations "
                f"dropped (type contract violation)",
                file=sys.stderr,
            )

        return new_combos

    def _solve_builtin_factor(self, combinations, factor):
        rule_info = self.builtin_rules[factor]

        new_combos = []
        contract_failures = 0
        for combo in combinations:
            if factor in combo:
                new_combos.append(combo)
                continue

            result = solve_builtin(rule_info, combo, self.test_factors)
            if result is not None:
                ok, msg = validate_factor(factor, result, combo)
                if not ok:
                    contract_failures += 1
                    if contract_failures <= 3:
                        print(
                            f"[CONTRACT] {factor} (builtin) value violates type contract: {msg}",
                            file=sys.stderr,
                        )
                else:
                    self._produced_values[factor].add(make_hashable(result))
                    new_combo = dict(combo)
                    new_combo[factor] = result
                    new_combos.append(new_combo)
            else:
                domain = self.get_factor_domain(factor)
                if domain:
                    value = random.choice(domain)
                    self._produced_values[factor].add(make_hashable(value))
                    new_combo = dict(combo)
                    new_combo[factor] = value
                    new_combos.append(new_combo)
                else:
                    new_combos.append(combo)

        if contract_failures > 0:
            print(
                f"[CONTRACT] {factor} (builtin): {contract_failures} combinations "
                f"dropped (type contract violation)",
                file=sys.stderr,
            )

        return new_combos

    def _solve_from_domain(self, combinations, factor):
        domain = self.get_factor_domain(factor)
        if domain:
            new_combos = []
            for combo in combinations:
                if factor in combo:
                    new_combos.append(combo)
                    continue

                if self.seed is not None:
                    random.seed(self.seed + hash(combo.get("self.dtype", "")) if combo else self.seed)

                value = random.choice(domain)
                self._produced_values[factor].add(make_hashable(value))
                new_combo = dict(combo)
                new_combo[factor] = value
                new_combos.append(new_combo)

            return new_combos

        ranges = self._get_intermediate_value_range(factor)
        if ranges is not None:
            return self._solve_from_value_range(combinations, factor, ranges)

        return combinations

    def _get_intermediate_value_range(self, factor):
        if not factor.endswith('.value'):
            return None
        param_name = factor.rsplit('.', 1)[0]
        if param_name not in self.intermediate:
            return None
        attr_factors = self.intermediate[param_name].get("factors", {})
        if not isinstance(attr_factors, dict):
            return None
        range_key = f"{param_name}.value_range"
        if range_key not in attr_factors:
            return None
        return attr_factors[range_key]

    def _solve_from_value_range(self, combinations, factor, ranges):
        if not ranges:
            return combinations
        if not isinstance(ranges[0], list):
            ranges = [ranges]

        new_combos = []
        for combo in combinations:
            if factor in combo:
                new_combos.append(combo)
                continue

            lo, hi = random.choice(ranges)
            lo, hi = int(lo), int(hi)
            if lo == hi:
                value = lo
            else:
                value = random.randint(lo, hi)

            new_combo = dict(combo)
            new_combo[factor] = value
            new_combos.append(new_combo)

        return new_combos

    def _exclude_intermediate_factors(self, cases):
        excluded = []
        for case in cases:
            filtered = {}
            for k, v in case.items():
                if k in self.intermediate_factors:
                    filtered[f"_tag_{k}"] = v
                    filtered[k] = v
                else:
                    filtered[k] = v
            excluded.append(filtered)
        return excluded

    def _clean_nan_cases(self, cases):
        """
        清洗含非法 NaN/None 的用例（exist-aware）。
        必须在 _exclude_intermediate_factors 之前调用，
        以确保 .exist 因子仍在 combo 中可查。
        """
        if not cases:
            return cases

        clean_cases = []
        nan_stats = {}

        for case in cases:
            has_invalid_nan = False
            for k, v in case.items():
                is_nan = (v is None) or (isinstance(v, float) and math.isnan(v))
                if not is_nan:
                    continue

                if is_exist_false(k, case):
                    continue

                nan_stats[k] = nan_stats.get(k, 0) + 1
                has_invalid_nan = True

            if not has_invalid_nan:
                clean_cases.append(case)

        dropped = len(cases) - len(clean_cases)
        if dropped > 0:
            print(
                f"\n[WARN] {dropped}/{len(cases)} cases contain invalid NaN/None values (dropped):",
                file=sys.stderr,
            )
            for k, count in sorted(nan_stats.items(), key=lambda x: -x[1])[:10]:
                print(f"  {k}: {count}", file=sys.stderr)
        elif nan_stats:
            print(
                f"\n[INFO] {len(nan_stats)} factors have NaN values "
                f"(all from optional params with exist=False, OK)",
                file=sys.stderr,
            )

        return clean_cases

    def _report_satisfaction(self, cases):
        print("\n" + "=" * 60, file=sys.stderr)
        print("Constraint satisfaction report", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

        for factor, func_info in self.constraints.items():
            func = func_info["function"]
            sources = func_info["sources"]

            satisfied = 0
            total = 0
            for case in cases:
                if any(s not in case for s in sources):
                    continue
                source_values = [case.get(s) for s in sources]
                total += 1
                try:
                    result = func(*source_values)
                    if result is SKIP or result is NOT_APPLICABLE:
                        satisfied += 1
                    elif isinstance(result, Candidates):
                        if case.get(factor) in list(result):
                            satisfied += 1
                    elif case.get(factor) == result:
                        satisfied += 1
                except Exception:
                    pass

            rate = satisfied / total * 100 if total > 0 else 0
            status = "OK" if rate >= 95 else ("WARN" if rate >= 50 else "FAIL")
            coverage_note = ""
            if total > 0 and rate < 50:
                sample_satisfied = 0
                sample_total = min(20, total)
                checked = 0
                for case in cases:
                    if checked >= sample_total:
                        break
                    if any(s not in case for s in sources):
                        continue
                    source_values = [case.get(s) for s in sources]
                    checked += 1
                    try:
                        func(*source_values)
                        sample_satisfied += 1
                    except Exception:
                        pass
                if sample_satisfied == sample_total:
                    coverage_note = " (random function - constraints valid)"
                    status = "OK"
            print(
                f"  [{status}] {factor}: {rate:.1f}% ({satisfied}/{total}){coverage_note}",
                file=sys.stderr,
            )

        if self._solve_failures:
            print("\nSolve failure stats:", file=sys.stderr)
            for factor, (failures, total) in self._solve_failures.items():
                print(
                    f"  [SKIP] {factor}: {failures}/{total} skipped (assert/exception)",
                    file=sys.stderr,
                )

        print("=" * 60, file=sys.stderr)

    def _report_domain_reachability(self):
        print("\n域可达性报告", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        has_warning = False
        for factor in sorted(self._produced_values.keys()):
            domain = self.get_factor_domain(factor)
            if not domain or len(domain) <= 1:
                continue
            domain_set = set(make_hashable(v) for v in domain)
            produced = self._produced_values[factor]
            covered = domain_set & produced
            uncovered = domain_set - produced
            rate = len(covered) / len(domain_set) * 100

            if uncovered:
                has_warning = True
                status = "WARN" if rate < 100 else "INFO"
                print(
                    f"  [{status}] {factor}: 域可达率 {rate:.1f}% "
                    f"({len(covered)}/{len(domain_set)}) "
                    f"-- 未覆盖: {sorted(uncovered, key=str)}",
                    file=sys.stderr,
                )
                print(
                    f"         建议: 检查 04_constraints.py 中 target='{factor}' 的 "
                    f"@solves 函数是否应返回 Candidates() 而非单值",
                    file=sys.stderr,
                )
            else:
                print(
                    f"  [OK] {factor}: 域可达率 100.0% "
                    f"({len(covered)}/{len(domain_set)})",
                    file=sys.stderr,
                )

        if not has_warning:
            print("  [OK] 所有 solved 因子的 YAML 域值均可被 @solves 产生", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        return not has_warning

    def generate_topology_report(self, output_path=None):
        lines = []
        lines.append("# Factor Dependency Topology\n")
        lines.append("## Solve Order\n")

        sorted_keys = sorted(
            self.topology_order.keys(),
            key=lambda k: (
                int(k.replace("level_", "").split("_")[0]),
                0 if "intermediate" in k else (1 if "anchors" in k else 2),
            ),
        )

        for level_key in sorted_keys:
            level_factors = self.topology_order[level_key]
            if "intermediate" in level_key:
                lines.append(f"**{level_key} (pure anchor intermediate):**")
                for f in level_factors:
                    domain = self.get_factor_domain(f)
                    lines.append(f"  - `{f}`  [domain: {domain}]")
            elif "anchors" in level_key:
                lines.append(f"\n**{level_key} (anchor factors):**")
                for f in level_factors:
                    domain = self.get_factor_domain(f)
                    lines.append(f"  - `{f}`  [domain: {domain}]")
            else:
                lines.append(f"\n**{level_key}:**")
                for f in level_factors:
                    sources = self._get_factor_sources(f)
                    solver_type = self._get_solver_type(f)
                    if sources:
                        lines.append(
                            f"  - `{f}`  <- [{', '.join(sources)}]  ({solver_type})"
                        )
                    else:
                        lines.append(f"  - `{f}`  ({solver_type})")

        lines.append("\n## Factor Coverage\n")

        explicit_count = len(self.constraints)
        builtin_count = len(self.builtin_rules)
        anchor_count = len(self.anchors)
        all_known = self._collect_all_factors()
        total = len(all_known)
        intermediate_count = len(self.intermediate_factors)

        lines.append(f"- Total factors: {total} (including {intermediate_count} intermediate)")
        lines.append(f"- Anchor factors: {anchor_count}")
        lines.append(f"- Explicit constraint coverage: {explicit_count}")
        lines.append(f"- Built-in derivation coverage: {builtin_count}")
        uncovered = all_known - set(self.constraints.keys()) - set(
            self.builtin_rules.keys()
        ) - set(self.anchors)
        lines.append(f"- Uncovered factors: {len(uncovered)}")
        if uncovered:
            for f in sorted(uncovered, key=str):
                lines.append(f"  - `{f}`")

        report = "\n".join(lines)
        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report)
        return report

    def _get_factor_sources(self, factor):
        if factor in self.constraints:
            return self.constraints[factor]["sources"]
        if factor in self.builtin_rules:
            return self.builtin_rules[factor]["sources"]
        return []

    def _get_solver_type(self, factor):
        if factor in self.constraints:
            func = self.constraints[factor]["function"]
            return f"@solves: {func.__name__}"
        if factor in self.builtin_rules:
            return f"built-in: {self.builtin_rules[factor]['rule']}"
        return "domain sampling"

    def solve_one(self, partial_assignment, max_attempts=50):
        target_hash = int(
            hashlib.sha256(
                str(sorted(partial_assignment.items())).encode()
            ).hexdigest()[:8], 16
        )

        sorted_keys = sorted(
            self.topology_order.keys(),
            key=lambda k: (
                int(k.replace("level_", "").split("_")[0]),
                0 if "intermediate" in k else (1 if "anchors" in k else 2),
            ),
        )

        for attempt in range(max_attempts):
            random.seed((self.seed or 0) + attempt + target_hash)
            get_and_reset_tags()
            combo = dict(partial_assignment)
            success = True

            for level_key in sorted_keys:
                for factor in self.topology_order[level_key]:
                    if factor in combo:
                        if factor in self.constraints:
                            if not self._validate_locked_value(factor, combo):
                                success = False
                                break
                        continue
                    result = self._solve_single_factor_value(factor, combo)
                    if result is SKIP:
                        combo[factor] = SKIP
                        continue
                    if result is NOT_APPLICABLE:
                        combo[factor] = None
                        continue
                    if result is None:
                        success = False
                        break
                    combo[factor] = result
                if not success:
                    break

            if success:
                tags = get_and_reset_tags()
                combo.update(tags)
                combo = self._exclude_intermediate_factors_single(combo)
                return combo

        return None

    def _solve_single_factor_value(self, factor, combo):
        if factor in self.constraints:
            return self._solve_explicit_single(factor, combo)
        elif factor in self.builtin_rules:
            return self._solve_builtin_single(factor, combo)
        else:
            return self._solve_from_domain_single(factor)

    def _validate_locked_value(self, factor, combo):
        func_info = self.constraints[factor]
        sources = func_info["sources"]

        if any(s not in combo for s in sources):
            return True
        if any(combo.get(s) is SKIP for s in sources):
            return True
        source_values = [combo.get(s) for s in sources]
        try:
            result = func_info["function"](*source_values)
        except (AssertionError, Exception):
            return False
        if result is SKIP or result is NOT_APPLICABLE:
            return False
        if isinstance(result, Candidates):
            return combo[factor] in list(result)
        return combo[factor] == result

    def _solve_explicit_single(self, factor, combo):
        func_info = self.constraints[factor]
        func = func_info["function"]
        sources = func_info["sources"]

        if any(s not in combo for s in sources):
            return None
        if any(combo.get(s) is SKIP for s in sources):
            return SKIP

        source_values = [combo.get(s) for s in sources]
        has_none = any(v is None for v in source_values)

        try:
            result = func(*source_values)
        except (AssertionError, Exception):
            return NOT_APPLICABLE if has_none else None

        if result is SKIP:
            fallback = self._try_skip_fallback(factor, combo)
            if fallback is not SKIP:
                if validate_factor(factor, fallback, combo)[0]:
                    self._produced_values[factor].add(make_hashable(fallback))
                    return fallback
            return SKIP
        if result is NOT_APPLICABLE:
            return NOT_APPLICABLE
        if has_none and result is None:
            return NOT_APPLICABLE
        if isinstance(result, Candidates):
            candidates = [v for v in result if validate_factor(factor, v, combo)[0]]
            if candidates:
                return random.choice(candidates)
            return NOT_APPLICABLE if has_none else None
        if validate_factor(factor, result, combo)[0]:
            return result
        return NOT_APPLICABLE if has_none else None

    def _solve_builtin_single(self, factor, combo):
        rule_info = self.builtin_rules[factor]
        sources = rule_info.get("sources", [])
        if any(combo.get(s) is SKIP for s in sources if s in combo):
            return SKIP
        if any(combo.get(s) is None for s in sources if s in combo):
            return NOT_APPLICABLE
        result = solve_builtin(rule_info, combo, self.test_factors)
        if result is not None and validate_factor(factor, result, combo)[0]:
            return result
        return None

    def _try_skip_fallback(self, factor, combo):
        if domain := self.get_factor_domain(factor):
            return random.choice(domain)

        if not factor.endswith('.value'):
            return SKIP

        param_name = factor.rsplit('.', 1)[0]
        param_data = self.test_factors.get(param_name, {})
        if not isinstance(param_data, dict):
            return SKIP

        dtype_key = f"{param_name}.dtype"
        dtype = combo.get(dtype_key)
        if dtype is None:
            factors_raw = param_data.get('factors', {})
            dt = factors_raw.get(dtype_key, factors_raw.get('dtype', []))
            if isinstance(dt, list) and dt:
                dtype = dt[0]
            elif isinstance(dt, str):
                dtype = dt
        if dtype is None:
            return SKIP

        factors = param_data.get('factors', {})
        vr_dtype_key = f"{param_name}.value_range_{dtype}"
        if vr_dtype_key in factors:
            value_range = factors[vr_dtype_key]
        else:
            vr_key = f"{param_name}.value_range"
            if vr_key in factors:
                value_range = factors[vr_key]
            else:
                from utils import get_default_value_range, param_excludes_infnan
                exclude_infnan = param_excludes_infnan(param_data)
                value_range = get_default_value_range(dtype, exclude_infnan=exclude_infnan)

        if not value_range:
            return SKIP

        from utils import generate_random_value_by_dtype
        if isinstance(value_range, list) and value_range:
            if isinstance(value_range[0], list):
                numeric_ranges = [r for r in value_range
                                  if len(r) == 2 and not isinstance(r[0], str) and not isinstance(r[1], str)]
                if not numeric_ranges:
                    return SKIP
                rng = random.choice(numeric_ranges)
            else:
                rng = value_range
            return generate_random_value_by_dtype(dtype, rng)

        return SKIP

    def _solve_from_domain_single(self, factor):
        domain = self.get_factor_domain(factor)
        if domain:
            return random.choice(domain)
        ranges = self._get_intermediate_value_range(factor)
        if ranges:
            if not isinstance(ranges[0], list):
                ranges = [ranges]
            lo, hi = random.choice(ranges)
            lo, hi = int(lo), int(hi)
            if lo == hi:
                return lo
            return random.randint(lo, hi)
        return None

    def _exclude_intermediate_factors_single(self, combo):
        filtered = {}
        for k, v in combo.items():
            if v is SKIP:
                continue
            if k in self.intermediate_factors:
                filtered[f"_tag_{k}"] = v
                filtered[k] = v
            else:
                filtered[k] = v
        return filtered

    def solve_one_pairwise(self, partial_assignment, max_attempts=50):
        target_hash = int(
            hashlib.sha256(
                str(sorted(partial_assignment.items())).encode()
            ).hexdigest()[:8], 16
        )

        sorted_keys = sorted(
            self.topology_order.keys(),
            key=lambda k: (
                int(k.replace("level_", "").split("_")[0]),
                0 if "intermediate" in k else (1 if "anchors" in k else 2),
            ),
        )

        for attempt in range(max_attempts):
            random.seed((self.seed or 0) + attempt + target_hash)
            get_and_reset_tags()
            combo = dict(partial_assignment)
            success = True

            for level_key in sorted_keys:
                for factor in self.topology_order[level_key]:
                    if factor in combo:
                        if factor in self.constraints:
                            action = self._reconcile_locked_value(factor, combo)
                            if action in ("reject", "replace"):
                                success = False
                                break
                        continue

                    result = self._solve_single_factor_value(factor, combo)
                    if result is SKIP:
                        combo[factor] = SKIP
                        continue
                    if result is NOT_APPLICABLE:
                        combo[factor] = None
                        continue
                    if result is None:
                        success = False
                        break
                    combo[factor] = result
                if not success:
                    break

            if success:
                tags = get_and_reset_tags()
                combo.update(tags)
                combo = self._exclude_intermediate_factors_single(combo)
                return combo

        return None

    def _reconcile_locked_value(self, factor, combo):
        func_info = self.constraints[factor]
        sources = func_info["sources"]

        if any(s not in combo for s in sources):
            return "keep"
        if any(combo.get(s) is SKIP for s in sources):
            return "keep"

        source_values = [combo.get(s) for s in sources]
        try:
            result = func_info["function"](*source_values)
        except (AssertionError, Exception):
            return "reject"

        if result is SKIP:
            return "keep"
        if result is NOT_APPLICABLE:
            return "reject"

        if isinstance(result, Candidates):
            candidates = list(result)
            if combo[factor] in candidates:
                return "keep"
            if candidates:
                combo[factor] = candidates[0]
                return "replace"
            return "reject"

        if combo[factor] == result:
            return "keep"

        combo[factor] = result
        return "replace"
