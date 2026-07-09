from collections import defaultdict, deque


class ConstraintGraph:
    def __init__(self, constraints, builtin_rules):
        self.constraints = constraints
        self.builtin_rules = builtin_rules
        self.all_rules = {**constraints, **builtin_rules}

        self.source_to_targets = defaultdict(list)
        for target, info in self.all_rules.items():
            for source in info["sources"]:
                self.source_to_targets[source].append(target)

        self._ancestor_cache = {}

    def get_ancestors(self, factor):
        if factor in self._ancestor_cache:
            return self._ancestor_cache[factor]

        ancestors = set()
        if factor in self.all_rules:
            for source in self.all_rules[factor]["sources"]:
                ancestors.add(source)
                ancestors.update(self.get_ancestors(source))

        self._ancestor_cache[factor] = ancestors
        return ancestors

    def classify_pair(self, f1, f2):
        anc_f1 = self.get_ancestors(f1)
        anc_f2 = self.get_ancestors(f2)

        if f1 in anc_f2 or f2 in anc_f1:
            return "ancestor_descendant"

        if anc_f1 & anc_f2:
            return "common_ancestor"

        return "independent"

    def find_shortest_constraint_path(self, source, target, max_depth=6):
        queue = deque([(source, [source])])
        visited = {source}
        while queue:
            current, path = queue.popleft()
            if len(path) > max_depth:
                continue
            for t in self.source_to_targets.get(current, []):
                if t == target:
                    return path + [t]
                if t not in visited:
                    visited.add(t)
                    queue.append((t, path + [t]))
        return None
