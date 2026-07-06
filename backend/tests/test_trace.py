from src.reporting.trace import TraceRecorder


def _run_events():
    return [
        {"type": "agent_active", "id": "market"},
        {"type": "tool_call", "id": "market", "tool": "web_search", "detail": "dog TAM"},
        {"type": "agent_done", "id": "market", "output": "**TAM**: $1.85B (https://a.com)"},
        {"type": "complete", "memo": "final"},
    ]


def test_writes_trace_file_with_searches_and_reports(tmp_path):
    rec = TraceRecorder("Acme", "AI dog walking", logs_dir=tmp_path)
    for e in _run_events():
        rec.record(e)
    path = rec.finish()
    text = path.read_text()
    assert path.name.startswith("agent-trace-") and path.suffix == ".md"
    assert "Acme" in text and "AI dog walking" in text
    assert "web_search" in text and "dog TAM" in text
    assert "$1.85B" in text


def test_records_errors(tmp_path):
    rec = TraceRecorder("Acme", "p", logs_dir=tmp_path)
    rec.record({"type": "agent_error", "id": "moat", "message": "rate limited"})
    assert "rate limited" in rec.finish().read_text()
