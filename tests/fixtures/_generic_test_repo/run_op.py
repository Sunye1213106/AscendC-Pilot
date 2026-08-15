# Inverse of the toy bridge: given a target key, which knobs spell it.
#
# Generic runner used only as a shape example for TG test-repo scan.
# It is not an operator-specific harness.
import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run operator cases from a CSV table")
    parser.add_argument("--case", default="./data/cases.csv", help="case csv table")
    parser.add_argument(
        "--mode",
        default="precision",
        help="precision compare or perf profiling",
    )
    args = parser.parse_args()
    path = Path(args.case)
    if not path.is_file():
        raise SystemExit(f"missing case table: {path}")
    print(f"ok {args.mode} {path}")


if __name__ == "__main__":
    main()
