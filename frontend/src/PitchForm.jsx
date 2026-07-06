import { useState } from "react";

export default function PitchForm({ onSubmit }) {
  const [name, setName] = useState("");
  const [pitch, setPitch] = useState("");

  const submit = (e) => {
    e.preventDefault();
    if (name.trim() && pitch.trim()) onSubmit(name.trim(), pitch.trim());
  };

  return (
    <form className="pitch-form" onSubmit={submit}>
      <h1>Get a grounded startup valuation</h1>
      <p className="sub">Six AI analysts research real market data and produce a cited investment memo.</p>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Startup name"
        required
      />
      <textarea
        value={pitch}
        onChange={(e) => setPitch(e.target.value)}
        rows={6}
        placeholder="Pitch: what it does, stage, traction, team…"
        required
      />
      <button type="submit">Run valuation</button>
    </form>
  );
}
