"""The same SRE copilot built with the OpenAI Agents SDK - compare it with agent.py.

The SDK gives you the loop (Runner), tool schemas from type hints (@function_tool), structured output
(output_type), max_turns, tracing and sessions. You still own: tool safety, timeouts, retries, budgets and
grounding. Requires `pip install -e ".[sdk]"` and ANTHROPIC_API_KEY (Claude via LiteLLM) or OPENAI_API_KEY."""

from __future__ import annotations

from .config import AgentConfig
from .errors import ToolError
from .prompts import DEVELOPER_PROMPT, SYSTEM_PROMPT
from .resilience import RetryPolicy, call_with_timeout, retry_call
from .schemas import AssistantResponse, CapacityCalcArgs, ServiceHealthArgs
from .tools.capacity import calculate
from .tools.service_health import MockMetricsBackend

_backend = MockMetricsBackend()


def build_sdk_agent(config: AgentConfig | None = None):
    from agents import Agent, ModelSettings, function_tool

    config = config or AgentConfig()

    @function_tool
    def get_service_health(service: str, window_minutes: int) -> dict:
        """Get live golden signals (rps, p50/p95/p99 latency, error rate, saturation, replicas), SLO targets,
        dependency status and the most recent change for ONE service. Read-only.

        Args:
            service: Service name, e.g. 'checkout-api'.
            window_minutes: Look-back window in minutes (1-1440), use 15 if unsure.
        """
        args = ServiceHealthArgs(service=service, window_minutes=window_minutes)
        try:
            result, _ = retry_call(
                lambda: call_with_timeout(lambda: _backend(args), config.tool_timeout_s),
                RetryPolicy(max_retries=config.tool_max_retries),
            )
        except ToolError as exc:  # returned to the model as data, same as our own runtime
            return {"ok": False, "error": str(exc), "error_type": exc.error_type}
        return {"ok": True, "output": result.model_dump()}

    @function_tool
    def capacity_calculator(expression: str) -> dict:
        """Evaluate SRE/capacity math exactly: error_budget_minutes(slo_pct, days), burn_rate(err_pct, slo_pct),
        concurrency(tps, latency_ms), replicas_needed(target_tps, tps_per_replica, headroom_pct),
        serial_availability(a, b, ...), parallel_availability(a, n) and + - * / ** sqrt ceil floor.

        Args:
            expression: The expression to evaluate.
        """
        try:
            return {"ok": True, "output": calculate(CapacityCalcArgs(expression=expression)).model_dump()}
        except ToolError as exc:
            return {"ok": False, "error": str(exc), "error_type": exc.error_type}

    return Agent(
        name="sre-copilot",
        instructions=SYSTEM_PROMPT + "\n\n" + DEVELOPER_PROMPT,
        tools=[get_service_health, capacity_calculator],
        output_type=AssistantResponse,
        model=_sdk_model(config),
        # Newer Claude models fix sampling (temperature=1 only), so the setting is only sent to OpenAI.
        model_settings=ModelSettings(temperature=None if config.provider == "anthropic" else config.temperature),
    )


def _sdk_model(config: AgentConfig):
    """OpenAI models run natively; Claude runs through the SDK's LiteLLM adapter (pip install -e '.[sdk]')."""
    if config.provider != "anthropic":
        return config.model
    from agents import set_tracing_disabled
    from agents.extensions.models.litellm_model import LitellmModel

    set_tracing_disabled(True)  # SDK traces export to the OpenAI platform; module 7 sends them to our own OTel stack
    return LitellmModel(model=f"anthropic/{config.model}")


def run_sdk(question: str, config: AgentConfig | None = None) -> AssistantResponse:
    from agents import Runner

    config = config or AgentConfig()
    result = Runner.run_sync(build_sdk_agent(config), question, max_turns=config.max_steps)
    return result.final_output
