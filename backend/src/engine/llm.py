import json
import os
import re
import time

import litellm

MAX_TOOL_CALLS = 8
MAX_RETRIES = 5
MAX_MALFORMED_RETRIES = 3

# Groq/llama occasionally emits a pseudo tool-call as plain text (e.g.
# "<function=web_search {...}>" or "<function(web_search){...}</function>")
# instead of a real tool_calls entry. The API doesn't always reject this
# itself (see MAX_RETRIES tool_use_failed handling below for when it does),
# so we also have to detect it client-side when it slips through as content.
_FAKE_TOOL_CALL_RE = re.compile(r"<function\b", re.IGNORECASE)


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
            retryable = (
                status == 429
                or (status is not None and status >= 500)
                or "tool_use_failed" in str(exc)
            )
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
    malformed_retries = 0
    while True:
        kwargs = {"model": _model(), "messages": messages}
        if tool_schemas and tools_used < MAX_TOOL_CALLS:
            kwargs["tools"] = tool_schemas
        msg = _completion_with_retry(**kwargs).choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            content = msg.content or ""
            looks_fake = bool(_FAKE_TOOL_CALL_RE.search(content))
            if looks_fake and malformed_retries < MAX_MALFORMED_RETRIES:
                malformed_retries += 1
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": "That was not a valid tool call — do not write function "
                               "syntax as text. Either use the actual tool-calling "
                               "mechanism, or write your final report in plain prose "
                               "with no function/tool syntax at all.",
                })
                continue
            return content
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
            if tools_used >= MAX_TOOL_CALLS:
                result = "ERROR: tool call limit reached; write your final report now."
            else:
                fn = (tool_functions or {}).get(name)
                if fn is None:
                    result = f"ERROR: unknown tool {name}"
                else:
                    try:
                        result = fn(**args)
                    except Exception as exc:
                        result = f"ERROR: tool execution failed: {exc}"
                if on_event:
                    detail = args.get("query") or args.get("url") or ""
                    on_event({"type": "tool_call", "tool": name, "detail": detail})
                tools_used += 1
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
