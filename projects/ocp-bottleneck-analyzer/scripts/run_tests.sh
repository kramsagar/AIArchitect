#!/usr/bin/env bash
# Run functional, regression and UAT (Playwright) suites; write JUnit + HTML reports and SUMMARY.md to test-reports/.
set -uo pipefail
cd "$(dirname "$0")/.."
OUT=test-reports
rm -rf "$OUT" && mkdir -p "$OUT"
status=0
for suite in functional regression uat; do
  mkdir -p "$OUT/$suite"
  python -m pytest -m "$suite" -p no:cacheprovider -q \
    --junitxml="$OUT/$suite/junit.xml" --html="$OUT/$suite/report.html" --self-contained-html \
    2>&1 | tee "$OUT/$suite/output.txt" || status=1
done
python scripts/summarize_reports.py "$OUT"
exit $status
