"""Lab 4 - structured output with Pydantic: schema, validation, repair loop.

Run: python -m m01_agent.labs.l04_structured_output"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..jsonschema import strict_json_schema
from ..tools.registry import format_validation_error


class IncidentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    severity: Literal["SEV1", "SEV2", "SEV3", "SEV4"]
    impact: str = Field(max_length=200)
    suspected_cause: str
    evidence: list[str] = Field(min_length=1, description="Facts with numbers that support the cause")
    next_actions: list[str] = Field(min_length=1, max_length=5)
    customer_facing: bool

    @field_validator("evidence")
    @classmethod
    def evidence_has_numbers(cls, v: list[str]) -> list[str]:
        if not any(ch.isdigit() for item in v for ch in item):
            raise ValueError("at least one evidence item must contain a number (metric, count, timestamp)")
        return v


MODEL_OUTPUTS = [
    # 1st try: typical LLM mistakes - prose wrapper, wrong enum, missing field, no numbers in evidence
    'Sure! Here is the summary: {"service": "Checkout API", "severity": "high", "impact": "slow checkout", '
    '"suspected_cause": "db", "evidence": ["db is slow"], "next_actions": ["look at it"]}',
    # 2nd try after feedback
    '{"service": "checkout-api", "severity": "SEV2", "impact": "p99 620ms vs 300ms SLO, ~4% checkouts time out", '
    '"suspected_cause": "DB pool reduced 50->20 in v2.31.0", "evidence": ["pool_in_use 20/20", '
    '"p99 620ms since deploy 25m ago"], "next_actions": ["roll back v2.31.0", "watch burn rate"], '
    '"customer_facing": true}',
]


def extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


def parse_with_repair(outputs: list[str], max_attempts: int = 3) -> tuple[IncidentSummary | None, list[str]]:
    log = []
    for attempt, raw in enumerate(outputs[:max_attempts], 1):
        try:
            return IncidentSummary.model_validate_json(extract_json(raw)), log
        except ValidationError as exc:
            msg = format_validation_error(exc)
            log.append(f"attempt {attempt}: {msg}")
    return None, log


def main() -> None:
    print("== Strict JSON schema sent to the model (response_format / output_type) ==")
    print(json.dumps(strict_json_schema(IncidentSummary), indent=2)[:900], "...")
    result, log = parse_with_repair(MODEL_OUTPUTS)
    print("\n== Repair loop ==")
    for line in log:
        print(" ", line)
    print("\nValidated object:", result.model_dump() if result else None)
    print(
        "\nRule: the schema is the API contract between the model and your code. Validate every time, feed the\n"
        "errors back (bounded retries), and fail closed if it never validates."
    )


if __name__ == "__main__":
    main()
