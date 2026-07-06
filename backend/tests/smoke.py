"""Live smoke test: runs the Market Validator agent once with real keys.

Costs a few Groq calls and ~1-4 Serper credits.
Run from backend/:  ../.venv/bin/python tests/smoke.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from src.engine import llm
from src.engine.agents import AGENTS
from src.engine.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS

agent = AGENTS[1]  # Market Validator
task = agent["task_template"].format(
    name="Rover",
    pitch="Marketplace app connecting dog owners with vetted dog walkers; live in 3 cities.",
)
report = llm.run_agent(
    agent["system_prompt"], task,
    tool_schemas=TOOL_SCHEMAS, tool_functions=TOOL_FUNCTIONS, on_event=print,
)
print("\n=== REPORT ===\n", report)
assert "http" in report.lower(), "expected at least one cited source URL in the report"
print("\nSMOKE OK")
