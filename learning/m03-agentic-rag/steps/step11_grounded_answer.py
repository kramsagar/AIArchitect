"""Step 11 - the Module 3 deliverable: validated Answer JSON + grounding (drop citations no tool returned)
+ refusal when nothing is left. This is m03_rag.agent.KnowledgeAgent, which `m03 ask` runs.

Run:  python steps/step11_grounded_answer.py "how do I rotate the TLS certificate on the edge proxy?"
"""

import re
import sys

import step10_retrieval_tool_agent as s10
from common import llm
from pydantic import ValidationError

from m03_rag.agent import SYSTEM, Answer
from m03_rag.llm import json_from


def ground(answer: Answer, seen: set[str]) -> Answer:
    kept = [c for c in dict.fromkeys(answer.citations) if c in seen]
    if not kept and not answer.insufficient_evidence:
        return answer.model_copy(update={"citations": [], "confidence": "low", "insufficient_evidence": True})
    return answer.model_copy(update={"citations": kept, "confidence": "low" if len(kept) < len(answer.citations)
                                     else answer.confidence})  # fmt: skip


if __name__ == "__main__":
    s10.HELPER, s10.SYSTEM = llm(), SYSTEM  # the strict system prompt asks for the Answer JSON
    text, calls = s10.agent(" ".join(sys.argv[1:]) or "how do I rotate the TLS certificate on the edge proxy?")
    seen = {i for _, _, out in calls for i in re.findall(r"[\w-]+#[\w-]+", out)}
    try:
        answer = Answer.model_validate(json_from(text) or {})
    except ValidationError:
        answer = Answer(answer="No grounded answer.", citations=[], confidence="low", insufficient_evidence=True)
    print(ground(answer, seen).model_dump_json(indent=2))
