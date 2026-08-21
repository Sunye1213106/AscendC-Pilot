# Cast-only diff infers precision scenarios

## Given

Impact slice anchors include OPERATION `Cast`.

## Task (CE)

Infer ScenarioSet from the slice. Do not invent ids outside the catalog.

## Correct outcome

`P-CAST` and `P-DTYPE` only. Truncation of the slice is not “no precision impact”.
