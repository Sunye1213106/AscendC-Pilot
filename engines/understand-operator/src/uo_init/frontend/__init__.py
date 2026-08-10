# -*- coding: utf-8 -*-
"""Clang frontend — CompilerFacts only (no AscendC business interpretation)."""

from uo_init.frontend.build_variant import BuildVariant, build_variant_from_context
from uo_init.frontend.clang import CompilerFacts, extract_compiler_facts

__all__ = [
    "BuildVariant",
    "CompilerFacts",
    "build_variant_from_context",
    "extract_compiler_facts",
]
