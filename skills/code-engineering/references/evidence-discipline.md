# Evidence Discipline

For every CE conclusion record:

1. claim or obligation id;
2. source/version fingerprint;
3. evidence references and Tier A/B/C;
4. derivation parameters and scope boundary;
5. result, uncertainty, and invalidation conditions.

The ledger is append-preserving:

```text
Open = O - V - X
```

`O` keeps all identified obligations. `V` contains obligations closed by
verification. `X` contains only referee-approved non-applicable obligations.
Never erase an obligation to make `Open` smaller, and never use Tier C evidence
to place an item in `V` or `X`.

Report stale products, missing source, unsupported edges, truncated slices, and
external-system dependencies as boundaries. Do not silently convert them into
negative findings.
