# lemma_mine

Domain: `skills/domain/source-lemma-proof/SKILL.md`

Inputs: Bundle targets + Task Prompt context/evidence.
Output: per Runtime output contract (do not invent paths).
Cannot decide: unresolved / needs_human; do not guess.

## Staging contract (`tg-lemma-mine-staging/v1`)

Each candidate in `runs/<run_id>/actions/lemma_mine/parts/*.yaml` must include:

| field | requirement |
|---|---|
| `proposition` | P ⇒ Q statement grounded in the lead |
| `codemap_anchors` | list of `{entity_id or relation_id, query}` |
| `obligations` | list of `{id, status, evidence}` with status in OPEN/CLOSED/BLOCKED |
| `source_citations` | list of `{file, line, quote}` |
| `verdict` | PROVED \| REFUTED \| INSUFFICIENT |

## PROVED gate

- `lemma_apply` rejects empty or placeholder-only parts.
- Accepted entries must have `verdict: PROVED` and all obligations CLOSED.
- REFUTED / INSUFFICIENT may be recorded but do not promote to E without referee acceptance.
