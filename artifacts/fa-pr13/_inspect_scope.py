import yaml
from pathlib import Path

p = Path(
    "/work/ops-transformer/attention/flash_attention_score_grad/"
    ".ascendc-pilot/arch35/uo/summary/scope_candidates.yaml"
)
c = yaml.safe_load(p.read_text(encoding="utf-8"))
print(
    {
        k: c.get(k)
        for k in [
            "op_name",
            "arch_dir",
            "probe_clean",
            "ambiguities",
            "host_probe_errors",
            "kernel_probe_errors",
        ]
    }
)
print("host_targets", len(c.get("host_targets") or []))
print("kernel_entry", c.get("kernel_entry"))
probes = c.get("probes") or {}
if isinstance(probes, dict):
    print("probes_keys", list(probes)[:30])
    for k, v in list(probes.items())[:12]:
        print("PROBE", k, str(v)[:300])
else:
    print("probes", probes)
