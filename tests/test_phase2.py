
from core.rag import RAGStore, chunk_text
from core.cost_tracker import CostTracker, UsageRecord


def test_chunk_text():
    text = "word " * 200
    chunks = chunk_text(text, size=100, overlap=20)
    assert len(chunks) > 1
    assert all(len(c) <= 120 for c in chunks)


def test_rag_ingest_and_search(tmp_path):
    rag = RAGStore(chroma_path=str(tmp_path / "chroma"))
    n = rag.ingest_text(
        "Cold Mode Protocol requires five verification steps before critical actions. "
        "Confidence must be at least 0.75. Fallback scripts are required for execute operations.",
        source="cold_mode_test",
    )
    assert n >= 1
    hits = rag.search("Cold Mode verification steps", n=3)
    assert len(hits) >= 1
    assert "Cold Mode" in hits[0]["content"]


def test_rag_ingest_file(tmp_path):
    doc = tmp_path / "test.md"
    doc.write_text("# Nexus\n\nAgentic AI framework with orchestrator and Cold Mode safety.")
    rag = RAGStore(chroma_path=str(tmp_path / "chroma2"))
    n = rag.ingest_file(doc)
    assert n >= 1
    ctx = rag.format_context("orchestrator safety")
    assert "Cold Mode" in ctx or "orchestrator" in ctx.lower()


def test_cost_tracker(tmp_path):
    db = str(tmp_path / "costs.db")
    tracker = CostTracker(db)
    tracker.record(UsageRecord(
        provider="ollama", model="llama3.1", tier="cheap",
        prompt_tokens=100, completion_tokens=50, cost_usd=0.0, agent="osint",
    ))
    tracker.record(UsageRecord(
        provider="gemini", model="gemini-2.0-flash", tier="cheap",
        prompt_tokens=500, completion_tokens=200, cost_usd=0.001, agent="orchestrator",
    ))
    summary = tracker.summary()
    assert summary["total_requests"] == 2
    assert summary["total_tokens"] == 850
    assert "gemini" in summary["by_provider"] or "ollama" in summary["by_provider"]
