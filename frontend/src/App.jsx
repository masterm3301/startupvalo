import { useEffect, useState } from "react";
import AgentBoard from "./AgentBoard";
import MemoView from "./MemoView";
import PitchForm from "./PitchForm";
import { fetchHealth, streamValuation } from "./api";

export default function App() {
  const [phase, setPhase] = useState("form"); // form | running | done
  const [agents, setAgents] = useState([]);
  const [memo, setMemo] = useState("");
  const [banner, setBanner] = useState("");

  useEffect(() => {
    fetchHealth()
      .then((h) => {
        if (!h.ok)
          setBanner(
            "Missing API keys — set GROQ_API_KEY and SERPER_API_KEY in .env, then restart the backend."
          );
      })
      .catch(() => setBanner("Backend not reachable on /api — is uvicorn running on :8000?"));
  }, []);

  const patchAgent = (id, patch) =>
    setAgents((prev) => prev.map((a) => (a.id === id ? { ...a, ...patch } : a)));

  const onEvent = (e) => {
    switch (e.type) {
      case "agent_init":
        setAgents((prev) => [...prev, { ...e, status: "pending", activity: "", output: "" }]);
        break;
      case "agent_active":
        patchAgent(e.id, { status: "active" });
        break;
      case "tool_call":
        patchAgent(e.id, {
          activity: `${e.tool === "web_search" ? "🔍 searching" : "📄 reading"}: ${e.detail}`,
        });
        break;
      case "agent_done":
        patchAgent(e.id, { status: "done", activity: "", output: e.output });
        break;
      case "agent_error":
        patchAgent(e.id, { status: "error", activity: "", output: e.message });
        setPhase("done");
        break;
      case "complete":
        setMemo(e.memo);
        setPhase("done");
        break;
      default:
        break;
    }
  };

  const start = async (name, pitch) => {
    setAgents([]);
    setMemo("");
    setPhase("running");
    try {
      await streamValuation(name, pitch, onEvent);
    } catch (err) {
      setBanner(String(err));
      setPhase("form");
    }
  };

  return (
    <div className="app">
      <header>
        <span className="logo">💎 StartupValo</span>
        {phase === "done" && (
          <button className="ghost" onClick={() => setPhase("form")}>New valuation</button>
        )}
      </header>
      {banner && <div className="banner">{banner}</div>}
      {phase === "form" && <PitchForm onSubmit={start} />}
      {phase !== "form" && <AgentBoard agents={agents} />}
      {phase === "done" && memo && <MemoView memo={memo} />}
    </div>
  );
}
