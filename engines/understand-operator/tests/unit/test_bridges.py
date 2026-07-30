# -*- coding: utf-8 -*-
from uo_init.bridges import collect_invoke_provenance, field_subset_ok, parse_schema_variant


def test_schema_variant_args(fag_dir):
    apt = fag_dir / "op_kernel" / "flash_attention_score_grad_apt.cpp"
    text = apt.read_text(encoding="utf-8", errors="replace")
    sv = parse_schema_variant(text)
    assert sv is not None
    assert len(sv.template_args) == 4
    blob = " ".join(sv.derived_from.values()) + " ".join(sv.template_args)
    assert "DeterType" in blob or "NEED_DETER" in blob
    assert "IsTnd" in blob
    assert "IsTndSwizzle" in blob


def test_host_kernel_field_subset():
    host = {"fBaseParams.s1", "fBaseParams.s2", "fBaseParams.isNzOut"}
    kernel = {"fBaseParams.s1", "fBaseParams.isNzOut"}
    assert field_subset_ok(host, kernel)
    assert not field_subset_ok(host, kernel | {"missing.field"})


def test_invoke_macro_provenance(fag_dir):
    found = False
    for p in (fag_dir / "op_kernel" / "arch35").rglob("*.h"):
        sites = collect_invoke_provenance(p)
        if sites:
            assert sites[0].file
            assert sites[0].line >= 1
            assert sites[0].snippet.startswith("INVOKE_FAG")
            found = True
            break
    if not found:
        # fallback: apt still has schema; provenance API must not crash on empty
        sites = collect_invoke_provenance(
            fag_dir / "op_kernel" / "flash_attention_score_grad_apt.cpp"
        )
        assert isinstance(sites, list)
