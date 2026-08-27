# PROVED — dtype selects schMode (atomic certificates)

## Source

Host + kernel excerpts from `TEST/.../add_example/`.

## Propositions

Two atomic certificates. Engine composes them after both are accepted.

**Certificate A (`certificate-host.yaml`)** `claim.layer: host`

`P`: host sees `dataType == ge::DT_FLOAT` ⇒ `Q`: Host writes `schMode == ELEMENTWISE_TPL_SCH_MODE_0`.

**Certificate B (`certificate-kernel.yaml`)** `claim.layer: kernel`

`P`: template `schMode == ELEMENTWISE_TPL_SCH_MODE_0` ⇒ `Q`: kernel selects `TILING_KEY_EXAMPLE_FLOAT` branch.

Do not merge these into one `layer: host` certificate that also cites kernel facts.

## Correct verdict

Both `PROVED`. Writers / calls completeness stay `partial` (no closure receipt). Call-graph and completeness obligations are `NA` — they do not apply to these local P⇒Q claims.

After accept:

```text
accepted A + accepted B
→ engine compose
→ host dtype FLOAT ⇒ kernel float specialization
```

## Why

Host write and kernel consume share `ELEMENTWISE_TPL_SCH_MODE_0`. Each certificate stays inside its declared layer. No counterexample arm for float→int32 on the cited window.
