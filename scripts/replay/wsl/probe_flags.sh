#!/usr/bin/env bash
# The include set the operator's own tiling TU was compiled with.
set -u
OPS=/work/ops-transformer
f="$OPS/build/attention/flash_attention_score_grad/op_host/CMakeFiles/ophost_transformer_tiling_obj.dir/flags.make"
if [ -f "$f" ]; then
  echo "--- $f"
  cat "$f"
else
  echo "not found: $f"
  find "$OPS/build" -name flags.make -path '*flash_attention*' | head -5
fi
echo
echo "=== where is log/log.h ==="
find "$OPS/third_party/opbase" -name 'log.h' -path '*log*' 2>/dev/null | head -5
