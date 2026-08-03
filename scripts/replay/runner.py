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


@dataclass
class Result:
    case_id: str
    ok: bool = False
    key: int = 0
    dims: dict = field(default_factory=dict)      # decoded from the key
    logged: dict = field(default_factory=dict)    # read off the tiling's own log
    diag: dict = field(default_factory=dict)      # intermediates
    reject: str = ""                              # why tiling refused, if it did
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
        return self.root / self.manifest.cache

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

    def _require_host(self) -> None:
        """Fail with what to fix, rather than on a blank done-marker check.

        A missing distribution and a missing driver both surface as empty
        stdout, which reads as "the replay produced nothing" and sends the
        reader looking at the cases.
        """
        if self.manifest.host != "wsl":
            raise ManifestError(
                f"replay host {self.manifest.host!r} is not supported; this "
                f"engine can only drive a wsl distribution")
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
                f"(see docs/workflows/tiling-key-coverage.md)"
            )

    def run(self, cases: dict[str, I.Case], *, with_log: bool = True,
            tag: str = "batch", check: bool = True) -> dict[str, Result]:
        """Replay every case and return one result each, keyed by case id."""
        self.cache.mkdir(parents=True, exist_ok=True)
        in_csv = self.cache / f"{tag}_in.csv"
        out_csv = self.cache / f"{tag}_out.csv"
        log_txt = self.cache / f"{tag}_log.txt"

        shadow = self.preflight(cases) if check else {}
        # Shadow: every case is sent. Filtering used to drop real witnesses
        # whenever the premise grade lagged; recording the would-reject is
        # enough to calibrate without losing coverage.
        send = cases

        in_csv.write_text(
            "\n".join(I.to_csv_line(c, cid) for cid, c in send.items()) + "\n",
            encoding="utf-8", newline="\n",
        )

        self._require_host()
        proc = subprocess.run(
            ["wsl", "-d", self.manifest.distro, "-e", "bash", self.manifest.entry,
             _wsl(in_csv), _wsl(out_csv), _wsl(log_txt), "1" if with_log else "0"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if self.manifest.done_marker not in (proc.stdout or ""):
            raise RuntimeError(
                f"replay did not finish: {proc.stdout}\n{proc.stderr}")

        results = self.parse_log(log_txt.read_text(encoding="utf-8", errors="replace"))
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
        row += [r.reject.replace(",", " ")]
        return row

    def write_wide(self, path: Path, cases: dict[str, I.Case],
                   results: dict[str, Result]) -> None:
        lines = [",".join(self.wide_header())]
        for cid, case in cases.items():
            lines.append(",".join(self.wide_row(cid, case.normalised(), results[cid])))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


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
            f"no operator package under {root / 'operators'}; add one, or "
            f"set UO_REPLAY_MANIFEST to a manifest elsewhere")
    listing = ", ".join(f"{op}/{arch}" for op, arch in found)
    raise ManifestError(
        f"several operator packages are present ({listing}); set UO_OPERATOR "
        f"and UO_ARCH to say which one this run is about")


_default: ReplayRunner | None = None


def default() -> ReplayRunner:
    """The runner the module-level names resolve through.

    Built on first use like the schema is, and for the same reason: reading
    the manifest is cheap but not free, and a module that only wants `Result`
    should not pay for it or fail without it.
    """
    global _default
    if _default is None:
        _default = ReplayRunner(OperatorManifest.load(manifest_path()))
    return _default


def use(manifest: OperatorManifest | str | os.PathLike[str]) -> ReplayRunner:
    """Point the module-level names at a different operator."""
    global _default
    if not isinstance(manifest, OperatorManifest):
        manifest = OperatorManifest.load(manifest)
    _default = ReplayRunner(manifest)
    return _default


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
