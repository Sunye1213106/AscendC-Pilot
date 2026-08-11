# -*- coding: utf-8 -*-
"""Generic TilingData decoder — layout comes from UO, never an operator name.

When layout facts are incomplete, callers must load a Local Extension
``tilingdata_decoder`` under ``<op>/.ascendc-pilot/<arch>/local/``.
"""

from __future__ import annotations

from typing import Any, Mapping


class LayoutIncomplete(Exception):
    """UO layout cannot drive a generic decode — need Local Extension."""

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(
            "LOCAL_CAPABILITY_REQUIRED interface=tilingdata_decoder "
            f"reason=UO_LAYOUT_INCOMPLETE detail={detail}"
        )


def decode(raw: bytes | bytearray, layout: Mapping[str, Any] | None) -> dict[str, Any]:
    """Decode ``raw`` using ``layout`` facts from ``.uo`` / projection.

    ``layout`` is expected to describe fields with at least offset + size
    (or a struct format string). Nested / variant layouts that UO cannot yet
    express raise ``LayoutIncomplete``.
    """
    if not layout:
        raise LayoutIncomplete("empty layout")
    fields = layout.get("fields") if isinstance(layout, Mapping) else None
    if not isinstance(fields, list) or not fields:
        raise LayoutIncomplete("layout.fields missing")

    out: dict[str, Any] = {}
    buf = memoryview(raw)
    for field in fields:
        if not isinstance(field, Mapping):
            raise LayoutIncomplete("non-mapping field")
        name = str(field.get("name") or "")
        if not name:
            raise LayoutIncomplete("field without name")
        if field.get("variant_guard") or field.get("nested"):
            raise LayoutIncomplete(f"unsupported field shape for {name}")
        try:
            offset = int(field["offset"])
            size = int(field["size"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LayoutIncomplete(f"field {name}: {exc}") from exc
        if offset < 0 or size < 0 or offset + size > len(buf):
            raise LayoutIncomplete(f"field {name}: out of range")
        chunk = bytes(buf[offset : offset + size])
        endian = str(field.get("endian") or "little")
        kind = str(field.get("type") or "uint").lower()
        if "float" in kind and size == 4:
            import struct

            out[name] = struct.unpack_from("<f" if endian.startswith("l") else ">f", chunk)[0]
        elif "float" in kind and size == 8:
            import struct

            out[name] = struct.unpack_from("<d" if endian.startswith("l") else ">d", chunk)[0]
        else:
            out[name] = int.from_bytes(chunk, endian if endian in ("little", "big") else "little")
    return out
