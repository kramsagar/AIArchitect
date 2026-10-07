"""Aggregate JUnit XML files under test-reports/ into SUMMARY.md (also used as the CI job summary)."""

import datetime
import pathlib
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET

SUITES = ("functional", "regression", "uat")


def _git_sha() -> str:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "src", "app", "tests"], text=True)
        return f"{sha} + uncommitted changes" if dirty.strip() else sha
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main(root: str = "test-reports") -> int:
    out = pathlib.Path(root)
    rows, failures, ok = [], [], True
    for suite in SUITES:
        path = out / suite / "junit.xml"
        if not path.exists():
            rows.append(f"| {suite} | - | - | - | - | - | not run |")
            ok = False
            continue
        totals = dict.fromkeys(("tests", "failures", "errors", "skipped"), 0)
        time_s = 0.0
        for ts in ET.parse(path).getroot().iter("testsuite"):
            for k in totals:
                totals[k] += int(ts.get(k, 0))
            time_s += float(ts.get("time", 0))
            for case in ts.iter("testcase"):
                bad = case.find("failure") if case.find("failure") is not None else case.find("error")
                if bad is not None:
                    failures.append(
                        f"- `{suite}` {case.get('classname')}::{case.get('name')}: {bad.get('message', '')[:200]}"
                    )
        passed = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
        result = "PASS" if not (totals["failures"] or totals["errors"]) and totals["tests"] else "FAIL"
        ok &= result == "PASS"
        rows.append(
            f"| {suite} | {totals['tests']} | {passed} | {totals['failures'] + totals['errors']} | "
            f"{totals['skipped']} | {time_s:.1f}s | {result} |"
        )
    lines = [
        "# Test results: ocp-bottleneck-analyzer",
        "",
        f"- Commit: `{_git_sha()}`",
        f"- Run at: {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M UTC}",
        f"- Python {platform.python_version()} on {platform.system()}",
        f"- Overall: **{'PASS' if ok else 'FAIL'}**",
        "",
        "| Suite | Tests | Passed | Failed | Skipped | Time | Result |",
        "|---|---|---|---|---|---|---|",
        *rows,
        "",
        "Reports: `<suite>/report.html` (HTML), `<suite>/junit.xml` (JUnit), `<suite>/output.txt` (console); "
        "UAT screenshots in `uat/screenshots/`.",
    ]
    if failures:
        lines += ["", "## Failures", *failures]
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
