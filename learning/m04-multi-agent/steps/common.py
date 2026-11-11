"""Shared by every Module 4 step: .env, the offline fixture world (or the live lab), and an LLM that is Claude if a
key is set, else the deterministic mock."""

import os

from m01_agent.config import load_dotenv

from m04_crew.llm import ClaudeText, MockCrewLLM
from m04_crew.tools import Toolbox

load_dotenv()
MODEL = os.getenv("AGENT_MODEL", "claude-haiku-5-5")
BACKEND = os.getenv("OBS_BACKEND", "fixture")  # set OBS_BACKEND=live with the Docker lab running
SCENARIO = os.getenv("OBS_FIXTURE_SCENARIO", "checkout-latency")


def tools() -> Toolbox:
    return Toolbox(BACKEND, SCENARIO)


def llm():
    if os.getenv("ANTHROPIC_API_KEY") and os.getenv("M04_OFFLINE") != "1":
        print(f"(LLM: Claude {MODEL})")
        return ClaudeText(MODEL)
    print("(LLM: offline mock - set ANTHROPIC_API_KEY in .env for Claude)")
    return MockCrewLLM()
