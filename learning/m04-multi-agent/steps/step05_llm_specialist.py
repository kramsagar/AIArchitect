"""Step 5 - an LLM specialist inside a node: the RCA agent gets the evidence as JSON, returns a `RootCause` JSON,
and we GROUND it: evidence ids it cites that no investigator produced are dropped and confidence is lowered.

Run:  python steps/step05_llm_specialist.py
"""

import json

from common import llm, tools
from step04_parallel_fanout import build

from m04_crew.crew import RCA_SYSTEM, Crew
from m04_crew.llm import MockCrewLLM, json_from
from m04_crew.state import RootCause


def ground(rc: RootCause, known: set[str]) -> RootCause:
    kept = [i for i in dict.fromkeys(rc.evidence_ids) if i in known]
    conf = (
        "low"
        if not kept
        else ("medium" if len(kept) < len(rc.evidence_ids) and rc.confidence == "high" else rc.confidence)
    )
    return rc.model_copy(update={"evidence_ids": kept, "confidence": conf})


if __name__ == "__main__":
    state = build(Crew(tools(), MockCrewLLM())).invoke({"alert": "checkout latency SLO"})
    model = llm()
    payload = {"symptom": state["symptom"], "evidence": state["evidence"]}
    raw = model.complete(RCA_SYSTEM, json.dumps(payload))
    rc = RootCause.model_validate(json_from(raw))
    print("model said :", rc.model_dump_json())
    print("grounded   :", ground(rc, {e["id"] for e in state["evidence"]}).model_dump_json())
    fake = rc.model_copy(update={"evidence_ids": [*rc.evidence_ids, "trace:deadbeef"]})
    print("with a made-up id:", ground(fake, {e["id"] for e in state["evidence"]}).confidence)
