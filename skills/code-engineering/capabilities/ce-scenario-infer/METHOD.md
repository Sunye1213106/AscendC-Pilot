# CE Scenario Infer Method

Produce or audit a `ce-scenario-set/v1` after UO freshness is confirmed.

## Static (no diff)

1. Query `kernel_api` for Cast / DataCopy / DataCopyPad / EnQue / DeQue.
2. Query `buffer` and split-field writers (`field` / `tiling_data`).
3. Map each hit with the catalog table. Do not invent ids.
4. Attach `origin: inferred` and default budgets from the catalog.

## Diff

1. Confirm change capture SHA and UO `source_revision` / fingerprint.
2. Resolve anchors from diff spans against **all** CodeMap kinds
   (OPERATION, BUFFER, BRANCH, KERNEL, not only Host writers).
3. Slice forward/backward on useful edges; keep `truncated`.
4. Map anchors to scenario ids. Truncation → `blind_spots`, not empty impact.
5. One obligation per scenario item; precision/perf stay `external` until
   `ce-external-evidence/v1` receipts exist.

## Forbidden

- Closing precision or perf with review text.
- Treating Host-only impact as complete for a kernel-only diff.
- Expanding into `tilingkey_full_coverage` from a scenario overlay.
