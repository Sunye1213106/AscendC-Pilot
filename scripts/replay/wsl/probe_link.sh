#!/usr/bin/env bash
# The exact command CMake used to link the UT executable, which is the recipe
# the replay driver has to match.
set -u
OPS=/work/ops-transformer
B="$OPS/build/tests/ut/framework_normal/op_host"

echo "=== link.txt for the UT exe ==="
find "$OPS/build" -name 'link.txt' -path '*op_host*' 2>/dev/null | while read -r f; do
  echo "--- $f"
  cat "$f"
  echo
done

echo "=== common objects available ==="
find "$B/CMakeFiles" -name '*.o' -path '*common*' 2>/dev/null

echo
echo "=== compile flags used for those objects ==="
find "$OPS/build" -name 'flags.make' -path '*ut_common*' 2>/dev/null | head -2 | while read -r f; do
  echo "--- $f"
  cat "$f"
done
