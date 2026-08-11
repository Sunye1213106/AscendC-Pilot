# -*- coding: utf-8 -*-
"""AscendC / CANN storage-type catalog for Kernel Root Trace.

Terminal storage / register roots and known framework wrapper contracts.
Project-specific policy / selector class names are never catalogued here —
they must be discovered via source composition (WRAPS / ALIASES).
"""

from __future__ import annotations

import re
from typing import Any

# type spelling (as written in operator / CANN headers) → register_class
ASCENDC_REGISTER_TYPES: dict[str, str] = {
    "RegTensor": "VREG",
    "MaskReg": "MASK_REG",
    "UnalignReg": "UNALIGN_REG",
    "UnalignRegForLoad": "UNALIGN_REG",
    "UnalignRegForStore": "UNALIGN_REG",
    "AddrReg": "ADDR_REG",
}

# Direct AscendC tensor/queue types (terminal storage roots).
ASCENDC_BUFFER_TYPES: frozenset[str] = frozenset(
    {
        "LocalTensor",
        "GlobalTensor",
        "TBuf",
        "TQue",
        "TQueBind",
        "TBufPool",
    }
)

# Framework wrappers with a known CANN-backed storage contract (outside project
# source scope). Not AscendC buffer kinds — they WRAPS → LocalTensor.
ASCENDC_STORAGE_WRAPPER_TYPES: frozenset[str] = frozenset(
    {
        "MutexBuffer",
        # Position-templated framework Buffer<> (ambiguous bare Buffer is handled
        # only when written as Buffer<...>).
        "Buffer",
    }
)

# External framework methods on MutexBuffer whose bodies are not in project
# source. Bridge to AscendC roots only when the receiver is a storage wrapper.
MUTEX_BUFFER_METHOD_BRIDGES: dict[str, tuple[str, str]] = {
    # method → (AscendC root spelling, root_kind)
    "LockProd": ("Lock", "SYNC"),
    "UnlockProd": ("Unlock", "SYNC"),
    "LockCons": ("Lock", "SYNC"),
    "UnlockCons": ("Unlock", "SYNC"),
    "Get": ("LocalTensor", "STORAGE"),
    "GetTensor": ("LocalTensor", "STORAGE"),
    "GetPre": ("LocalTensor", "STORAGE"),
    "GetReused": ("LocalTensor", "STORAGE"),
}

ASCENDC_NON_STORAGE_TYPES: frozenset[str] = frozenset({"TPipe"})

BUFFER_MEMORY_SPACES: frozenset[str] = frozenset(
    {"GM", "UB", "L1", "L0A", "L0B", "L0C", "QUEUE", "WORKSPACE", "C2"}
)

# CANN AscendC TPosition / QuePosition → logical memory space.
TPOSITION_TO_SPACE: dict[str, str] = {
    "GM": "GM",
    "VECIN": "UB",
    "VECOUT": "UB",
    "VECCALC": "UB",
    "A1": "L1",
    "B1": "L1",
    "C1": "L1",
    "A2": "L0A",
    "B2": "L0B",
    "CO1": "L0C",
    "CO2": "L0C",
    "C2": "C2",
    "LCM": "UB",
}

# Common BufferType enums used with AscendC TPosition.
BUFFER_TYPE_TO_SPACE: dict[str, str] = {
    "L1": "L1",
    "L0A": "L0A",
    "L0B": "L0B",
    "L0C": "L0C",
    "UB": "UB",
    "GM": "GM",
    "C2": "C2",
}

_CXX_KEYWORDS = frozenset(
    {
        "this",
        "true",
        "false",
        "nullptr",
        "return",
        "sizeof",
        "alignof",
        "if",
        "else",
        "for",
        "while",
        "switch",
        "case",
        "default",
        "break",
        "continue",
        "const",
        "constexpr",
        "static",
        "volatile",
        "typedef",
        "using",
        "namespace",
        "class",
        "struct",
        "enum",
        "template",
        "typename",
        "public",
        "private",
        "protected",
        "virtual",
        "inline",
        "new",
        "delete",
        "operator",
        "Min",
        "Max",
        "Ceil",
        "AlignUp",
        "AlignDown",
    }
)


def register_class_from_type(type_text: str) -> str | None:
    text = str(type_text or "")
    for spelling, klass in ASCENDC_REGISTER_TYPES.items():
        if spelling in text:
            return klass
    return None


def is_buffer_type(type_text: str) -> bool:
    text = str(type_text or "")
    if any(t in text for t in ASCENDC_BUFFER_TYPES):
        return True
    return is_storage_wrapper_type(text)


def is_storage_wrapper_type(type_text: str) -> bool:
    """True for framework types that wrap a CANN LocalTensor/GlobalTensor."""
    text = str(type_text or "")
    if "MutexBuffer" in text:
        return True
    if re.search(r"\bBuffer\s*<", text):
        return True
    return False


def is_non_storage_type(type_text: str) -> bool:
    text = str(type_text or "")
    return any(t in text for t in ASCENDC_NON_STORAGE_TYPES)


def is_storage_type_text(type_text: str) -> bool:
    return bool(register_class_from_type(type_text) or is_buffer_type(type_text))


def is_valid_storage_name(name: str) -> bool:
    text = str(name or "").strip()
    if not text or text in _CXX_KEYWORDS:
        return False
    return text.isidentifier()


def memory_space_from_type_text(type_text: str) -> str | None:
    """Resolve memory_space from CANN/AscendC position template args — not names."""
    text = str(type_text or "")
    for enum_name, space in BUFFER_TYPE_TO_SPACE.items():
        token = f"BufferType::{enum_name}"
        if token in text:
            return space
    for pos, space in TPOSITION_TO_SPACE.items():
        if f"TPosition::{pos}" in text or f"QuePosition::{pos}" in text:
            return space
    if "GlobalTensor" in text:
        return "GM"
    if "LocalTensor" in text:
        return "UB"
    if "TQue" in text or "TQueBind" in text:
        return "QUEUE"
    if "TBuf" in text or "TBufPool" in text:
        return "UB"
    return None


def storage_root_kind_from_space(space: str) -> str:
    if space == "GM":
        return "GlobalTensor"
    if space == "QUEUE":
        return "TQue"
    return "LocalTensor"


def resolve_buffer_decl(type_text: str) -> dict[str, Any] | None:
    """Classify a decl type_text into storage metadata (no name heuristics)."""
    text = str(type_text or "")
    if not text:
        return None
    if register_class_from_type(text):
        return None
    if is_non_storage_type(text):
        return None
    wrapper = is_storage_wrapper_type(text)
    if not (wrapper or any(t in text for t in ASCENDC_BUFFER_TYPES)):
        return None
    space = memory_space_from_type_text(text) or "UNKNOWN"
    root = "LocalTensor" if wrapper else (
        "GlobalTensor"
        if "GlobalTensor" in text
        else (
            "TQue"
            if "TQue" in text
            else ("TBuf" if "TBuf" in text else storage_root_kind_from_space(space))
        )
    )
    if "LocalTensor" in text and not wrapper:
        root = "LocalTensor"
    return {
        "is_wrapper": wrapper,
        "memory_space": space,
        "storage_root_kind": root,
    }
