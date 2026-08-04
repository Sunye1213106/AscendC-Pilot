# -*- coding: utf-8 -*-
"""TilingKey closure: drive R up with real runs, drive E up with source lemmas.

The closure argument is that every declared key is settled exactly one way:

    D = (R ∩ D) ∪ E        and        R ∩ E = ∅

`R` grows only from a real host verdict, `E` only from a lemma that cites the
source lines it read. A fitted model may choose and rank candidates; it may
never exclude a key.
"""

from testcase_agent.closure.workspace import Workspace, default_workspace
from testcase_agent.closure import ledger
from testcase_agent.closure import lemma
from testcase_agent.closure import report

__all__ = [
    "Workspace",
    "default_workspace",
    "ledger",
    "lemma",
    "report",
]
