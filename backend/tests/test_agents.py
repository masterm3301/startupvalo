from src.engine.agents import AGENTS


def test_six_agents_in_pipeline_order():
    assert [a["id"] for a in AGENTS] == [
        "talent", "market", "moat", "finance", "sentiment", "memo",
    ]


def test_agent_shape_and_placeholders():
    for a in AGENTS:
        for key in ("id", "name", "icon", "color", "uses_tools",
                    "system_prompt", "task_template"):
            assert key in a, f"{a.get('id')} missing {key}"
        # must format cleanly with exactly these two placeholders
        a["task_template"].format(name="X", pitch="Y")


def test_only_the_committee_lacks_tools():
    assert [a["uses_tools"] for a in AGENTS] == [True] * 5 + [False]


def test_research_agents_demand_citations():
    for a in AGENTS[:5]:
        assert "cite" in a["system_prompt"].lower()
