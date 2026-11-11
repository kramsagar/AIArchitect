"""Step 2 - structured output. Concepts: a Pydantic model as the contract, JSON schema, validation errors.

Run:  python steps/step02_structured_output.py
"""

import json
from typing import Literal

from anthropic import transform_schema
from common import MODEL, client, text_of
from pydantic import BaseModel, Field, ValidationError


class HealthVerdict(BaseModel):
    """The contract: code downstream (paging, dashboards) can rely on these fields and types."""

    service: str
    severity: Literal["ok", "warning", "critical"]
    summary: str = Field(description="One sentence with the key numbers")
    actions: list[str] = Field(description="Ordered next actions; empty if none")


METRICS = "checkout-api: p99=620ms (SLO 300ms), error_rate=0.42%, saturation=91%, v2.31.0 deployed 25m ago"


def get_verdict(c, metrics: str) -> HealthVerdict:
    resp = c.messages.create(
        model=MODEL,
        max_tokens=500,
        system="You are an SRE. severity: critical if p99 is above its SLO, warning if saturation >= 85%, else ok.",
        messages=[{"role": "user", "content": f"Judge this service: {metrics}"}],
        # Constrained decoding: Claude can ONLY produce JSON that matches this schema.
        output_config={"format": {"type": "json_schema", "schema": transform_schema(HealthVerdict)}},
    )
    raw = text_of(resp)
    print("raw text from Claude:\n", raw)
    return HealthVerdict.model_validate_json(raw)  # never trust, always validate


def main() -> None:
    print("JSON schema sent to the model:\n", json.dumps(HealthVerdict.model_json_schema(), indent=1)[:600], "...\n")
    verdict = get_verdict(client(), METRICS)
    print("\nnow it is a typed Python object:", repr(verdict.severity), verdict.actions[:2])
    if verdict.severity == "critical":
        print("-> code can act on it: PAGE the on-call engineer")

    print("\nWhat validation catches (a bad reply):")
    try:
        HealthVerdict.model_validate_json('{"service": "checkout-api", "severity": "meh", "summary": "?"}')
    except ValidationError as exc:
        print(exc)


if __name__ == "__main__":
    main()
