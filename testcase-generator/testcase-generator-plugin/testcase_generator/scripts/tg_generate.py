from __future__ import annotations

import click

from testcase_generator.scripts._cli import bootstrap, common_options, log, resolve_project_root


@click.command()
@click.option("--level", default="L0,L1", show_default=True, help="Coverage levels: L0,L1,L2")
@common_options
def main(
    project_root_arg: str | None,
    project_root_opt: str | None,
    op_name: str | None,
    output_root: str | None,
    verbose: bool,
    level: str,
) -> int:
    bootstrap()
    from testcase_generator._core.paths import resolve_paths
    from testcase_generator._core.yaml_io import dump_yaml, load_yaml, write_jsonl
    from testcase_generator.engine.candidates import build_candidates
    from testcase_generator.engine.factor_space import build_factor_space
    from testcase_generator.engine.prune import prune_candidates
    from testcase_generator.engine.realize import realize_inputs
    from testcase_generator.engine.rule_model import build_rule_model
    from testcase_generator.engine.set_cover import greedy_set_cover

    project_root = resolve_project_root(project_root_arg, project_root_opt)
    _, op, _, tg = resolve_paths(project_root, op_name, output_root)
    snap = load_yaml(tg / "kb_snapshot.yaml")
    obligations = load_yaml(tg / "plan" / "coverage_obligations.yaml")
    if not obligations:
        click.echo("ERROR: plan/coverage_obligations.yaml missing. Run tg-plan first.", err=True)
        return 1

    levels = [x.strip() for x in level.split(",") if x.strip()]
    factor_space = build_factor_space(snap)
    rule_model = build_rule_model(snap)
    raw = build_candidates(obligations, factor_space, levels, rule_model=rule_model)
    pruned = prune_candidates(raw, factor_space, rule_model)
    selected = greedy_set_cover(pruned["valid"], obligations.get("all_obligations", []))
    cases, suggestions = realize_inputs(
        selected["selected"],
        rule_model,
        snap.get("operator_io", {}),
    )

    gen = tg / "generate"
    dump_yaml(gen / "factor_space.yaml", factor_space)
    dump_yaml(gen / "rule_model.yaml", rule_model)
    dump_yaml(gen / "candidate_keys_raw.yaml", raw)
    dump_yaml(gen / "candidate_keys_valid.yaml", pruned)
    dump_yaml(gen / "selected_targets.yaml", selected)
    dump_yaml(
        gen / "realized_cases.yaml",
        {
            "version": 1,
            "op_name": op,
            "levels": levels,
            "level_semantics": raw.get("level_semantics", {}),
            "cases": cases,
        },
    )
    if suggestions:
        dump_yaml(tg / "review" / "realization_patch_suggestion.yaml", {"suggestions": suggestions})

    probe_rows = []
    for c in cases:
        # L2 negatives are documented but not sent to positive probe by default.
        if c.get("expect_reject") or (c.get("level") == "L2"):
            continue
        probe_rows.append(
            {
                "case_id": c["case_id"],
                "expected_key": c.get("expected_key", {}),
                "inputs": c.get("inputs", {}),
                "family_id": c.get("family_id"),
                "level": c.get("level", "L1"),
            }
        )
    write_jsonl(gen / "probe_cases.jsonl", probe_rows)

    # Keep L2 negatives in a separate artifact for review / negative dry-run.
    l2_cases = [c for c in cases if c.get("level") == "L2" or c.get("expect_reject")]
    if l2_cases:
        dump_yaml(gen / "l2_negative_cases.yaml", {"version": 1, "op_name": op, "cases": l2_cases})

    log(
        verbose,
        f"raw={raw['count']} by_level={raw.get('counts_by_level')} "
        f"valid={pruned['valid_count']} selected={selected['selected_count']}",
    )
    click.echo(f"Generated {len(cases)} realized cases -> generate/realized_cases.yaml")
    click.echo(f"Positive probe cases: {len(probe_rows)} -> generate/probe_cases.jsonl")
    if l2_cases:
        click.echo(f"L2 negatives: {len(l2_cases)} -> generate/l2_negative_cases.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
