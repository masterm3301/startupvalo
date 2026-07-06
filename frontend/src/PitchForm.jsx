import { useRef, useState } from "react";

export default function PitchForm({ onSubmit }) {
  const [name, setName] = useState("");
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  const pick = (f) => {
    if (f) setFile(f);
  };

  const submit = (e) => {
    e.preventDefault();
    if (name.trim() && file) onSubmit(name.trim(), file);
  };

  return (
    <form className="pitch-form" onSubmit={submit}>
      <h1>Get a grounded startup valuation</h1>
      <p className="sub">
        Upload your pitch deck — six AI analysts research real market data and
        produce a cited investment memo.
      </p>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Startup name"
        required
      />
      <div
        className={`drop-zone ${dragging ? "dragging" : ""}`}
        onClick={() => inputRef.current.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          pick(e.dataTransfer.files[0]);
        }}
      >
        {file ? (
          <span>
            📎 {file.name} ({(file.size / 1024 / 1024).toFixed(1)} MB)
          </span>
        ) : (
          <span>Drop your pitch deck here or click to browse (.pptx or .pdf)</span>
        )}
        <input
          ref={inputRef}
          type="file"
          accept=".pptx,.pdf"
          hidden
          onChange={(e) => pick(e.target.files[0])}
        />
      </div>
      <button type="submit" disabled={!name.trim() || !file}>
        Run valuation
      </button>
    </form>
  );
}
