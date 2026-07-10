# PR Mode

Reads:

- `.understand-operator/<op>/cbm/change_set.yaml`
- `.understand-operator/<op>/summary/update_plan.yaml`
- canonical tiling model from kb_snapshot

Expands impacted obligations only, then generate/probe/audit.

MVP: `tg-pr` writes stub `pr/pr_test_report.md` if change_set missing.
