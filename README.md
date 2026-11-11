# AIArchitect

A portfolio of hands-on projects covering **Machine Learning, AIOps, MLOps, Agentic AI and Agentic Ops**.
Each project is self-contained under [`projects/`](projects/) with its own README, dependencies, tests and
deployment manifests.

## Projects

| Project | Domain | Summary |
| --- | --- | --- |
| [OCP Bottleneck Analyzer](projects/ocp-bottleneck-analyzer/) | AIOps · Agentic Ops | Connects to an OpenShift cluster, reads the full stack around a deployment (workload spec, pods, events, HPA, nodes, quotas, logs and Prometheus metrics), detects performance bottlenecks with a rule engine and uses a tool-calling LLM agent to produce a root-cause summary with remediation steps. |

## Learning program: Agentic AI Architect (basic → enterprise)

A 12-module, theory + hands-on track built around SRE/observability use cases and a local Docker
observability lab. Start at [`learning/ROADMAP.md`](learning/ROADMAP.md).

| Module | Status | Deliverable |
| --- | --- | --- |
| [M1 LLM & Agent Engineering](learning/m01-llm-agent-engineering/) | ✅ | SRE copilot: single agent, two tools, structured output, retries/timeouts/circuit breaker, bench |
| [M2 Real tools, RAG, memory & MCP](learning/m02-rag-memory-mcp/) | ✅ | observability-mcp-server (Prometheus, Jaeger, Splunk, runbook RAG) + grounded MCP-client investigator with memory |
| [M3 Agentic RAG](learning/m03-agentic-rag/) | ✅ | incident-knowledge agent: BM25+vector hybrid, reranking, query rewriting/HyDE, corrective RAG, service-graph RAG, grounded citations, retrieval eval |

## Repository layout

```
AIArchitect/
├── projects/
│   └── ocp-bottleneck-analyzer/   # AIOps + agentic root-cause analysis for OpenShift
├── learning/                      # Agentic AI Architect program (ROADMAP.md + one folder per module)
│   ├── m01-llm-agent-engineering/
│   ├── m02-rag-memory-mcp/
│   └── m03-agentic-rag/
├── lab/                           # Docker observability lab (ShopSphere + OTel, Prometheus, Jaeger, Splunk, Grafana)
└── .github/workflows/             # CI (lint + tests per project)
```

## Conventions

- Python projects use a `src/` layout, `pyproject.toml`, `ruff` for linting and `pytest` for tests.
- Every project ships a **demo mode** with synthetic data so it can be explored without access to real infrastructure.
- Secrets (cluster credentials, LLM API keys) are only ever read from user input or environment variables — never committed.
