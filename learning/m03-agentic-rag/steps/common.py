"""Shared by every Module 3 step: .env, the corpus, and an LLM that is Claude if a key is set, else the offline mock."""

import os

from m01_agent.config import load_dotenv
from m02_obs.rag.chunking import load_corpus

from m03_rag.hybrid import corpus_dirs
from m03_rag.llm import ClaudeText, MockText

load_dotenv()
MODEL = os.getenv("AGENT_MODEL", "claude-haiku-5-5")
CHUNKS = load_corpus(corpus_dirs())  # runbooks + postmortems + incidents + architecture + service graph + SLO policy
BY_ID = {c.id: c for c in CHUNKS}


def llm():
    if os.getenv("ANTHROPIC_API_KEY") and os.getenv("M03_OFFLINE") != "1":
        print(f"(LLM: Claude {MODEL})")
        return ClaudeText(MODEL)
    print("(LLM: offline mock - set ANTHROPIC_API_KEY in .env for Claude)")
    return MockText()
