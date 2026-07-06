export default function AgentCard({ agent }) {
  const { name, icon, color, status, activity, output } = agent;
  return (
    <div className={`card ${status}`} style={{ "--accent": color }}>
      <div className="card-head">
        <span className="card-icon">{icon}</span>
        <span className="card-name">{name}</span>
        <span className={`pill ${status}`}>{status}</span>
      </div>
      {activity && <div className="activity">{activity}</div>}
      {output && (
        <details>
          <summary>{status === "error" ? "Error details" : "Report"}</summary>
          <pre>{output}</pre>
        </details>
      )}
    </div>
  );
}
