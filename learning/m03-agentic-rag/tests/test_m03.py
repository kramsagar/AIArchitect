"""Offline tests for Module 3 (mock LLM, no key)."""

import json

import pytest
from m02_obs.rag.chunking import Chunk

from m03_rag.agent import Answer, KnowledgeAgent, MockKnowledgeClient
from m03_rag.bm25 import BM25Index, tokenize
from m03_rag.crag import corrective_retrieve
from m03_rag.eval import EVAL_SET, evaluate, metrics
from m03_rag.graph import ServiceGraph
from m03_rag.hybrid import HybridRetriever, rrf
from m03_rag.llm import MockText, json_from
from m03_rag.rerank import lexical_rerank, llm_rerank
from m03_rag.rewrite import decompose, rewrite


@pytest.fixture(scope="module")
def retriever():
    return HybridRetriever()


def test_tokenize_keeps_error_codes_whole():
    assert "pg-53300" in tokenize("Error PG-53300 too_many_connections") and "53300" in tokenize("PG-53300")


def test_bm25_finds_exact_codes(retriever):
    assert BM25Index(retriever.chunks).search("PAY-503-UPSTREAM", k=1)[0][0].id == "incidents#inc-4203-pay-503-upstream"


def test_rrf_rewards_agreement():
    a, b, c = (Chunk(i, "d", i, i) for i in "abc")
    fused = rrf({"bm25": [a, b, c], "vector": [b, a, c]})
    assert {fused[0].chunk.id, fused[1].chunk.id} == {"a", "b"} and fused[2].chunk.id == "c"
    assert fused[0].sources.keys() == {"bm25", "vector"}


def test_hybrid_filters_by_type(retriever):
    assert all(
        r.chunk.metadata["type"] == "incident" for r in retriever.search("slow", k=5, filters={"type": "incident"})
    )


def test_lexical_rerank_and_llm_rerank_fallback(retriever):
    cands = retriever.search("is it safe to retry a payment charge", k=20)
    top = lexical_rerank("is it safe to retry a payment charge", cands, k=3)
    assert len(top) == 3 and top[0].score >= top[-1].score

    class Broken:
        calls = 0

        def complete(self, *a, **k):
            return "not json"

    assert [r.chunk.id for r in llm_rerank(Broken(), "x", cands, 3)] == [
        r.chunk.id for r in lexical_rerank("x", cands, 3)
    ]


def test_query_transforms_with_mock():
    llm = MockText()
    assert "slow" in rewrite(llm, "purchase flow sluggish")
    assert len(decompose(llm, "is redis healthy and who owns postgres?")) == 2
    assert json_from('```json\n{"a": 1}\n```') == {"a": 1}


def test_corrective_retrieval_records_attempts(retriever):
    res = corrective_retrieve(retriever, MockText(), "PG-53300 in the shop logs")
    assert res.sufficient and res.attempts[0].strategy == "original" and "incidents#inc-4188-pg-53300" in res.ids

    class NeverRelevant(MockText):
        def complete(self, system, user, max_tokens=600):
            return "{}" if "[grade]" in system else super().complete(system, user, max_tokens)

    res = corrective_retrieve(retriever, NeverRelevant(), "anything", max_attempts=3)
    assert not res.sufficient and [a.strategy for a in res.attempts] == ["original", "rewrite", "decompose"]
    assert res.chunks == []


def test_service_graph_blast_radius_and_owner():
    g = ServiceGraph()
    assert g.blast_radius("postgres") == ["edge-proxy", "loadgen", "shopsphere-shop"]
    assert g.describe("payments-service")["owner"]["oncall"] == "payments-oncall"
    assert "error" in g.describe("nope")


def test_metrics():
    assert metrics(["x", "a"], {"a"}, 3) == {"hit": 1.0, "recall": 1.0, "mrr": 0.5, "ndcg": pytest.approx(0.631, 0.01)}
    assert metrics(["x"], {"a"}, 3)["hit"] == 0.0


def test_eval_baseline_does_not_regress(retriever):
    report = evaluate(("bm25", "hybrid", "hybrid+rerank"), k=3, retriever=retriever)
    assert len(EVAL_SET) >= 18
    assert all(row["hit@3"] >= 0.8 for row in report.values())


def test_agent_offline_cites_graph_for_relationship_question(retriever):
    agent = KnowledgeAgent(MockKnowledgeClient(), "mock", retriever=retriever)
    answer, meta = agent.ask("what is affected if redis fails?")
    assert [t["tool"] for t in agent.trace] == ["search_knowledge", "service_graph"]
    assert "service-graph#dependencies" in answer.citations and len(set(answer.citations)) == len(answer.citations)
    assert set(answer.citations) <= set(meta["seen_ids"])


def test_grounding_drops_invented_citations():
    a = Answer(answer="x", citations=["runbooks#real", "runbooks#invented"], confidence="high")
    g = KnowledgeAgent._ground(a, {"runbooks#real"})
    assert g.citations == ["runbooks#real"] and g.confidence == "low"
    none = KnowledgeAgent._ground(Answer(answer="x", citations=["a#b"], confidence="high"), set())
    assert none.insufficient_evidence and none.citations == []


def test_agent_parse_failure_falls_back():
    from types import SimpleNamespace

    resp = SimpleNamespace(content=[SimpleNamespace(type="text", text="no json here")])
    assert KnowledgeAgent._parse(resp).insufficient_evidence


def test_cli_offline(capsys):
    from m03_rag.cli import main

    assert main(["graph", "redis"]) == 0 and json.loads(capsys.readouterr().out)["service"] == "redis"
    assert main(["search", "PG-53300", "-k", "1"]) == 0 and "pg-53300" in capsys.readouterr().out
    assert main(["ask", "PG-53300 in the shop logs"]) == 0 and "incidents#inc-4188-pg-53300" in capsys.readouterr().out
