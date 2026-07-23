"""Compat shim — use finalize_scope.py."""
from uo.scripts.finalize_scope import *  # noqa: F403
from uo.scripts.finalize_scope import finalize_scope, main

finalize_phase0 = finalize_scope

if __name__ == "__main__":
    raise SystemExit(main())
