from pathlib import Path
from uo_init.tu_cache import tu_cache_dir, uo_cache_root

op = Path("/work/ops-transformer/attention/flash_attention_score_grad")
d = tu_cache_dir(op, "arch35")
print("cache_root", uo_cache_root(op, "arch35"))
print("tu_dir", d, "exists", d.is_dir())
if d.is_dir():
    files = list(d.glob("*.pkl"))
    print("pkl_count", len(files))
    print("total_mb", round(sum(f.stat().st_size for f in files) / 1e6, 2))
