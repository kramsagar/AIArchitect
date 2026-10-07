# AIArchitect

A portfolio of hands-on projects covering **Machine Learning, AIOps, MLOps, Agentic AI and Agentic Ops**.
Each project is self-contained under [`projects/`](projects/) with its own README, dependencies, tests and
deployment manifests.

## Projects

| Project | Domain | Summary |
| --- | --- | --- |
| [OCP Bottleneck Analyzer](projects/ocp-bottleneck-analyzer/) | AIOps · Agentic Ops | Connects to an OpenShift cluster, reads the full stack around a deployment (workload spec, pods, events, HPA, nodes, quotas, logs and Prometheus metrics), detects performance bottlenecks with a rule engine and uses a tool-calling LLM agent to produce a root-cause summary with remediation steps. |

## Repository layout

```
AIArchitect/
├── projects/
│   └── ocp-bottleneck-analyzer/   # AIOps + agentic root-cause analysis for OpenShift
└── .github/workflows/             # CI (lint + tests per project)
```

## Conventions

- Python projects use a `src/` layout, `pyproject.toml`, `ruff` for linting and `pytest` for tests.
- Every project ships a **demo mode** with synthetic data so it can be explored without access to real infrastructure.
- Secrets (cluster credentials, LLM API keys) are only ever read from user input or environment variables — never committed.
