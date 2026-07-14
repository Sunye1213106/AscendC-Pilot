"""Explicit Stage Validator entry point; retained validate_facts.py delegates here."""
from understand_operator.scripts.validate_facts import main, validate_facts

__all__ = ["main", "validate_facts"]

if __name__ == "__main__":
    raise SystemExit(main())
