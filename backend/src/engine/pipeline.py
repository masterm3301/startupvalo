import queue
import threading

from src.engine import llm
from src.engine.agents import AGENTS
from src.engine.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS
from src.reporting.trace import TraceRecorder


def _worker(name: str, pitch: str, q: queue.Queue) -> None:
    # The outer try guarantees a terminal event on the queue no matter what
    # raises — otherwise run_valuation's q.get() would block forever.
    # Synthetic id matching no UI card; only surfaces if something raises
    # before the first agent id is assigned below.
    agent_id = "pipeline"
    try:
        reports = []
        output = ""
        for agent in AGENTS:
            agent_id = agent["id"]
            q.put({"type": "agent_active", "id": agent_id})
            task = agent["task_template"].format(name=name, pitch=pitch)
            if reports:
                prior = "\n\n---\n\n".join(reports)
                task += f"\n\nReports from earlier analysts:\n\n{prior}"

            def on_event(event, agent_id=agent_id):
                q.put({**event, "id": agent_id})

            try:
                output = llm.run_agent(
                    agent["system_prompt"], task,
                    tool_schemas=TOOL_SCHEMAS if agent["uses_tools"] else None,
                    tool_functions=TOOL_FUNCTIONS if agent["uses_tools"] else None,
                    on_event=on_event,
                )
            except Exception as exc:
                q.put({"type": "agent_error", "id": agent_id, "message": str(exc)})
                return
            reports.append(f"### {agent['name']}\n\n{output}")
            q.put({"type": "agent_done", "id": agent_id, "output": output})
        q.put({"type": "complete", "memo": output})
    except Exception as exc:
        q.put({"type": "agent_error", "id": agent_id, "message": str(exc)})


def run_valuation(name: str, pitch: str, logs_dir=None):
    """Yield SSE-ready event dicts for one full valuation run."""
    for agent in AGENTS:
        yield {"type": "agent_init", "id": agent["id"], "name": agent["name"],
               "icon": agent["icon"], "color": agent["color"]}
    trace = TraceRecorder(name, pitch, logs_dir=logs_dir)
    q: queue.Queue = queue.Queue()
    thread = threading.Thread(target=_worker, args=(name, pitch, q), daemon=True)
    thread.start()
    while True:
        event = q.get()
        trace.record(event)
        yield event
        if event["type"] in ("complete", "agent_error"):
            break
    trace.finish()
