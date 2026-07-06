from src.engine import pipeline


def test_happy_path_event_order(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline.llm, "run_agent", lambda *a, **k: "report")
    events = list(pipeline.run_valuation("Acme", "AI dog walking", logs_dir=tmp_path))
    types = [e["type"] for e in events]
    assert types[:6] == ["agent_init"] * 6
    assert types.count("agent_active") == 6
    assert types.count("agent_done") == 6
    assert types[-1] == "complete"
    assert events[-1]["memo"] == "report"


def test_prior_reports_flow_forward(monkeypatch, tmp_path):
    seen = []

    def fake(system_prompt, task, **kwargs):
        seen.append(task)
        return "r"

    monkeypatch.setattr(pipeline.llm, "run_agent", fake)
    list(pipeline.run_valuation("Acme", "pitch", logs_dir=tmp_path))
    assert "earlier analysts" not in seen[0]
    assert "earlier analysts" in seen[5]


def test_tool_events_carry_agent_id(monkeypatch, tmp_path):
    def fake(system_prompt, task, tool_schemas=None, tool_functions=None, on_event=None):
        if on_event:
            on_event({"type": "tool_call", "tool": "web_search", "detail": "q"})
        return "r"

    monkeypatch.setattr(pipeline.llm, "run_agent", fake)
    events = list(pipeline.run_valuation("Acme", "p", logs_dir=tmp_path))
    tool_events = [e for e in events if e["type"] == "tool_call"]
    assert tool_events and all("id" in e for e in tool_events)


def test_failure_stops_pipeline_and_preserves_partials(monkeypatch, tmp_path):
    calls = []

    def flaky(system_prompt, task, **kwargs):
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError("boom")
        return "r"

    monkeypatch.setattr(pipeline.llm, "run_agent", flaky)
    events = list(pipeline.run_valuation("Acme", "p", logs_dir=tmp_path))
    types = [e["type"] for e in events]
    assert types.count("agent_done") == 2
    assert types[-1] == "agent_error"
    assert len(calls) == 3  # agents 4-6 never ran


def test_trace_file_written(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline.llm, "run_agent", lambda *a, **k: "report text")
    list(pipeline.run_valuation("Acme", "p", logs_dir=tmp_path))
    files = list(tmp_path.glob("agent-trace-*.md"))
    assert len(files) == 1
    assert "report text" in files[0].read_text()
