# code-engineering (CE)

AscendC Code Engineering engine: PR → impact (via CodeMap) → regression cases
(via TG closure corpus).

## Dependencies

Declared in `pyproject.toml`:

```toml
dependencies = ["PyYAML>=6.0"]
```

Sibling engines are **not** path-deps inside this `pyproject.toml`. The repo
root installs them together as editable packages (same pattern as
`testcase-generation` depending on `acp-common` by package name, resolved via
workspace install):

```text
# requirements.txt (repo root)
-e ./engines/common
-e ./engines/understand-operator
-e ./engines/testcase-generation[ml]
-e ./engines/code-engineering
```

CE currently imports only PyYAML; it does not declare `acp-common` / `uo-init`
until those packages are imported by CE modules.
