# Agent IO Protocol

Read the relevant Phase receipt before writing facts. Write only paths allowed by `spec/ownership.yaml`.

Business agents do not write validator reports. Python validators are the only writers of `checks/*validation.yaml`.

Parallel agents must not modify shared files. Agents must not relax schemas or ownership rules.
