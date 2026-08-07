from __future__ import annotations

from testcase_agent.closure.oracle import HostOracle, Verdict, accounting


def test_accounting_separates_judged_and_operational_outcomes() -> None:
    report = accounting(
        [
            Verdict(case_id="accepted", ok=True),
            Verdict(case_id="rejected", ok=False),
            Verdict(case_id="crashed", reject="HOST_CRASHED:signal", judged=False),
            Verdict(case_id="not-run", reject="NOT_RUN:batch_truncated", judged=False),
            Verdict(case_id="parse", reject="PARSE_FAILED:csv", judged=False),
        ]
    )
    assert report["requested"] == 5
    assert report["judged"] == 2
    assert report["actually_run"] == 3
    assert report["accepted"] == report["rejected"] == 1
    assert report["crashed"] == report["not_run"] == report["parse_failed"] == 1
    assert report["conserved"] == 1


def test_host_oracle_marks_runner_exception_as_crash() -> None:
    class ExplodingRunner:
        def run(self, *_args, **_kwargs):
            raise RuntimeError("driver failed")

    verdicts = HostOracle(runner=ExplodingRunner()).judge([object(), object()], tag="probe")
    assert all(v.reject.startswith("HOST_CRASHED") for v in verdicts)
    assert all(not v.verdict for v in verdicts)
