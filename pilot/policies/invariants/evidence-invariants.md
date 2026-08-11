# Evidence invariants (model-facing, short)

1. Search / UO graph locate ≠ proof. High confidence needs a disk source window.
2. `confidence: high` / `source_verified: true` requires **both**:
   - `evidence_window_sha256` for the cited `path:line` window
   - continuous `evidence_snippet` that is a substring of that window
3. Never invent hashes, line numbers, or pasted non-contiguous snippets.
4. Neighbor / wrong-window sha reuse is fabrication → reject.
5. Absence claims need machine-checkable negative evidence, not “I searched a lot”.
6. Intermediate locals are never input roots; ungrounded surfaces stay unresolved.

Full detail: `pilot/policies/evidence/POLICY.md`.
