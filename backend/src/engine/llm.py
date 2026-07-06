import json
import os
import time

import litellm

MAX_TOOL_CALLS = 8
MAX_RETRIES = 5


def _model() -> str:
    return os.environ.get("LLM_MODEL", "groq/llama-3.3-70b-versatile")


def _pacing() -> float:
    return float(os.environ.get("LLM_PACING_SECONDS", "2"))


def _completion_with_retry(**kwargs):
    delay = 2.0
    for attempt in range(MAX_RETRIES):
        try:
            response = litellm.completion(**kwargs)
            time.sleep(_pacing())  # stay under Groq free-tier req/min limits
            return response
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            retryable = status == 429 or (status is not None and status >= 500)
            if not retryable or attempt == MAX_RETRIES - 1:
                raise
            time.sleep(delay)
            delay *= 2


def run_agent(system_prompt, user_message, tool_schemas=None, tool_functions=None,
              on_event=None):
    """Run one agent to completion, executing any tools it requests.

    Returns the agent's final text report. After MAX_TOOL_CALLS tool executions,
    the next LLM call omits tools to force a final answer.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    tools_used = 0
    while True:
        kwargs = {"model": _model(), "messages": messages}
        if tool_schemas and tools_used < MAX_TOOL_CALLS:
            kwargs["tools"] = tool_schemas
        msg = _completion_with_retry(**kwargs).choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            return msg.content or ""
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name,
                              "arguments": tc.function.arguments}}
                for tc in tool_calls
            ],
        })
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            fn = (tool_functions or {}).get(name)
            result = fn(**args) if fn else f"ERROR: unknown tool {name}"
            if on_event:
                detail = args.get("query") or args.get("url") or ""
                on_event({"type": "tool_call", "tool": name, "detail": detail})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            tools_used += 1
