# Graph Relation Rules

Fact items become raw nodes. Fact relations become raw edges. Relations do not also create nodes.

Raw graph entries must trace back to YAML pointers and source anchors. Raw graph must not contain family, L0/L1/L2, or derived-view abstractions.

Cross-layer links may use only stable IDs and explicit structural fields such as `field_ref`, `struct_ref`, `operation_ref`, `buffer_ref`, `event_identifier`, or explicit interface refs. Do not connect facts by fuzzy natural-language similarity.
