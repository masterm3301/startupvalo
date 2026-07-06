from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class TraceRecorder:
    """Accumulates one run's events and writes logs/agent-trace-<timestamp>.md."""

    def __init__(self, name: str, pitch: str, logs_dir: Path | None = None):
        self.logs_dir = Path(logs_dir) if logs_dir else PROJECT_ROOT / "logs"
        self.started = datetime.now()
        self.lines = [
            f"# Agent Trace — {name}",
            f"\n**Run started:** {self.started:%Y-%m-%d %H:%M:%S}",
            f"\n**Pitch:** {pitch}\n",
        ]

    def record(self, event: dict) -> None:
        etype = event["type"]
        if etype == "agent_active":
            self.lines.append(f"\n## Agent: {event['id']}\n")
        elif etype == "tool_call":
            self.lines.append(f"- 🔧 `{event['tool']}` → {event['detail']}")
        elif etype == "agent_done":
            self.lines.append(f"\n### Report\n\n{event['output']}\n")
        elif etype == "agent_error":
            self.lines.append(f"\n### ERROR\n\n{event['message']}\n")

    def finish(self) -> Path:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        path = self.logs_dir / f"agent-trace-{self.started:%Y%m%d-%H%M%S}.md"
        path.write_text("\n".join(self.lines))
        return path
