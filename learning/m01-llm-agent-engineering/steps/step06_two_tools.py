"""Step 6 - a second tool + multi-step reasoning. Concepts: a SAFE calculator (AST whitelist, never eval),
tool-selection rules in the prompt, chaining: the result of tool 1 becomes the input of tool 2.

Run:  python steps/step06_two_tools.py
      python steps/step06_two_tools.py "Can payments-gateway handle 3x traffic?"
"""

import ast
import math
import operator
import sys

from common import client
from pydantic import BaseModel, ConfigDict, Field
from step03_tool_schema import HEALTH_TOOL, Tool
from step05_agent_loop import SYSTEM, run_agent


def replicas_needed(target_rps: float, rps_per_replica: float, headroom_pct: float = 30) -> float:
    return float(math.ceil(target_rps * (1 + headroom_pct / 100) / rps_per_replica))


def burn_rate(error_rate_pct: float, slo_pct: float) -> float:
    """1.0 = spending the error budget exactly on time; 14.4 = a 30-day budget gone in ~2 days."""
    return error_rate_pct / (100 - slo_pct)


def concurrency(rps: float, latency_ms: float) -> float:
    """Little's law: requests in flight = arrival rate x time in system."""
    return rps * latency_ms / 1000


FUNCS = {"replicas_needed": replicas_needed, "burn_rate": burn_rate, "concurrency": concurrency, "ceil": math.ceil}
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def safe_eval(expression: str) -> float:
    """Walk the syntax tree and allow ONLY numbers, + - * /, unary minus and whitelisted functions."""

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS:
            return FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError(f"not allowed in expression: {type(node).__name__}")

    return float(ev(ast.parse(expression, mode="eval")))


class CalcArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expression: str = Field(
        max_length=200,
        description="Arithmetic with + - * / and functions: replicas_needed(target_rps, rps_per_replica, headroom_pct)"
        ", burn_rate(error_rate_pct, slo_pct), concurrency(rps, latency_ms), ceil(x)",
    )


CALC_TOOL = Tool(
    name="capacity_calculator",
    description="Evaluate SRE/capacity math exactly. Use it for ANY arithmetic.",
    args_model=CalcArgs,
    fn=lambda args: {"expression": args.expression, "result": safe_eval(args.expression)},
)
TOOLS = {t.name: t for t in (HEALTH_TOOL, CALC_TOOL)}
SYSTEM6 = SYSTEM + (
    "\nNever do arithmetic yourself: use capacity_calculator. For 'can X handle Nx traffic?': first get X's health, "
    "then call replicas_needed(rps * N, rps / replicas, 30) and burn_rate(error_rate_pct, slo_availability_pct). "
    "Fix existing SLO breaches before scaling."
)


def main() -> None:
    print("safe_eval offline checks:")
    for expr in ("replicas_needed(12400*2, 12400/24, 30)", "burn_rate(0.42, 99.95)", "__import__('os').system('dir')"):
        try:
            print(f"   {expr} = {safe_eval(expr)}")
        except ValueError as exc:
            print(f"   {expr} -> REJECTED: {exc}")
    question = " ".join(sys.argv[1:]) or "Can checkout-api handle 2x traffic?"
    print(f"\nAgent: {question}")
    print("\n" + run_agent(client(), question, tools=TOOLS, system=SYSTEM6))


if __name__ == "__main__":
    main()
