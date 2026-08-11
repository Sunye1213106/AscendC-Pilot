# -*- coding: utf-8 -*-
"""AscendC / CANN storage-type catalog for Kernel Execution modeling.

Sources (CANN asc-devkit):
  - ``AscendC::Reg`` / ``MicroAPI = Reg`` → REGISTER (RegTensor, MaskReg, ...)
  - ``LocalTensor`` / ``GlobalTensor`` / ``TQue`` / ``TBuf`` → BUFFER
  - ``TPosition`` / ``QuePosition`` template args → memory_space
  - Wrapper types (e.g. ``MutexBuffer<BufferType, SyncType>``) compose a
    CANN storage root (LocalTensor/GlobalTensor at a TPosition) + sync policy.
    Model the wrapper as a TYPE with ``role=storage_wrapper_type`` that
    ``WRAPS`` / ``ROOTED_AT`` AscendC LocalTensor — not as an AscendC buffer
    kind. Decl sites keep ``role=storage_wrapper`` + file:line for location.
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

# Direct AscendC tensor/queue types.
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

# Types that wrap a CANN LocalTensor/GlobalTensor (+ sync). Not name-based.
ASCENDC_STORAGE_WRAPPER_TYPES: frozenset[str] = frozenset(
    {
        "MutexBuffer",
        # fa_base_matmul::Buffer / similar position-templated wrappers
        "Buffer",
    }
)

# Multi-buffer policies that wrap MutexBuffer (hence LocalTensor).
ASCENDC_STORAGE_POLICY_TYPES: frozenset[str] = frozenset(
    {
        "MutexBuffersPolicySingleBuffer",
        "MutexBuffersPolicyDB",
        "MutexBuffersPolicy3buff",
        "MutexBuffersPolicy4buff",
        "MutexMatrix2x2BufferPolicy",
        "MutexBufferManager",
    }
)

# Method spellings that collide with AscendC TQue/TBuf APIs but, on a
# MutexBuffer / policy receiver, are view accessors → LocalTensor.
STORAGE_VIEW_ACCESSORS: frozenset[str] = frozenset(
    {
        "Get",
        "GetTensor",
        "GetPre",
        "GetReused",
        "GetVec",
        "GetCube",
        "GetFree",
        "AllocNext",
        "ReuseNext",
        "FreeNext",
        "PeekNextK",
        "PeekBuffer",
        "GetBuffer",
    }
)

ASCENDC_NON_STORAGE_TYPES: frozenset[str] = frozenset({"TPipe"})

BUFFER_MEMORY_SPACES: frozenset[str] = frozenset(
    {"GM", "UB", "L1", "L0A", "L0B", "L0C", "QUEUE", "WORKSPACE", "C2"}
)

# CANN AscendC TPosition / QuePosition → logical memory space.
# (kernel_tpipe.h / matmul TPosition usage)
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

# Common BufferType enums used with AscendC TPosition (ops-transformer buffer.h
# and equivalent). Keys are enum enumerators, not variable names.
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
    """True for types that wrap a CANN LocalTensor/GlobalTensor (+ sync)."""
    text = str(type_text or "")
    if "MutexBuffer" in text:
        return True
    # Bare ``Buffer`` is ambiguous (BufferType, ...); require template form.
    if re.search(r"\bBuffer\s*<", text):
        return True
    return False


def wrapper_family_from_type(type_text: str) -> str:
    """Classify project storage-wrapper / policy family from a type spelling.

    Returns empty string when the type is a direct AscendC buffer (TQue/…)
    or unrelated — so ``Get``/``GetTensor`` keep their AscendC roots.
    """
    text = str(type_text or "")
    if not text:
        return ""
    if any(p in text for p in ASCENDC_STORAGE_POLICY_TYPES) or "MutexBuffersPolicy" in text:
        return "MutexBuffersPolicy"
    if "MutexBufferManager" in text:
        return "MutexBufferManager"
    if "MutexBuffer" in text:
        return "MutexBuffer"
    if re.search(r"\bBuffer\s*<", text):
        return "Buffer"
    return ""


def is_storage_view_accessor(callee: str) -> bool:
    return str(callee or "").split("::")[-1] in STORAGE_VIEW_ACCESSORS


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
    # BufferType::L1 / BufferType::L0A / ...
    for enum_name, space in BUFFER_TYPE_TO_SPACE.items():
        token = f"BufferType::{enum_name}"
        if token in text:
            return space
    # TPosition::A1 / QuePosition::VECIN / TQue<QuePosition::VECIN, ...>
    for pos, space in TPOSITION_TO_SPACE.items():
        if f"TPosition::{pos}" in text or f"QuePosition::{pos}" in text:
            return space
    # Bare LocalTensor / GlobalTensor without position → default spaces
    if "GlobalTensor" in text:
        return "GM"
    if "LocalTensor" in text:
        return "UB"
    if "TQue" in text or "TQueBind" in text:
        return "QUEUE"
    if "TBuf" in text:
        return "UB"
    return None


def storage_root_kind_from_space(memory_space: str) -> str:
    """Underlying CANN tensor kind for a resolved memory space."""
    if memory_space == "GM":
        return "GlobalTensor"
    return "LocalTensor"


def resolve_buffer_decl(type_text: str) -> dict[str, Any] | None:
    """Classify a buffer/wrapper decl into CodeMap-oriented fields.

    Returns None if not a buffer/wrapper type.
    Wrappers always declare a CANN storage root kind (LocalTensor/GlobalTensor),
    even when BufferType/TPosition is still a dependent template parameter.
    """
    text = str(type_text or "")
    if register_class_from_type(text) or is_non_storage_type(text):
        return None
    if not is_buffer_type(text):
        return None

    wrapper = is_storage_wrapper_type(text)
    if "MutexBuffer" in text:
        kind = "MutexBuffer"
    elif wrapper:
        kind = "Buffer"
    else:
        kind = next((t for t in ASCENDC_BUFFER_TYPES if t in text), "Buffer")

    space = memory_space_from_type_text(text) or "UNKNOWN"

    out: dict[str, Any] = {
        "kind": kind,
        "memory_space": space,
        "role": "storage_wrapper" if wrapper else "cann_storage",
        "is_wrapper": wrapper,
    }
    if wrapper:
        # MutexBuffer always wraps LocalTensor (see mutex_buffer.h TensorType).
        # Other BufferType::GM wrappers may use GlobalTensor.
        if "MutexBuffer" in text:
            out["storage_root_kind"] = "LocalTensor"
        else:
            out["storage_root_kind"] = storage_root_kind_from_space(
                space if space != "UNKNOWN" else "UB"
            )
        if space != "UNKNOWN":
            out["tposition_space"] = space
    return out
