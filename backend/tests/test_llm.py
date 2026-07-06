from types import SimpleNamespace as NS

import litellm
import pytest

from src.engine import llm


def _resp(content=None, tool_calls=None):
    return NS(choices=[NS(message=NS(content=content, tool_calls=tool_calls))])


def _tool_call(name, arguments, id="call_1"):
    return NS(id=id, function=NS(name=name, arguments=arguments))


@pytest.fixture(autouse=True)
def no_pacing(monkeypatch):
    monkeypatch.setenv("LLM_PACING_SECONDS", "0")


def test_returns_final_text_without_tools(monkeypatch):
    monkeypatch.setattr(litellm, "completion", lambda **k: _resp(content="report"))
    assert llm.run_agent("sys", "user") == "report"


def test_executes_requested_tool_and_feeds_result_back(monkeypatch):
    responses = [
        _resp(tool_calls=[_tool_call("echo", '{"query": "hi"}')]),
        _resp(content="done"),
    ]
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    monkeypatch.setattr(litellm, "completion", fake_completion)
    events = []
    out = llm.run_agent(
        "sys", "user",
        tool_schemas=[{"type": "function", "function": {"name": "echo"}}],
        tool_functions={"echo": lambda query: f"echo:{query}"},
        on_event=events.append,
    )
    assert out == "done"
    tool_msgs = [m for m in calls[1]["messages"] if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == "echo:hi"
    assert events == [{"type": "tool_call", "tool": "echo", "detail": "hi"}]


def test_tool_cap_forces_final_answer(monkeypatch):
    def always_wants_tools(**kwargs):
        if "tools" in kwargs:
            return _resp(tool_calls=[_tool_call("echo", '{"query": "again"}')])
        return _resp(content="forced final")

    monkeypatch.setattr(litellm, "completion", always_wants_tools)
    out = llm.run_agent(
        "sys", "user",
        tool_schemas=[{"type": "function", "function": {"name": "echo"}}],
        tool_functions={"echo": lambda query: "r"},
    )
    assert out == "forced final"


def test_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    attempts = []

    def flaky(**kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            err = Exception("rate limited")
            err.status_code = 429
            raise err
        return _resp(content="ok")

    monkeypatch.setattr(litellm, "completion", flaky)
    assert llm.run_agent("sys", "user") == "ok"
    assert len(attempts) == 3


def test_non_retryable_error_raises(monkeypatch):
    def bad(**kwargs):
        err = Exception("invalid key")
        err.status_code = 401
        raise err

    monkeypatch.setattr(litellm, "completion", bad)
    with pytest.raises(Exception, match="invalid key"):
        llm.run_agent("sys", "user")
