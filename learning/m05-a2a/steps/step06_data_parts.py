"""Step 6 - structured payloads: DataPart (JSON) instead of text, and the protobuf number trap.

New idea: agents exchange STATE, not prose, so the input is {"skill", "state"} as a DataPart and the output is
a data artifact. A2A 1.x DataParts are protobuf `Value`s: every number becomes a double (0 -> 0.0).
That silently changed our idempotency key from `...:0` to `...:0.0` - `restore_ints` fixes it on both sides."""

from a2a.helpers import get_data_parts, new_data_part
from common import title

from m05_a2a.client import restore_ints

state = {"severity": "sev2", "attempts": 0, "evidence": [{"id": "trace:abc", "duration_ms": 1446}]}
part = new_data_part(state)
back = get_data_parts([part])[0]
title("after a protobuf round-trip")
print(back)
key = f"thread:reset_faults:payments:{back['attempts']}"
print("idempotency key:", key, "<- WRONG, a retry with attempts=0 would not match")
title("restore_ints")
fixed = restore_ints(back)
print(fixed, "->", f"thread:reset_faults:payments:{fixed['attempts']}")
assert fixed == state
