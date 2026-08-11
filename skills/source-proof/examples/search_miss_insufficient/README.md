# INSUFFICIENT — Grep miss is not absence

## Source pattern

Aligned with cannbot / Pilot evidence policy: locate ≠ proof.

## Given

A lead claims “no other SetTilingKey writers” after one Grep with a narrow pattern that misses `GET_TPL_TILING_KEY` indirection.

## Correct verdict

`INSUFFICIENT` (or keep obligations OPEN). Must not emit PROVED_UNREACHABLE / exclusion.

## Why

Search failure and partial index cannot close absence obligations.
