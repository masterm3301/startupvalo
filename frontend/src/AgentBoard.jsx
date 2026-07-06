import AgentCard from "./AgentCard";

export default function AgentBoard({ agents }) {
  return (
    <section className="board">
      {agents.map((a) => (
        <AgentCard key={a.id} agent={a} />
      ))}
    </section>
  );
}
