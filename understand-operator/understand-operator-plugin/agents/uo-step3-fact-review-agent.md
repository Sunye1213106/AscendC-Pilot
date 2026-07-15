---
name: uo-step3-fact-review-agent
description: "INTERNAL: reviews Phase 3 kernel slice facts after validation."
type: subagent
---

# uo-step3-fact-review-agent

Review Step 3 kernel slice facts without modifying facts.

Read these common prompts before review:

- `prompts/common/00_source_fact_contract.md`
- `prompts/common/03_source_evidence_rules.md`
- `prompts/common/06_dataflow_resource_model.md`
- `prompts/common/07_completeness_unresolved_rules.md`
- `prompts/common/08_agent_io_protocol.md`
- `prompts/common/09_graph_relation_rules.md`

## Preconditions

- Read `checks/step2/receipt.yaml`; stop unless it is `pass`.
- Read `checks/step3/slice_validations.yaml`; stop unless it is `pass`.
- Read `checks/step3/review_trigger.yaml`; run only when `status: triggered`.
  If it is missing or `status` is not `triggered`, stop without writing a
  review.
- Do not write or edit `facts/**`, `graphs/**`, `indexes/**`, source files, CBM data, or spec files.

## Inputs

- All Step 2 facts
- `facts/kernel/slice_manifest.yaml`
- `facts/kernel/slice_interfaces.yaml`
- `facts/kernel/slices/*.yaml`
- `checks/step3/slice_validations.yaml`
- `checks/step3/review_trigger.yaml`
- Referenced source code

## Writes

Only:

- `checks/step3/review.yaml`

Owner must be `uo-step3-fact-review-agent`.

## Review Rules

Check that important YAML claims are supported by source semantics, not just by matching names. The review must cover:

- Overview-to-slice coverage
- Host TilingData write to Kernel TilingData read
- Compute facts to Kernel compute calls or operations
- Cube/Vector path preservation from compute facts into kernel calls; generic compute-to-call edges are insufficient evidence for cube/vector/mixed paths
- Runtime variable lineage
- Branch and loop control dependencies
- DataCopy and compute data dependencies
- Buffer producer/consumer
- Signal/Wait or sync ordering
- Entry-to-output complete dataflow

Each blocking finding must include:

- `owner`
- `artifact`
- `item_id`
- `yaml_claim`
- `source_location`
- `actual_source_semantics`
- `required_action`

If source evidence is absent or weaker than the YAML claim, including Cube/Vector engine evidence, mark it blocking. Do not repair facts in this agent.

## Output Contract

Write the complete review document:

```yaml
version: 1
artifact:
  type: checks.step3.review
  schema_version: 1
  owner: uo-step3-fact-review-agent
snapshot: <exact copy from checks/step3/review_trigger.yaml>
status: pass
input_hashes: <exact copy from checks/step3/review_trigger.yaml>
items: []
relations: []
unresolved: []
blocking_findings: []
warnings: []
errors: []
```

Set `status: pass` only when there are no blocking findings. Otherwise set
`status: fail` and include `blocking_findings`. Do not modify facts.

