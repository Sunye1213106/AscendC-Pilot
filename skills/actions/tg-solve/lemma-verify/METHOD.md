# lemma_verify

Domain: `skills/domain/tg-closure/SKILL.md`

Inputs: `runs/<run_id>/actions/lemma_mine/parts/*.yaml` candidates + the R ledger.
Output: `runs/<run_id>/actions/lemma_verify/verify.yaml` (`tg-lemma-verify/v1`).
Deterministic engine — no judgement, no source reading.

## What it decides

Each candidate's `when` is projected onto every witness in R. A candidate that
some witness satisfies claims a reachable key is unreachable, so it is refuted
no matter how the proof reads. Refutations carry the witnesses that killed them
so the producer can narrow the antecedent instead of guessing.

| field | meaning |
|---|---|
| `candidates` | non-placeholder candidates read from mine parts |
| `survivors` | candidates no witness contradicts |
| `refuted` | `{label, hits, counterexamples}` per killed candidate |
| `closes` | open keys the survivors would exclude |

## Placement

Runs after `lemma_mine` and before `lemma_review`: refuting a candidate costs a
set intersection, while a referee reviewing it costs a subagent turn.

`lemma_apply` repeats the same check on the accepted set and fails with
`REFUTED_BY_R`, so a referee cannot accept a candidate R already disproved.
