# CE Impact Audit Method

Audit the impact ledger after deterministic slicing and risk classification.

1. Confirm the change capture and UO fingerprint identify the reviewed source.
2. Reproduce forward and backward slices from every changed anchor. Record
   direction, edge filters, depth, budget, and `truncated`.
3. Check that every material impacted node or boundary produced an obligation
   in `O`; do not treat absence beyond a budget boundary as exclusion.
4. Check risk classes against source and relation evidence.
5. Recompute `Open = O - V - X`.
6. Reject any entry in `V` or `X` supported only by Tier C evidence.
7. Return pass only when omissions and slice boundaries are explicit and the
   ledger is internally consistent. External precision/performance claims stay
   open until their measurements are supplied.
