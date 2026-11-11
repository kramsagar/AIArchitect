import time

from m02_obs.memory import LongTermMemory, SessionMemory, redact
from m02_obs.rag.chunking import chunk_markdown
from m02_obs.rag.index import KnowledgeBase
from m02_obs.rag.store import VectorStore

DOC = """---
type: runbook
---
# Runbooks
## checkout-latency
Signal: ShopSphereCheckoutLatencySLO. Look at payments-service spans.

## empty
"""


def test_chunker_uses_headings_and_metadata():
    chunks = chunk_markdown(DOC, "runbooks")
    assert [c.id for c in chunks] == ["runbooks#checkout-latency"]
    c = chunks[0]
    assert c.text.startswith("Runbooks > checkout-latency")
    assert c.metadata["type"] == "runbook"
    assert "payments-service" in c.metadata["services"]
    assert c.metadata["alerts"] == ["ShopSphereCheckoutLatencySLO"]


def test_long_sections_split_with_overlap():
    body = "\n\n".join(f"paragraph {i} " + "x" * 300 for i in range(6))
    chunks = chunk_markdown(f"# T\n## big\n{body}", "d", max_chars=700)
    assert len(chunks) > 1 and chunks[0].id == "d#big-1"
    assert chunks[0].text.splitlines()[-1] in chunks[1].text  # last paragraph carried over


def test_retrieval_eval_baseline():
    r = KnowledgeBase.from_dirs().evaluate(k=3)
    assert r["recall_at_k"] >= 0.9 and r["mrr"] >= 0.6


def test_metadata_filter_and_persistence(tmp_path):
    kb = KnowledgeBase.from_dirs()
    hits = kb.search("payments latency", k=5, filters={"type": "postmortem"})
    assert hits and all(h.chunk.metadata["type"] == "postmortem" for h in hits)
    kb.store.save(tmp_path / "kb.json")
    loaded = VectorStore.load(tmp_path / "kb.json")
    assert len(loaded) == len(kb.store)


def test_session_memory_compacts_old_turns():
    m = SessionMemory(max_turns=2)
    for i in range(4):
        m.add(f"question {i}", f"answer {i}. details")
    assert len(m.turns) == 2 and "question 0" in m.summary
    assert m.messages()[0]["content"].startswith("(Summary")


def test_redaction():
    out = redact("key sk-ant-abcdefghijklmnopqrst password=hunter2 mail bob@example.com card 4111 1111 1111 1111")
    assert "sk-ant" not in out and "hunter2" not in out and "bob@" not in out and "4111" not in out


def test_long_term_facts_ttl_and_episodes(tmp_path):
    ltm = LongTermMemory(tmp_path / "m.db")
    ltm.remember("payments_timeout", "2s")
    ltm.remember("tmp", "x", ttl_s=0.01)
    time.sleep(0.02)
    assert ltm.facts() == {"payments_timeout": "2s"}
    ltm.record_episode("why is checkout slow", "payments slow", "payment provider latency", ["payments-service"])
    assert ltm.recall("checkout is slow again")[0]["root_cause"] == "payment provider latency"
    assert LongTermMemory(tmp_path / "m.db").episodes()  # survives a restart
