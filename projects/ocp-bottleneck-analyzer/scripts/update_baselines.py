"""Regenerate tests/regression/baselines.json from the demo scenarios (run after intentional rule changes)."""

import json
import pathlib

from ocp_analyzer.analyzer import run_analysis
from ocp_analyzer.demo import DemoKube, DemoPrometheus

OUT = pathlib.Path(__file__).resolve().parents[1] / "tests" / "regression" / "baselines.json"


def main() -> None:
    kube, data = DemoKube(), {}
    for dep in sorted(d["metadata"]["name"] for d in kube.list_deployments("shop")):
        report = run_analysis(DemoKube(), DemoPrometheus(), "shop", dep)
        data[dep] = {
            "health_score": report.health_score,
            "rule_ids": sorted({f.rule_id for f in report.findings}),
            "severity_counts": {
                s: sum(1 for f in report.findings if f.severity.value == s)
                for s in ("critical", "high", "medium", "low", "info")
            },
        }
    OUT.write_text(json.dumps(data, indent=2) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
