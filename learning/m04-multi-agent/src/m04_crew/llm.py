"""LLM access for the crew. Each specialist is one `complete(system, user)` call: a role prompt plus a JSON payload.
`ClaudeText` (from Module 3) talks to Claude; `MockCrewLLM` is deterministic, so tests/CI/offline runs need no key."""

from __future__ import annotations

import json

from m03_rag.llm import ClaudeText, TextLLM, json_from

__all__ = ["ClaudeText", "MockCrewLLM", "TextLLM", "build_llm", "json_from"]


def build_llm(provider: str, model: str | None = None) -> TextLLM:
    return ClaudeText(model) if provider == "anthropic" else MockCrewLLM()


class MockCrewLLM:
    """Rule-based stand-in. It recognises the role by the tag in the system prompt and reads the JSON payload."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, system: str, user: str, max_tokens: int = 600) -> str:
        self.calls += 1
        data = json.loads(user)
        if "[rca]" in system:
            return json.dumps(self._rca(data))
        if "[plan]" in system:
            return json.dumps(self._plan(data))
        if "[supervisor]" in system:
            left = [w for w in data["workers"] if w not in data["done"]]
            return json.dumps({"next": left[0] if left else "FINISH", "why": "next unvisited specialist"})
        if "[postmortem]" in system:
            return self._postmortem(data)
        return json.dumps({})

    @staticmethod
    def _rca(d: dict) -> dict:
        ev = d["evidence"]
        changes = [e for e in ev if e["source"] == "changes"]
        traces = [e["id"] for e in ev if e["source"] == "traces"][:2]
        alerts = [e["id"] for e in ev if e["id"].startswith("alert:")][:1]
        if changes:
            c = changes[0]
            svc = c["id"].split(":", 1)[1]
            service = {"shop": "shopsphere-shop", "payments": "payments-service"}.get(svc, svc)
            return {
                "root_cause": f"Recent change on {svc}: {c['summary']}",
                "service": service,
                "confidence": "high" if traces else "medium",
                "evidence_ids": [c["id"], *traces, *alerts],
            }
        return {
            "root_cause": "No change or fault found; symptom unexplained",
            "service": d.get("focus_service") or "?",
            "confidence": "low",
            "evidence_ids": alerts,
        }

    @staticmethod
    def _plan(d: dict) -> dict:
        rca, faults = d["rca"], d["active_faults"]
        target = {"shopsphere-shop": "shop", "payments-service": "payments"}.get(rca["service"], rca["service"])
        runbook = (d.get("runbooks") or [None])[0]
        if target in faults and rca["confidence"] != "low":
            return {
                "action": "reset_faults",
                "target": target,
                "risk": "medium",
                "runbook": runbook,
                "rationale": f"Roll back the active change on {target} ({faults[target]}); it explains the symptom.",
            }
        return {
            "action": "escalate",
            "target": None,
            "risk": "low",
            "runbook": runbook,
            "rationale": "No safe automated action matches the evidence; page the owning team.",
        }

    @staticmethod
    def _postmortem(d: dict) -> str:
        lines = [
            f"# Postmortem: {d['alert']}",
            "",
            f"**Status:** {d['status']}  **Severity:** {d['severity']}",
            "",
            "## Root cause",
            (d.get("rca") or {}).get("root_cause", "unknown"),
            "",
            "## Timeline",
        ]
        lines += [f"{i}. [{t['agent']}] {t['event']}" for i, t in enumerate(d["timeline"], 1)]
        lines += ["", "## Evidence", *[f"- `{e}`" for e in (d.get("rca") or {}).get("evidence_ids", [])]]
        lines += [
            "",
            "## Action items",
            "- Add a pre-deploy check that would have caught this change.",
            "- Review the alert threshold and runbook used during this incident.",
        ]
        return "\n".join(lines)
