from __future__ import annotations

from typing import Any


def decode_tiling_key(tiling_key: int, key_space: dict[str, Any]) -> dict[str, Any]:
    fields = key_space.get("fields", {}) or {}
    decoded: dict[str, Any] = {}
    for name, spec in fields.items():
        bits = spec.get("bits") or []
        if not bits:
            if "constant" in spec:
                decoded[name] = spec["constant"]
            continue
        lo = min(bits)
        hi = max(bits)
        width = hi - lo + 1
        mask = (1 << width) - 1
        decoded[name] = (tiling_key >> lo) & mask
    return decoded


def encode_tiling_key(decoded: dict[str, Any], key_space: dict[str, Any]) -> int:
    fields = key_space.get("fields", {}) or {}
    value = 0
    for name, field_val in decoded.items():
        spec = fields.get(name, {})
        bits = spec.get("bits") or []
        if not bits:
            continue
        lo = min(bits)
        width = max(bits) - lo + 1
        value |= (int(field_val) & ((1 << width) - 1)) << lo
    return value
