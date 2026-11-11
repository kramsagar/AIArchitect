"""Error taxonomy. The type decides the handling: retry, report to the model, or abort."""


class ToolError(Exception):
    """A tool failed in a way the model should be told about (bad input, unknown city, ...). Not retried."""

    error_type = "tool_error"


class TransientToolError(ToolError):
    """A temporary upstream failure (HTTP 503, rate limit, connection reset). Safe to retry if idempotent."""

    error_type = "transient_error"


class ToolTimeoutError(TransientToolError):
    """The tool exceeded its time budget."""

    error_type = "timeout"


class LLMError(Exception):
    """The model provider failed after its own transport-level retries."""
