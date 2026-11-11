"""Step 7 - errors are data. Concepts: unknown tool, invalid arguments and tool failures become an
is_error tool_result the model can read and recover from, instead of crashing the program.

Run:  python steps/step07_tool_errors.py
"""

import json
import logging
from types import SimpleNamespace

from common import client
from pydantic import ValidationError
from step05_agent_loop import run_agent
from step06_two_tools import SYSTEM6, TOOLS


class ToolError(Exception):
    """A failure the model should be told about (bad input, not found). Not retried."""


class TransientError(ToolError):
    """A temporary failure (timeout, HTTP 503). Safe to retry for read-only tools (step 8)."""


def default_run(tool, args):
    return tool.fn(args)


def safe_execute(call, tools: dict, run=default_run) -> dict:
    def error(message: str) -> dict:
        return {"type": "tool_result", "tool_use_id": call.id, "content": message, "is_error": True}

    tool = tools.get(call.name)
    if tool is None:
        return error(f"unknown tool '{call.name}'. Available: {', '.join(tools)}")
    try:
        args = tool.args_model.model_validate(call.input)
    except ValidationError as exc:
        first = exc.errors()[0]
        return error(f"invalid arguments: {first['msg']} (field: {'.'.join(map(str, first['loc'])) or '-'})")
    try:
        result = run(tool, args)
    except (ToolError, ValueError, LookupError) as exc:  # expected failures: tell the model exactly what happened
        return error(f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # a bug in OUR code: log it, but do not leak internals to the model
        logging.exception("tool %s crashed: %r", call.name, exc)
        return error("internal error in tool")
    return {"type": "tool_result", "tool_use_id": call.id, "content": json.dumps(result)}


def main() -> None:
    print("Offline: what the model receives for each kind of failure")
    for name, args in [
        ("get_metrics", {"service": "checkout-api"}),
        ("get_service_health", {"name": "checkout-api"}),
        ("get_service_health", {"service": "checkout"}),
        ("capacity_calculator", {"expression": "open('secrets.txt')"}),
    ]:
        result = safe_execute(SimpleNamespace(id="t1", name=name, input=args), TOOLS)
        print(f"   {name}({args}) -> {result['content']}")

    print("\nAgent with a wrong service name: watch it read the error and correct itself")
    print("\n" + run_agent(client(), "Is checkout healthy?", tools=TOOLS, system=SYSTEM6, execute=safe_execute))


if __name__ == "__main__":
    main()
