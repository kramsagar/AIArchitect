# 4. Structured output with Pydantic

> Lab: `python -m m01_agent.labs.l04_structured_output` · Code: `schemas.py`, `jsonschema.py`

Agents are integrated into **programs**, not chat windows: pagers, tickets, dashboards, other agents. Programs need contracts.

## Three levels of reliability
1. "Answer in JSON" in the prompt: often works, sometimes doesn't.
2. **JSON mode**: always valid JSON, any shape.
3. **Structured Outputs** (`response_format={"type":"json_schema","strict":true}`): the provider constrains decoding to your schema. Requirements for strict mode: every property in `required`, `additionalProperties: false`, limited keywords. `jsonschema.to_strict_schema` converts Pydantic models to that form; optional fields become `["type","null"]`.

**Always validate anyway** (`AssistantResponse.model_validate_json`). Providers change, fallbacks/local models may not support strict mode, and semantic checks (e.g. `severity` must agree with metrics, `tools_used` must match reality) are your job.

## Design rules for schemas
- `extra="forbid"`: unknown fields are bugs.
- Enums (`Literal["ok","warning","critical","unknown"]`) instead of free text → routable.
- Bounded fields (`max_length`, `ge/le`) to cap output tokens and abuse.
- Include `confidence` and `unknown` states; never force the model to pretend.
- Separate **reasoning-free fields for machines** (severity, intent) from **human text** (answer).

## Repair loop (what `Agent.run` does)
```
output -> validate -> ok? return
                  -> error -> send validation errors back as a user message -> retry (max_repairs)
                  -> still bad -> fail closed with a safe fallback response (status=invalid_output)
```
Bound it: each repair costs a full LLM call.

## Check yourself
1. Why does strict mode require every field to be `required`? How do you express optional?
2. What's the risk of trusting `tools_used` reported by the model? (see `Agent._finish`)
