class Candidates(list):
    pass


class _Skip:
    def __repr__(self):
        return "SKIP"


class _NotApplicable:
    def __repr__(self):
        return "NOT_APPLICABLE"


SKIP = _Skip()
NOT_APPLICABLE = _NotApplicable()


class ConstraintRegistry:
    def __init__(self):
        self._registry = {}

    def register(self, target, sources, func):
        if target in self._registry:
            import inspect

            prev_func = self._registry[target]["function"]
            prev_file = inspect.getfile(prev_func)
            prev_line = inspect.getsourcelines(prev_func)[1]
            new_file = inspect.getfile(func)
            new_line = inspect.getsourcelines(func)[1]
            raise ValueError(
                f"Duplicate @solves target '{target}': "
                f"previously registered at {prev_file}:{prev_line}, "
                f"conflicting at {new_file}:{new_line}"
            )
        self._registry[target] = {
            "function": func,
            "sources": sources,
            "target": target,
        }

    def get_all(self):
        return dict(self._registry)

    def get(self, target):
        return self._registry.get(target)

    def clear(self):
        self._registry.clear()


_active_registry = None


def get_active_registry():
    global _active_registry
    if _active_registry is None:
        _active_registry = ConstraintRegistry()
    return _active_registry


def set_active_registry(registry):
    global _active_registry
    _active_registry = registry


def solves(target, sources):
    def decorator(func):
        get_active_registry().register(target, sources, func)
        return func

    return decorator
