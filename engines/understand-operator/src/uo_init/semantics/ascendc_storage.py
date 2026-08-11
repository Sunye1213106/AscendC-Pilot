# -*- coding: utf-8 -*-
"""AscendC / CANN storage-type catalog for Kernel Execution modeling.

Source of truth (dav_3510 / arch35 MicroAPI):
  cann-asc-devkit/.../tikcfw/impl/kernel_macros.h
      ``namespace MicroAPI = Reg;``
  cann-asc-devkit/.../interface/reg_compute/kernel_reg_compute_struct_intf.h
      ``AscendC::Reg::RegTensor<T>``
  cann-asc-devkit/.../interface/reg_compute/kernel_reg_compute_common_intf.h
      ``MaskReg``, ``UnalignReg*``, ``AddrReg``

These are register-file objects, not UB/GM buffers. Model them as REGISTER
entities with a register_class, keep BUFFER for LocalTensor/GlobalTensor/TQue/...
"""

from __future__ import annotations

# type spelling (as written in operator / CANN headers) → register_class
ASCENDC_REGISTER_TYPES: dict[str, str] = {
    "RegTensor": "VREG",
    "MaskReg": "MASK_REG",
    "UnalignReg": "UNALIGN_REG",
    "UnalignRegForLoad": "UNALIGN_REG",
    "UnalignRegForStore": "UNALIGN_REG",
    "AddrReg": "ADDR_REG",
}

# Memory / queue tensor types (BUFFER ontology).
ASCENDC_BUFFER_TYPES: frozenset[str] = frozenset(
    {
        "LocalTensor",
        "GlobalTensor",
        "TBuf",
        "TQue",
        "MutexBuffer",
    }
)

# TPipe is a host-side pipe object, not data storage.
ASCENDC_NON_STORAGE_TYPES: frozenset[str] = frozenset({"TPipe"})

# Memory spaces that count as Tensor/queue buffers (not register file).
BUFFER_MEMORY_SPACES: frozenset[str] = frozenset(
    {"GM", "UB", "L1", "L0A", "L0B", "L0C", "QUEUE", "WORKSPACE"}
)

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
        "Min",  # often a callee leaked into arg text
        "Max",
        "Ceil",
        "AlignUp",
        "AlignDown",
    }
)


def register_class_from_type(type_text: str) -> str | None:
    """Return register_class if ``type_text`` mentions an AscendC Reg* type."""
    text = str(type_text or "")
    for spelling, klass in ASCENDC_REGISTER_TYPES.items():
        if spelling in text:
            return klass
    return None


def is_buffer_type(type_text: str) -> bool:
    text = str(type_text or "")
    return any(t in text for t in ASCENDC_BUFFER_TYPES)


def is_non_storage_type(type_text: str) -> bool:
    text = str(type_text or "")
    return any(t in text for t in ASCENDC_NON_STORAGE_TYPES)


def is_storage_type_text(type_text: str) -> bool:
    """True if the decl type is an AscendC buffer or register storage type."""
    return bool(register_class_from_type(type_text) or is_buffer_type(type_text))


def is_valid_storage_name(name: str) -> bool:
    """C++ identifier usable as a storage entity name (not an expression)."""
    text = str(name or "").strip()
    if not text or text in _CXX_KEYWORDS:
        return False
    return text.isidentifier()
