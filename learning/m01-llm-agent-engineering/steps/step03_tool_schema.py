"""Step 3 - a tool. Concepts: a plain Python function + a Pydantic args model = a tool the model can call.
No LLM in this step: you see exactly what the model will receive and what it will send back.

Run:  python steps/step03_tool_schema.py
"""

import json
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError

# Fake metrics backend (think Prometheus/APM). Later modules replace this dict with real HTTP calls.
SERVICES = {
    "checkout-api": {
        "rps": 12400, "replicas": 24, "p99_ms": 620, "slo_p99_ms": 300, "error_rate_pct": 0.42,
        "slo_availability_pct": 99.95, "saturation_pct": 91,
        "recent_change": "v2.31.0 deployed 25m ago (DB connection pool 50 -> 20)",
    },
    "payments-gateway": {
        "rps": 3100, "replicas": 12, "p99_ms": 1450, "slo_p99_ms": 800, "error_rate_pct": 3.8,
        "slo_availability_pct": 99.99, "saturation_pct": 62, "recent_change": None,
    },
    "search-api": {
        "rps": 8800, "replicas": 16, "p99_ms": 70, "slo_p99_ms": 150, "error_rate_pct": 0.02,
        "slo_availability_pct": 99.9, "saturation_pct": 38, "recent_change": None,
    },
}  # fmt: skip


class ServiceHealthArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown keys are an error, not silently ignored
    service: str = Field(description="Exact service name, e.g. checkout-api")


def get_service_health(args: ServiceHealthArgs) -> dict:
    if args.service not in SERVICES:
        raise LookupError(f"unknown service '{args.service}'. Known services: {', '.join(SERVICES)}")
    return {"service": args.service, **SERVICES[args.service]}


@dataclass
class Tool:
    name: str
    description: str  # the model decides WHEN to call a tool from its name + description
    args_model: type[BaseModel]
    fn: Callable

    def spec(self) -> dict:
        """What the model receives: name, description, JSON schema of the arguments."""
        return {"name": self.name, "description": self.description, "input_schema": self.args_model.model_json_schema()}

    def run(self, raw_input: dict):
        """What we do when the model asks for it: validate the arguments, then call the function."""
        return self.fn(self.args_model.model_validate(raw_input))


HEALTH_TOOL = Tool(
    name="get_service_health",
    description="Get the current golden signals of ONE service: rps, replicas, p99 latency vs SLO, error rate, "
    "saturation and the most recent change. Read-only.",
    args_model=ServiceHealthArgs,
    fn=get_service_health,
)


def main() -> None:
    print("1) The tool spec sent to the model:\n", json.dumps(HEALTH_TOOL.spec(), indent=1))
    print("\n2) The model replies with a tool call like {'service': 'checkout-api'} -> we run it:")
    print("  ", HEALTH_TOOL.run({"service": "checkout-api"}))
    for bad in ({"svc": "checkout-api"}, {"service": "checkout"}):
        try:
            HEALTH_TOOL.run(bad)
        except (ValidationError, LookupError) as exc:
            print(f"\n3) Bad call {bad} -> {type(exc).__name__}: {str(exc).splitlines()[0]}")
    print("\nThe model never runs code. It only PROPOSES a call; your code validates and executes it.")


if __name__ == "__main__":
    main()
