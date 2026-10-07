"""Log mining: classify lines into failure categories and cluster them into templates."""

from __future__ import annotations

import re
from collections import Counter

from .models import LogInsight

CATEGORIES: dict[str, re.Pattern[str]] = {
    "out_of_memory": re.compile(
        r"OutOfMemoryError|out of memory|Cannot allocate memory|heap space|memory limit exceeded", re.I
    ),
    "db_pool": re.compile(
        r"pool exhausted|too many connections|connection pool|could not obtain connection|HikariPool"
        r"|max_connections|remaining connection slots",
        re.I,
    ),
    "timeout": re.compile(r"timed? ?out|timeout|deadline exceeded|\b504\b", re.I),
    "connection": re.compile(
        r"connection refused|ECONNREFUSED|connection reset|broken pipe|no route to host|EHOSTUNREACH", re.I
    ),
    "dns": re.compile(r"no such host|NXDOMAIN|name resolution|UnknownHostException|getaddrinfo", re.I),
    "tls": re.compile(r"x509|certificate (has expired|signed by unknown)|handshake fail|SSLHandshake", re.I),
    "http_5xx": re.compile(r'(status[=: ]+|HTTP/\d(\.\d)?" |code[=: ]+)5\d\d\b', re.I),
    "slow": re.compile(r"slow (query|request)|took \d{4,} ?ms|exceeded threshold", re.I),
    "gc": re.compile(r"GC overhead|Full GC|stop-the-world|gc pause", re.I),
    "exception": re.compile(r"Exception\b|Traceback \(most recent|panic:|\bFATAL\b|\bSEVERE\b"),
    "error": re.compile(r"\bERROR\b|level=error|\"level\":\s*\"error\"|\[error\]", re.I),
}

_TIMESTAMP = re.compile(r"^\S*\d{4}-\d{2}-\d{2}[T ][\d:.,]+(Z|[+-]\d{2}:?\d{2})?\s*")
_VARIABLE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
    r"|\b0x[0-9a-f]+\b|\b[0-9a-f]{12,}\b|(?<![A-Za-z_])\d+(?:\.\d+)*",
    re.I,
)
MAX_SAMPLES = 3


def template_of(line: str) -> str:
    """Normalise a log line into a template by stripping timestamps, ids and numbers."""
    return _VARIABLE.sub("<*>", _TIMESTAMP.sub("", line)).strip()[:200]


def analyze_log(pod: str, container: str, text: str, previous: bool = False) -> LogInsight:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    counts: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}
    templates: Counter[str] = Counter()
    for line in lines:
        matched = [name for name, rx in CATEGORIES.items() if rx.search(line)]
        if not matched:
            continue
        templates[template_of(line)] += 1
        for name in matched:
            counts[name] += 1
            bucket = samples.setdefault(name, [])
            clean = _TIMESTAMP.sub("", line).strip()[:300]
            if len(bucket) < MAX_SAMPLES and clean not in bucket:
                bucket.append(clean)
    return LogInsight(
        pod=pod,
        container=container,
        previous=previous,
        lines=len(lines),
        category_counts=dict(counts),
        samples=samples,
        top_templates=[{"template": t, "count": n} for t, n in templates.most_common(5)],
    )


def analyze_logs(logs: dict[str, str]) -> list[LogInsight]:
    """``logs`` keys are ``pod/container`` or ``pod/container#previous``."""
    insights = []
    for key, text in logs.items():
        ident, _, flag = key.partition("#")
        pod, _, container = ident.partition("/")
        insights.append(analyze_log(pod, container, text, previous=flag == "previous"))
    return insights
