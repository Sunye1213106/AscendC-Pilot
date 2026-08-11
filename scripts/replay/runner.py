# -*- coding: utf-8 -*-
"""Drive the replay executable and read back the key, its dimensions and why.

Decoding the key gives the dimension values, but the tiling also logs them
before packing, along with the intermediates that decide the hard ones. Those
say *why* a dimension did not flip, which is what makes a coverage search
directed rather than blind.

None of that is spelled here any more. Which operator, which machine, which
lines mean what -- all of it comes from an operator manifest, and this module
knows only that there is a driver to run and slots to fill. The module-level
names (`SCHEMA`, `DIM_NAMES`, `CACHE`, `run`) still work: they resolve through
a default runner built from whichever manifest the environment names, so the
twenty-odd scripts that reach for them read unchanged.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init import paths  # noqa: E402
from uo_init.tpl_dsl import parse_file  # noqa: E402

from . import inputs as I  # noqa: E402
from .manifest import (  # noqa: E402
    ManifestError, OperatorManifest, available, discover, slots_of)


#: `reject` prefixes that mean "the host never gave a verdict", as opposed to
#: the host having refused. Telling the two apart matters: a case the driver
#: died on and a case it never reached are not evidence about the operator,
#: and counting them as refusals both understates acceptance and feeds a
#: learner negative examples nothing earned.
CRASHED = "HOST_CRASHED"
NOT_RUN = "NOT_RUN"


@dataclass
class Result:
    case_id: str
    ok: bool = False
    key: int = 0
    dims: dict = field(default_factory=dict)      # decoded from the key
    logged: dict = field(default_factory=dict)    # read off the tiling's own log
    diag: dict = field(default_factory=dict)      # intermediates
    reject: str = ""                              # why tiling refused, if it did

    @property
    def verdict(self) -> bool:
        """Whether the host actually judged this case, either way."""
        return not self.reject.startswith((CRASHED, NOT_RUN))
    #: Per-sample records, one list per named series. Unlike everything above
    #: these are evidence about individual batch entries rather than about the
    #: case, which is what a claim about a loop can be checked against.
    series: dict = field(default_factory=dict)


class ReplayRunner:
    """One operator's replay, as described by its manifest."""

    def __init__(self, manifest: OperatorManifest, *, root: Path = ROOT):
        self.manifest = manifest
        self.root = root
        self._parsed: dict[str, object] = {}

    # --- what the manifest says -----------------------------------------

    @property
    def cache(self) -> Path:
        """Replay batch directory under ``<op_src>/.ascendc-pilot/<arch>/``."""
        cache = Path(self.manifest.cache)
        if cache.is_absolute():
            return cache
        op_src = (
            os.environ.get("ASCENDC_PROJECT_ROOT")
            or os.environ.get("UO_OP_DIR")
            or ""
        )
        if op_src:
            base = Path(op_src).expanduser().resolve()
            return base / ".ascendc-pilot" / self.manifest.arch / cache
        # Fallback: relative to the AscendC-Pilot checkout (legacy / tests).
        return self.root / ".ascendc-pilot" / self.manifest.arch / cache

    @property
    def log_fields(self) -> list[str]:
        """Dimension names the tiling logs, in the order the protocol lists."""
        return list(self.manifest.log.dim_fields)

    def tpl_path(self) -> Path:
        """The header that declares the key layout.

        Resolved through `uo_init.paths`, so a checkout anywhere is found the
        same way the rest of the repository finds it.
        """
        header = self.manifest.tiling_key_header
        if Path(header).is_absolute():
            return Path(header).expanduser()
        op = paths.op_dir(relative=self.manifest.relative_path)
        if op is None:
            raise SystemExit(
                f"cannot locate operator {self.manifest.relative_path!r}\n"
                f"{paths.explain()}\n"
                f"set UO_OPS_ROOT, or point the manifest's "
                f"replay.overrides.tiling_key_header variable at the header"
            )
        return op / header

    def schema(self):
        """The key layout the operator's kernel declares.

        Parsed on first use. Reading the header is the one thing here that
        needs the operator sources, and doing it at import made every pure
        module unimportable on a machine without them.
        """
        if "schema" not in self._parsed:
            self._parsed["schema"] = parse_file(self.tpl_path())
        return self._parsed["schema"]

    def dim_names(self) -> list[str]:
        """Dimension names, in the order the key packs them."""
        if "dims" not in self._parsed:
            self._parsed["dims"] = [d.name for d in self.schema().dims]
        return list(self._parsed["dims"])  # type: ignore[arg-type]

    # --- reading a run ---------------------------------------------------

    def parse_log(self, text: str) -> dict[str, Result]:
        """Split the output per case and let the protocol fill the slots."""
        marks = self.manifest.log.marks
        case_mark, done_mark = marks.get("case"), marks.get("done")
        if case_mark is None or done_mark is None:
            raise ManifestError(
                "the log protocol must define the `case` and `done` marks; "
                "without them there is no way to tell one case's output from "
                "the next")

        out: dict[str, Result] = {}
        cur: Result | None = None
        body: list[str] = []

        def close() -> None:
            if cur is not None:
                got = slots_of(self.manifest.log, body)
                cur.logged = got["dim"]
                cur.diag = got["state"]
                cur.series = got["series"]
                if got["reject"]:
                    cur.reject = got["reject"]

        for line in text.splitlines():
            m = case_mark.match(line)
            if m:
                close()
                cur = Result(case_id=m.group("case_id"))
                out[cur.case_id] = cur
                body = []
                continue
            m = done_mark.match(line)
            if m and cur is not None:
                cur.ok = m.group("ok") == "1"
                cur.key = int(m.group("key"))
                close()
                cur, body = None, []
                continue
            if cur is not None:
                body.append(line)
        close()
        return out

    def finished_ids(self, text: str) -> set[str]:
        """Cases the driver saw all the way through.

        `parse_log` also returns a Result for a case whose ###CASE was printed
        and whose ###DONE never was -- the one the driver died on. That Result
        is indistinguishable from a refusal, so the done marks are counted
        separately.
        """
        done_mark = self.manifest.log.marks.get("done")
        if done_mark is None:
            return set()
        out = set()
        for line in text.splitlines():
            m = done_mark.match(line)
            if m:
                out.add(m.group("case_id"))
        return out

    def started_ids(self, text: str) -> list[str]:
        case_mark = self.manifest.log.marks.get("case")
        if case_mark is None:
            return []
        out = []
        for line in text.splitlines():
            m = case_mark.match(line)
            if m:
                out.append(m.group("case_id"))
        return out

    # --- running it ------------------------------------------------------

    def preflight(self, cases: dict[str, I.Case]) -> dict[str, Result]:
        """Cases the extracted premises say the host would refuse.

        Shadow only: the result is tagged PREFLIGHT_WOULD_REJECT so a later
        pass can count how often the extraction agrees with the host, but the
        case is still sent. Hard-filtering used to drop witnesses whenever the
        grade file lagged behind a fix in the premises.
        """
        from . import bridge as B

        out: dict[str, Result] = {}
        for cid, case in cases.items():
            bad = B.refused_by(case)
            if bad:
                p = bad[0]
                where = f"{Path(str(p.get('file', ''))).name}:{p.get('line')}"
                out[cid] = Result(
                    case_id=cid,
                    reject=(f"PREFLIGHT_WOULD_REJECT {where} "
                            f"{str(p.get('text', ''))[:120]}"),
                )
        return out

    def _native_host(self) -> bool:
        if sys.platform.startswith("linux"):
            return True
        if str(self.manifest.host or "").lower() == "native":
            return True
        if os.environ.get("UO_REPLAY_HOST", "").lower() == "native":
            return True
        return False

    def _require_host(self) -> None:
        """Fail with what to fix, rather than on a blank done-marker check.

        A missing distribution and a missing driver both surface as empty
        stdout, which reads as "the replay produced nothing" and sends the
        reader looking at the cases.
        """
        entry = self.manifest.entry
        if self._native_host():
            if not entry or not Path(entry).expanduser().exists():
                raise RuntimeError(
                    f"replay entry script not found at {entry!r}\n"
                    f"build the driver locally, or point the manifest's replay.entry "
                    f"at wherever it was built "
                    f"(see skills/testcase-generation and skills/source-proof)"
                )
            return
        if self.manifest.host != "wsl":
            raise ManifestError(
                f"replay host {self.manifest.host!r} is not supported; this "
                f"engine can only drive wsl or native hosts")
        distro, entry = self.manifest.distro, self.manifest.entry
        listing = subprocess.run(
            ["wsl", "-l", "-q"], capture_output=True, text=True,
            encoding="utf-16-le", errors="replace",
        )
        names = [n.strip() for n in (listing.stdout or "").splitlines() if n.strip()]
        if names and distro not in names:
            raise RuntimeError(
                f"WSL distribution {distro!r} not registered "
                f"(have: {', '.join(names) or 'none'})\n"
                f"set UO_REPLAY_DISTRO to the one holding the replay driver"
            )
        # Bytes, not text: only the exit status is read, and wsl.exe writes
        # its diagnostics as UTF-16 which the default codec cannot decode.
        probe = subprocess.run(
            ["wsl", "-d", distro, "-e", "test", "-f", entry], capture_output=True)
        if probe.returncode != 0:
            raise RuntimeError(
                f"replay entry script not found at {entry} inside {distro}\n"
                f"build the driver there, or point the manifest's replay.entry "
                f"at wherever it was built "
                f"(see skills/testcase-generation and skills/source-proof)"
            )

    def _invoke(self, send: dict[str, I.Case], in_csv, out_csv, log_txt,
                with_log: bool) -> tuple[str, int]:
        """One driver invocation. Returns the log text and the driver's status."""
        in_csv.write_text(
            "\n".join(I.to_csv_line(c, cid) for cid, c in send.items()) + "\n",
            encoding="utf-8", newline="\n",
        )
        if self._native_host():
            proc = subprocess.run(
                ["bash", self.manifest.entry, str(in_csv), str(out_csv), str(log_txt),
                 "1" if with_log else "0"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
        else:
            proc = subprocess.run(
                ["wsl", "-d", self.manifest.distro, "-e", "bash", self.manifest.entry,
                 _wsl(in_csv), _wsl(out_csv), _wsl(log_txt), "1" if with_log else "0"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
        stdout = proc.stdout or ""
        if self.manifest.done_marker not in stdout:
            raise RuntimeError(
                f"replay did not finish: {proc.stdout}\n{proc.stderr}")
        # The entry script reports the driver's status in the done marker and
        # exits zero itself, so the subprocess return code says nothing about
        # whether the batch survived.
        rc = proc.returncode
        if "rc=" in stdout:
            tail = stdout.split("rc=", 1)[1].split()
            if tail and tail[0].lstrip("-").isdigit():
                rc = int(tail[0])
        return log_txt.read_text(encoding="utf-8", errors="replace"), rc

    def run(self, cases: dict[str, I.Case], *, with_log: bool = True,
            tag: str = "batch", check: bool = True,
            restarts: int = 64) -> dict[str, Result]:
        """Replay every case and return one result each, keyed by case id.

        A driver that dies takes the rest of its batch with it. Nothing about
        that is visible from the outside: the entry script reports success
        either way, and the cases the driver never reached come back as
        Results with no key and no reason -- the same shape a refusal has. A
        single input could therefore turn most of a batch into silent negative
        evidence, which is how a search comes to spend its budget on cases it
        never ran.

        So the batch is resumed. Whatever finished is kept, the case the
        driver died on is recorded as such, and the remainder goes back for
        another pass until every case has a verdict or the restart budget is
        spent.
        """
        self.cache.mkdir(parents=True, exist_ok=True)
        in_csv = self.cache / f"{tag}_in.csv"
        out_csv = self.cache / f"{tag}_out.csv"
        log_txt = self.cache / f"{tag}_log.txt"

        shadow = self.preflight(cases) if check else {}
        # Shadow: every case is sent. Filtering used to drop real witnesses
        # whenever the premise grade lagged; recording the would-reject is
        # enough to calibrate without losing coverage.
        self._require_host()

        results: dict[str, Result] = {}
        transcript: list[str] = []
        pending = dict(cases)
        for _ in range(max(restarts, 0) + 1):
            if not pending:
                break
            text, rc = self._invoke(pending, in_csv, out_csv, log_txt, with_log)
            transcript.append(text)
            done = self.finished_ids(text)
            parsed = self.parse_log(text)
            for cid in done:
                if cid in parsed:
                    results[cid] = parsed[cid]

            # The case that started and never finished is the one that killed
            # the driver. Record it, drop it, and carry on with the rest.
            started = self.started_ids(text)
            crashed = next((c for c in reversed(started) if c not in done), None)
            for cid in done:
                pending.pop(cid, None)
            if crashed is not None:
                results[crashed] = Result(
                    case_id=crashed,
                    reject=f"{CRASHED} driver exited rc={rc} after "
                           f"{len(done)} of {len(pending) + len(done)} cases")
                pending.pop(crashed, None)
            elif not done:
                break  # no progress and nobody to blame: stop rather than spin

        for cid, case in pending.items():
            results[cid] = Result(
                case_id=cid,
                reject=f"{NOT_RUN} restart budget exhausted")

        if transcript:
            log_txt.write_text("".join(transcript), encoding="utf-8", newline="\n")

        for cid, shadow_r in shadow.items():
            r = results.setdefault(cid, Result(case_id=cid))
            # Prefer the host's own refusal when it has one; otherwise keep the
            # shadow tag so calibration can see what the extraction predicted.
            if not r.reject:
                r.reject = shadow_r.reject
        for cid in cases:
            r = results.setdefault(cid, Result(case_id=cid))
            if r.ok and r.key:
                r.dims = self.schema().decode_tiling_key(r.key)
        return results

    # --- writing what it found -------------------------------------------

    def wide_header(self) -> list[str]:
        """Columns of the wide table: what was fed in, and what came out."""
        return (
            ["case_id"] + list(I.describe(I.Case()).keys())
            + ["ok", "tiling_key"]
            + [f"dim_{n}" for n in self.dim_names()]
            + ["log_" + n for n in self.log_fields]
            + list(self.manifest.log.report_state)
            + ["reject"]
        )

    def wide_row(self, cid: str, case: I.Case, r: Result) -> list[str]:
        row = [cid] + [str(v) for v in I.describe(case).values()]
        row += ["1" if r.ok else "0", str(r.key)]
        row += [str(r.dims.get(n, "")) for n in self.dim_names()]
        row += [str(r.logged.get(n, "")) for n in self.log_fields]
        row += [str(r.diag.get(n, "")) for n in self.manifest.log.report_state]
        row += [r.reject]
        # Every field, not just the reject. `reject` was the only one scrubbed,
        # but a case tag reads `BSND:d=64,d1=16` and split the row in two --
        # silently, and for about a sixth of the corpus, which a strict reader
        # then dropped. Whichever column grows a comma next should not cost
        # another round of runs to notice.
        return [_plain(v) for v in row]

    def write_wide(self, path: Path, cases: dict[str, I.Case],
                   results: dict[str, Result]) -> None:
        lines = [",".join(self.wide_header())]
        for cid, case in cases.items():
            lines.append(",".join(self.wide_row(cid, case.normalised(), results[cid])))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _plain(value: str) -> str:
    """One CSV field, with nothing in it that would end the field early."""
    return str(value).replace(",", " ").replace("\n", " ").replace("\r", " ")


def _wsl(p: Path) -> str:
    s = str(p).replace("\\", "/")
    return "/mnt/" + s[0].lower() + s[2:]


def manifest_path(root: Path = ROOT) -> Path:
    """Where the default runner reads its manifest from.

    Which operator is under analysis is an input to this tool, never a
    property of it, so nothing here names one. A repository holding a single
    package has only one answer and giving it saves every script an argument;
    a repository holding several has to be told, because guessing would make
    every result quietly about whichever package sorted first.
    """
    explicit = os.environ.get("UO_REPLAY_MANIFEST")
    if explicit:
        return Path(explicit).expanduser()

    operator, arch = os.environ.get("UO_OPERATOR"), os.environ.get("UO_ARCH")
    if operator and arch:
        return discover(root, operator, arch)

    found = available(root)
    if len(found) == 1:
        return discover(root, *found[0])
    if not found:
        raise ManifestError(
            f"no operator package selected; set UO_OPERATOR+UO_ARCH "
            f"(fixture under tests/fixtures/) or UO_REPLAY_MANIFEST / "
            f"ASCENDC_PROJECT_ROOT for operator-local .ascendc-pilot")
    listing = ", ".join(f"{op}/{arch}" for op, arch in found)
    raise ManifestError(
        f"several operator packages are present ({listing}); set UO_OPERATOR "
        f"and UO_ARCH to say which one this run is about")


_default: ReplayRunner | None = None
_default_selection: tuple[str, str, str] | None = None

SELECTION_ENV_VARS = ("UO_REPLAY_MANIFEST", "UO_OPERATOR", "UO_ARCH")


def _selection() -> tuple[str, str, str]:
    """The env that decides which operator ``default()`` is about."""
    return tuple((os.environ.get(name) or "").strip() for name in SELECTION_ENV_VARS)


def default() -> ReplayRunner:
    """The runner the module-level names resolve through.

    Built on first use like the schema is, and for the same reason: reading
    the manifest is cheap but not free, and a module that only wants `Result`
    should not pay for it or fail without it.

    Rebuilt when the selecting env changes: holding the first operator asked
    for would make a later caller's results quietly about the wrong package.
    """
    global _default, _default_selection
    selection = _selection()
    if _default is None or _default_selection != selection:
        _default = ReplayRunner(OperatorManifest.load(manifest_path()))
        _default_selection = selection
    return _default


def use(manifest: OperatorManifest | str | os.PathLike[str]) -> ReplayRunner:
    """Point the module-level names at a different operator."""
    global _default, _default_selection
    if not isinstance(manifest, OperatorManifest):
        manifest = OperatorManifest.load(manifest)
    _default = ReplayRunner(manifest)
    _default_selection = _selection()
    return _default


def reset() -> None:
    """Forget the cached default so the next call re-reads the selection."""
    global _default, _default_selection
    _default = None
    _default_selection = None


def tpl_path() -> Path:
    return default().tpl_path()


def schema():
    return default().schema()


def dim_names() -> list[str]:
    return default().dim_names()


def preflight(cases: dict[str, I.Case]) -> dict[str, Result]:
    return default().preflight(cases)


def run(cases: dict[str, I.Case], *, with_log: bool = True,
        tag: str = "batch", check: bool = True) -> dict[str, Result]:
    return default().run(cases, with_log=with_log, tag=tag, check=check)


def wide_header() -> list[str]:
    return default().wide_header()


def wide_row(cid: str, case: I.Case, r: Result) -> list[str]:
    return default().wide_row(cid, case, r)


def write_wide(path: Path, cases: dict[str, I.Case],
               results: dict[str, Result]) -> None:
    default().write_wide(path, cases, results)


#: `R.SCHEMA` / `R.DIM_NAMES` / `R.CACHE` / `R.LOG_FIELDS` / `R.TPL` keep
#: working as module attributes so the call sites read unchanged; each
#: resolves through the default runner on first touch. PEP 562, so only an
#: actual attribute access pays for it.
def __getattr__(name: str):
    if name == "SCHEMA":
        return default().schema()
    if name == "DIM_NAMES":
        return default().dim_names()
    if name == "TPL":
        return default().tpl_path()
    if name == "CACHE":
        return default().cache
    if name == "LOG_FIELDS":
        return default().log_fields
    if name == "MANIFEST":
        return default().manifest
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
