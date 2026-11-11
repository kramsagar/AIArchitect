"""Safe capacity / SLO calculator. Parses the expression into an AST and evaluates a whitelist only -
never `eval()` model-generated text."""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable

from ..errors import ToolError
from ..schemas import CalculationResult, CapacityCalcArgs

MAX_NODES = 100
MAX_EXPONENT = 64


def _pct(x: float, name: str) -> float:
    if not 0 < x <= 100:
        raise ValueError(f"{name} must be a percentage in (0, 100], got {x}")
    return x / 100


def error_budget_minutes(slo_pct: float, days: float = 30) -> float:
    """Allowed downtime for an availability SLO over a window."""
    if not 0 < slo_pct < 100:
        raise ValueError("slo_pct must be between 0 and 100 (exclusive)")
    return (100 - slo_pct) / 100 * days * 24 * 60


def burn_rate(error_rate_pct: float, slo_pct: float) -> float:
    """How fast the error budget is consumed: 1.0 = exactly on budget, 14.4 = 30-day budget gone in ~2 days."""
    if not 0 < slo_pct < 100:
        raise ValueError("slo_pct must be between 0 and 100 (exclusive)")
    return error_rate_pct / (100 - slo_pct)


def concurrency(tps: float, latency_ms: float) -> float:
    """Little's law: L = lambda * W -> requests in flight (threads, connections, pool size needed)."""
    if tps < 0 or latency_ms < 0:
        raise ValueError("tps and latency_ms must be >= 0")
    return tps * latency_ms / 1000


def replicas_needed(target_tps: float, tps_per_replica: float, headroom_pct: float = 30) -> float:
    if tps_per_replica <= 0:
        raise ValueError("tps_per_replica must be > 0")
    return float(math.ceil(target_tps * (1 + headroom_pct / 100) / tps_per_replica))


def serial_availability(*availability_pcts: float) -> float:
    """Hard dependencies in series multiply: 99.9% * 99.9% = 99.8%."""
    if not availability_pcts:
        raise ValueError("need at least one availability")
    return math.prod(_pct(a, "availability") for a in availability_pcts) * 100


def parallel_availability(availability_pct: float, n: float) -> float:
    """N independent redundant copies: 1 - (1 - a)^n."""
    if n < 1:
        raise ValueError("n must be >= 1")
    return (1 - (1 - _pct(availability_pct, "availability")) ** n) * 100


FUNCTIONS: dict[str, Callable[..., float]] = {
    "error_budget_minutes": error_budget_minutes,
    "burn_rate": burn_rate,
    "concurrency": concurrency,
    "replicas_needed": replicas_needed,
    "serial_availability": serial_availability,
    "parallel_availability": parallel_availability,
    "sqrt": math.sqrt,
    "ceil": math.ceil,
    "floor": math.floor,
    "round": round,
    "min": min,
    "max": max,
    "abs": abs,
    "log": math.log,
    "log10": math.log10,
}
CONSTANTS = {"pi": math.pi, "e": math.e}
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def evaluate(expression: str) -> float:
    expr = expression.replace("^", "**").replace(",", ", ")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ToolError(f"invalid expression syntax: {exc.msg}") from exc
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise ToolError("expression too complex")
    try:
        value = _eval(tree.body)
    except ZeroDivisionError as exc:
        raise ToolError("division by zero") from exc
    except (ValueError, TypeError, OverflowError) as exc:
        raise ToolError(f"math error: {exc}") from exc
    if not math.isfinite(value):
        raise ToolError("result is not a finite number")
    return float(value)


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise ToolError(f"exponent larger than {MAX_EXPONENT} is not allowed")
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Name) and node.id in CONSTANTS:
        return CONSTANTS[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS:
        if node.keywords:
            raise ToolError("keyword arguments are not supported; pass positional arguments")
        return FUNCTIONS[node.func.id](*[_eval(a) for a in node.args])
    raise ToolError(f"unsupported syntax: {ast.dump(node)[:60]}")


def calculate(args: CapacityCalcArgs) -> CalculationResult:
    return CalculationResult(expression=args.expression, result=round(evaluate(args.expression), 6))
