"""Offline smoke tests for steps/ (mock LLM)."""

import os
import sys
from pathlib import Path

os.environ["M03_OFFLINE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "steps"))

import step01_bm25 as s1  # noqa: E402
import step02_hybrid_rrf as s2  # noqa: E402
import step03_eval as s3  # noqa: E402
import step08_corrective_rag as s8  # noqa: E402
import step09_service_graph as s9  # noqa: E402
import step11_grounded_answer as s11  # noqa: E402

from m03_rag.agent import Answer  # noqa: E402
from m03_rag.llm import MockText  # noqa: E402


def test_bm25_and_hybrid_find_codes():
    assert s1.bm25("PG-53300", 1) == ["incidents#inc-4188-pg-53300"]
    assert "incidents#inc-4188-pg-53300" in s2.hybrid("PG-53300 in the shop logs")


def test_eval_scoring():
    assert s3.score(["x", "a"], {"a"})[:2] == (1.0, 0.5)


def test_corrective_refuses_when_nothing_relevant():
    ids, log = s8.corrective(MockText(), "how do I rotate the TLS certificate on the edge proxy?")
    assert ids == [] and len(log) == 3


def test_graph_and_grounding():
    assert s9.blast_radius("postgres") == ["edge-proxy", "loadgen", "shopsphere-shop"]
    g = s11.ground(Answer(answer="x", citations=["a#b"], confidence="high"), set())
    assert g.insufficient_evidence and g.citations == []
