from __future__ import annotations

from code_engineering.impact import parse_two_sided_spans


def test_two_sided_diff_retains_old_new_and_rename() -> None:
    diff = "--- a/old.cpp\n+++ b/new.cpp\n@@ -3,2 +7,4 @@\n-x\n+y\n"
    rows = parse_two_sided_spans(diff)
    assert rows == [{
        "status": "rename",
        "old": {"file": "old.cpp", "start": 3, "end": 4},
        "new": {"file": "new.cpp", "start": 7, "end": 10},
    }]
