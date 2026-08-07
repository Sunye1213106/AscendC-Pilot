# -*- coding: utf-8 -*-

from __future__ import annotations

import pandas as pd


def test_int_exact_preserves_17_digit_tiling_key():
    from testcase_agent.closure.key_utils import int_exact

    key = "19703249444016816"
    assert int_exact(key) == 19703249444016816
    assert int_exact(f"{key}.0") == 19703249444016816


def test_corpus_coerce_preserves_target_key_precision():
    from testcase_agent.closure import corpus

    key = "19703249444016816"
    frame = pd.DataFrame([{
        "ok": "1",
        "tiling_key": key,
        "_target_key": key,
        "_predicted_key": key,
        "layout": "BSND",
    }])
    out = corpus.coerce(frame)

    assert int(out.loc[0, "tiling_key"]) == 19703249444016816
    assert int(out.loc[0, "_target_key"]) == 19703249444016816
    assert int(out.loc[0, "_predicted_key"]) == 19703249444016816
