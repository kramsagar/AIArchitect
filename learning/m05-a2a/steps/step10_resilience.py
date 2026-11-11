"""Step 10 - remote agents fail: down, slow, or wrong. The caller must degrade, not hang.

New idea: every hop gets a timeout and bounded retries (M1's RetryPolicy); when an investigator is DOWN the
incident still proceeds with less evidence (graceful degradation) instead of failing the whole response."""

import time

from common import title

from m05_a2a.client import A2AClient

client = A2AClient(["http://127.0.0.1:9399"], token="", timeout_s=1.0)  # nothing listens here
client.skills = {"logs": ("telemetry-agent", "http://127.0.0.1:9399/a2a/jsonrpc")}
t0 = time.perf_counter()
try:
    client.call("logs", {})
except Exception as e:  # noqa: BLE001
    title(f"agent down -> {type(e).__name__} after {time.perf_counter() - t0:.2f}s (3 attempts with jittered backoff)")


def logs_or_degraded(state):
    try:
        return client.call("logs", state)
    except Exception:  # noqa: BLE001  (A2AError, transport errors, bad JSON)
        return {"evidence": [], "timeline": [{"node": "logs", "event": "DEGRADED: telemetry-agent unavailable"}]}


title("graceful degradation")
print(logs_or_degraded({}))
