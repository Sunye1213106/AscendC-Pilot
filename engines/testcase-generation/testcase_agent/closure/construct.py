# -*- coding: utf-8 -*-
"""Build the input a target key asks for, instead of searching for it.

By the construction stage every dimension's provenance is known, so a target
key can be read as a specification and turned straight into Cases. Sampling
had to stumble onto these combinations; construction just writes them down.
What construction cannot do is guarantee the host agrees -- the dimensions
interact -- so several spellings of each target are sent and the host still
decides.
"""

from __future__ import annotations

from typing import Mapping

from testcase_agent.closure import workspace as W

DTYPE = {"1": "FLOAT", "2": "BF16", "3": "FLOAT16"}
D_FOR = {
    "64": [64, 63], "128": [128, 96, 72], "192": [192, 160],
    "256": [256, 224], "768": [320, 512, 384, 768],
}
DETER_FOR = {
    "0": [(0, 0), (0, 2), (0, 3)],
    "1": [(1, 6), (1, 5)],
    "2": [(1, 0), (1, 1), (1, 4)],
    "3": [(1, 2)],
    "4": [(1, 3)],
}
S1_FOR = {"128": [1024, 2048, 512, 256], "64": [256, 2048, 1024], "0": [0]}
MASKS = ["ss", "bnss", "b1ss", "11ss"]


def build(t: Mapping[str, str], seed: int = 0) -> list:
    """Spellings of one target key, most likely first."""
    I = W.replay_inputs()
    dtype = DTYPE.get(str(t.get("InputDType")))
    if dtype is None or str(t.get("IsRegbase")) != "1" or str(t.get("IsEmptyTensor")) == "1":
        return []
    if str(t.get("OutDType")) != str(t.get("InputDType")):
        return []
    out = []
    for d in D_FOR.get(str(t.get("DTemplateNum")), []):
        for s1 in S1_FOR.get(str(t.get("S1TemplateNum")), [1024]):
            for det, sparse in DETER_FOR.get(str(t.get("DeterType")), []):
                for mask in (MASKS if str(t.get("IsAttenMask")) == "1" else ["none"]):
                    rope = str(t.get("IsRope")) == "1"
                    if rope and str(t.get("DTemplateNum")) != "192":
                        continue
                    g = 1 if str(t.get("IsNEqual")) == "1" else 2
                    d1 = d if str(t.get("IsDNoEqual")) == "0" else max(16, d // 2)
                    if rope:
                        d1 = None
                    s2 = 1024 if str(t.get("S2TemplateNum")) == "128" else s1
                    case = I.Case(
                        layout="TND" if str(t.get("IsTnd")) == "1" else "BSND",
                        dtype=dtype, b=2, s1=s1, s2=s2, n2=2, g=g,
                        d=d, d1=d1, atten_mask=mask,
                        pse=(str(t.get("IsPse")) == "1"),
                        pse_shape="bnss" if str(t.get("IsTnd")) == "0" else "slope",
                        pse_type=2 if str(t.get("IsTnd")) == "1" else 1,
                        rope=rope,
                        keep_prob=0.5 if str(t.get("IsDrop")) == "1" else 1.0,
                        sparse_mode=sparse, deterministic=det,
                        pre_tokens=65536, next_tokens=65536,
                        out_dtype=0,
                    )
                    try:
                        out.append(case.normalised())
                    except Exception:
                        pass
    return out
