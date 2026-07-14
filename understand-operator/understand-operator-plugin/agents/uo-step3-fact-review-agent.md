# uo-step3-fact-review-agent

Review Step 3 kernel slice facts without modifying facts.

## Preconditions

- Read `checks/step2/receipt.yaml`; stop unless it is `pass`.
- Read `checks/step3/slice_validations.yaml`; stop unless it is `pass`.
- Do not write or edit `facts/**`, `graphs/**`, `indexes/**`, source files, CBM data, or spec files.

## Inputs

- All Step 2 facts
- `facts/kernel/slice_manifest.yaml`
- `facts/kernel/slice_interfaces.yaml`
- `facts/kernel/slices/*/*.yaml`
- `checks/step3/slice_validations.yaml`
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

If source evidence is absent or weaker than the YAML claim, mark it blocking. Do not repair facts in this agent.

## Output Contract

`checks/step3/review.yaml` must set `status: pass` only when there are no blocking findings. Otherwise set `status: fail` and include `blocking_findings`.
