# Pitch-Deck Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the pitch textarea with a deck upload (.pptx/.pdf): the server extracts the deck's text and feeds it to the existing valuation pipeline as the pitch.

**Architecture:** A new pure extractor module (`deck.py`) turns uploaded bytes into pitch text with user-readable failures (`DeckError`); `/api/valuation` becomes a multipart endpoint that extracts-then-streams; the React form swaps its textarea for a drag-and-drop file zone. Pipeline, agents, and trace are untouched.

**Tech Stack:** python-pptx, pypdf (extraction); fpdf2 (test-only PDF authoring); python-multipart (FastAPI form parsing); existing FastAPI/React stack.

**Spec:** `docs/superpowers/specs/2026-07-06-pitch-deck-upload-design.md`

## Global Constraints

- Backend commands run **from `backend/`** with `../.venv/bin/<tool>`; frontend commands from `frontend/` with npm.
- `MAX_DECK_CHARS = 15_000` (truncation), `MIN_TEXT_CHARS = 200` (image-only rejection), `MAX_DECK_BYTES = 15 * 1024 * 1024`.
- All `DeckError` messages are user-facing — copy them verbatim from this plan.
- **Breaking change is intended:** the JSON `{name, pitch}` body is removed; old server tests for it are replaced, not kept.
- Commit messages end with the trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- NEVER `git add -A` — the working tree may hold uncommitted user edits (`text.txt` must never be committed). Stage files explicitly.

---

### Task 1: Deck text extractor (`deck.py`)

**Files:**
- Modify: `backend/requirements.txt` (append deps)
- Create: `backend/src/engine/deck.py`
- Test: `backend/tests/test_deck.py`

**Interfaces:**
- Produces: `extract_deck_text(filename: str, data: bytes) -> str` and `DeckError(ValueError)` in `src.engine.deck`; constants `MAX_DECK_CHARS = 15_000`, `MIN_TEXT_CHARS = 200`. Task 2 imports `DeckError` and `extract_deck_text`.

- [ ] **Step 1: Add dependencies**

Append to `backend/requirements.txt`:

```
python-pptx>=1.0.0
pypdf>=5.0.0
fpdf2>=2.7.0
python-multipart>=0.0.9
```

Run: `../.venv/bin/pip install -r requirements.txt` (from `backend/`) — expect clean install.

- [ ] **Step 2: Write the failing tests** — `backend/tests/test_deck.py`:

```python
import io

import pytest

from src.engine.deck import MAX_DECK_CHARS, DeckError, extract_deck_text

LONG_NOTE = "This startup sells AI-powered dog walking subscriptions to urban pet owners. " * 5


def _make_pptx(slide_texts, notes=None):
    from pptx import Presentation

    prs = Presentation()
    layout = prs.slide_layouts[5]  # "Title Only"
    for i, text in enumerate(slide_texts):
        slide = prs.slides.add_slide(layout)
        slide.shapes.title.text = text
        if notes and i < len(notes) and notes[i]:
            slide.notes_slide.notes_text_frame.text = notes[i]
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _make_pdf(pages):
    from fpdf import FPDF

    pdf = FPDF()
    for text in pages:
        pdf.add_page()
        pdf.set_font("helvetica", size=12)
        pdf.multi_cell(0, 10, text)
    return bytes(pdf.output())


def test_pptx_extracts_slides_and_notes():
    data = _make_pptx(["Problem: dogs need walks", "Market: $1.85B"],
                      notes=[LONG_NOTE, None])
    text = extract_deck_text("pitch.pptx", data)
    assert "Slide 1:" in text and "Slide 2:" in text
    assert "dogs need walks" in text
    assert "urban pet owners" in text  # speaker notes included


def test_pdf_extracts_pages():
    data = _make_pdf([LONG_NOTE, "Traction: 3 cities live"])
    text = extract_deck_text("pitch.pdf", data)
    assert "Page 1:" in text and "Page 2:" in text
    assert "3 cities" in text


def test_legacy_ppt_rejected():
    with pytest.raises(DeckError, match="save as .pptx"):
        extract_deck_text("old-deck.ppt", b"whatever")


def test_unsupported_extension_rejected():
    with pytest.raises(DeckError, match="Unsupported file type"):
        extract_deck_text("pitch.docx", b"whatever")


def test_corrupt_file_rejected():
    with pytest.raises(DeckError, match="corrupt"):
        extract_deck_text("pitch.pptx", b"this is not a zip archive")


def test_near_empty_deck_rejected():
    data = _make_pptx(["Hi"])
    with pytest.raises(DeckError, match="readable text"):
        extract_deck_text("pitch.pptx", data)


def test_long_deck_truncated():
    data = _make_pdf([LONG_NOTE * 60])  # well over 15k chars
    text = extract_deck_text("pitch.pdf", data)
    assert len(text) <= MAX_DECK_CHARS
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `../.venv/bin/pytest tests/test_deck.py -v` · Expected: FAIL (module missing).

- [ ] **Step 4: Implement** — `backend/src/engine/deck.py`:

```python
"""Extract pitch text from uploaded deck files (.pptx / .pdf)."""
import io
from pathlib import Path

MAX_DECK_CHARS = 15_000
MIN_TEXT_CHARS = 200


class DeckError(ValueError):
    """User-readable deck extraction failure — messages go straight to the UI."""


def _pptx_text(data: bytes) -> str:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    blocks = []
    for n, slide in enumerate(prs.slides, 1):
        parts = []
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                parts.append(shape.text_frame.text.strip())
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                parts.append(f"(speaker notes) {notes}")
        if parts:
            blocks.append(f"Slide {n}: " + "\n".join(parts))
    return "\n\n".join(blocks)


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    blocks = []
    for n, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if text:
            blocks.append(f"Page {n}: {text}")
    return "\n\n".join(blocks)


_PARSERS = {".pptx": _pptx_text, ".pdf": _pdf_text}


def extract_deck_text(filename: str, data: bytes) -> str:
    """Return the deck's readable text, or raise DeckError with a user-facing message."""
    ext = Path(filename or "").suffix.lower()
    if ext == ".ppt":
        raise DeckError(
            "Legacy .ppt is not supported — open it in PowerPoint and save as .pptx."
        )
    parser = _PARSERS.get(ext)
    if parser is None:
        raise DeckError(
            f"Unsupported file type {ext or '(none)'} — upload a .pptx or .pdf deck."
        )
    try:
        text = parser(data).strip()
    except Exception:
        raise DeckError(
            f"Could not read {filename} — the file appears corrupt or is not a valid {ext} file."
        )
    if len(text) < MIN_TEXT_CHARS:
        raise DeckError(
            "The deck contains almost no readable text (image-only slides?). "
            "Export a text-based deck or PDF."
        )
    return text[:MAX_DECK_CHARS]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `../.venv/bin/pytest tests/test_deck.py -v` · Expected: 7 PASS. Then full suite: `../.venv/bin/pytest -q` — all pass, no regressions.

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/src/engine/deck.py backend/tests/test_deck.py
git commit -m "feat: deck text extractor for .pptx and .pdf pitch decks"
```

---

### Task 2: Multipart valuation endpoint

**Files:**
- Modify: `backend/src/api/server.py` (replace the `/api/valuation` endpoint and `ValuationRequest`)
- Modify: `backend/tests/test_server.py` (replace the two JSON-body valuation tests; keep health tests)

**Interfaces:**
- Consumes: `extract_deck_text(filename, data) -> str`, `DeckError` from `src.engine.deck` (Task 1); `pipeline.run_valuation(name, pitch)` (existing).
- Produces: `POST /api/valuation` accepting multipart form fields `name` (str) and `deck` (file) → SSE stream identical to before; 422 with `{"detail": <DeckError message>}` on extraction failure; 422 on missing fields; 422 on files over `MAX_DECK_BYTES`. Frontend (Task 3) relies on the 422 `detail` field.

- [ ] **Step 1: Replace the valuation tests in `backend/tests/test_server.py`**

Delete `test_valuation_streams_events` and `test_valuation_requires_name_and_pitch`. Add (keeping the existing imports and health tests; add `from src.engine.deck import DeckError` to imports):

```python
def _post_deck(client, name="Acme", filename="pitch.pptx", content=b"deck-bytes"):
    return client.post(
        "/api/valuation",
        data={"name": name},
        files={"deck": (filename, content, "application/octet-stream")},
    )


def test_valuation_accepts_deck_upload(monkeypatch):
    monkeypatch.setattr(server, "extract_deck_text",
                        lambda filename, data: "extracted pitch text")
    captured = {}

    def fake_run(name, pitch):
        captured["name"], captured["pitch"] = name, pitch
        return iter([{"type": "complete", "memo": "m"}])

    monkeypatch.setattr(server.pipeline, "run_valuation", fake_run)
    client = TestClient(server.app)
    resp = _post_deck(client)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert 'data: {"type": "complete", "memo": "m"}' in resp.text
    assert captured == {"name": "Acme", "pitch": "extracted pitch text"}


def test_valuation_rejects_bad_deck(monkeypatch):
    def boom(filename, data):
        raise DeckError("The deck contains almost no readable text")

    monkeypatch.setattr(server, "extract_deck_text", boom)
    client = TestClient(server.app)
    resp = _post_deck(client)
    assert resp.status_code == 422
    assert "no readable text" in resp.json()["detail"]


def test_valuation_requires_name_and_deck():
    client = TestClient(server.app)
    assert client.post("/api/valuation", data={"name": "Acme"}).status_code == 422
    assert client.post(
        "/api/valuation",
        files={"deck": ("p.pptx", b"x", "application/octet-stream")},
    ).status_code == 422


def test_valuation_rejects_oversized_deck(monkeypatch):
    monkeypatch.setattr(server, "MAX_DECK_BYTES", 10)
    client = TestClient(server.app)
    resp = _post_deck(client, content=b"x" * 11)
    assert resp.status_code == 422
    assert "larger than" in resp.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../.venv/bin/pytest tests/test_server.py -v` · Expected: the four new tests FAIL (endpoint still expects JSON); the two health tests still PASS.

- [ ] **Step 3: Implement in `backend/src/api/server.py`**

Update the fastapi import line, add the deck import and constant, delete the `ValuationRequest` class and the `pydantic` import, and replace the endpoint:

```python
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
```

```python
from src.engine.deck import DeckError, extract_deck_text
```

```python
MAX_DECK_BYTES = 15 * 1024 * 1024
```

```python
@app.post("/api/valuation")
async def valuation(name: str = Form(...), deck: UploadFile = File(...)):
    data = await deck.read()
    if len(data) > MAX_DECK_BYTES:
        raise HTTPException(
            status_code=422,
            detail=f"Deck file is larger than {MAX_DECK_BYTES // (1024 * 1024)} MB — upload a smaller file.",
        )
    try:
        pitch = extract_deck_text(deck.filename, data)
    except DeckError as err:
        raise HTTPException(status_code=422, detail=str(err))
    return StreamingResponse(
        _sse(pipeline.run_valuation(name, pitch)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `../.venv/bin/pytest tests/test_server.py -v` · Expected: 6 PASS (4 new + 2 health). Full suite: `../.venv/bin/pytest -q` — all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/server.py backend/tests/test_server.py
git commit -m "feat: multipart deck upload on /api/valuation (replaces JSON pitch)"
```

---

### Task 3: Frontend file-drop form

**Files:**
- Modify: `frontend/src/api.js` (streamValuation → FormData; surface 422 detail)
- Modify: `frontend/src/PitchForm.jsx` (textarea → drop zone)
- Modify: `frontend/src/App.jsx` (param rename only)
- Modify: `frontend/src/styles.css` (append drop-zone styles)

**Interfaces:**
- Consumes: `POST /api/valuation` multipart (`name`, `deck`), 422 `{"detail": msg}` (Task 2).
- Produces: `streamValuation(name, deckFile, onEvent)` — second arg is now a `File`; `PitchForm` calls `onSubmit(name, file)`. `parseSSE`/`fetchHealth` unchanged.

- [ ] **Step 1: Update `frontend/src/api.js`** — replace `streamValuation` only (`parseSSE` and `fetchHealth` stay):

```js
export async function streamValuation(name, deckFile, onEvent) {
  const form = new FormData();
  form.append("name", name);
  form.append("deck", deckFile);
  const resp = await fetch("/api/valuation", { method: "POST", body: form });
  if (!resp.ok) {
    let detail = `Server error: HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      if (body.detail) detail = body.detail;
    } catch {
      // non-JSON error body; keep the generic message
    }
    throw new Error(detail);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let events;
    [events, buffer] = parseSSE(buffer);
    events.forEach(onEvent);
  }
}
```

(No manual `Content-Type` header — the browser sets the multipart boundary.)

- [ ] **Step 2: Replace `frontend/src/PitchForm.jsx`**:

```jsx
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
```

- [ ] **Step 3: Update `frontend/src/App.jsx`** — rename the `start` param (behavior unchanged):

```jsx
  const start = async (name, deckFile) => {
    setAgents([]);
    setMemo("");
    setPhase("running");
    try {
      await streamValuation(name, deckFile, onEvent);
    } catch (err) {
      setBanner(String(err.message || err));
      setPhase("form");
    }
  };
```

- [ ] **Step 4: Append to `frontend/src/styles.css`**:

```css
.drop-zone {
  border: 2px dashed var(--border);
  border-radius: 10px;
  padding: 2rem 1rem;
  text-align: center;
  color: var(--text-2);
  cursor: pointer;
}
.drop-zone.dragging { border-color: var(--blue); color: var(--text-1); }
button:disabled { opacity: 0.5; cursor: not-allowed; }
```

- [ ] **Step 5: Verify tests and build**

Run (from `frontend/`): `npm test` → 3 PASS (parseSSE untouched), then `npm run build` → clean `dist/` rebuild.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api.js frontend/src/PitchForm.jsx frontend/src/App.jsx frontend/src/styles.css
git commit -m "feat: deck-upload drop zone replaces pitch textarea"
```

---

### Task 4: Live e2e with a generated deck + README

**Files:**
- Create: `backend/tests/make_sample_deck.py` (tiny generator, reused for manual testing)
- Modify: `README.md` (input description)

**Interfaces:**
- Consumes: the full stack (Tasks 1-3) with real keys from `.env`.

- [ ] **Step 1: Write the sample-deck generator** — `backend/tests/make_sample_deck.py`:

```python
"""Generate a small sample pitch deck for e2e testing.

Run from backend/:  ../.venv/bin/python tests/make_sample_deck.py
Writes: /tmp path printed on stdout.
"""
import tempfile
from pathlib import Path

from pptx import Presentation

SLIDES = [
    ("Rover — dog walking, on demand",
     "Marketplace app connecting dog owners with vetted dog walkers."),
    ("Problem",
     "Urban dog owners work long hours; 40% report skipping walks weekly. "
     "Existing options are informal, uninsured, and unreliable."),
    ("Solution & traction",
     "Vetted walkers, GPS-tracked walks, in-app payments. Live in 3 cities, "
     "1,200 weekly active walkers, $38k MRR growing 15% month over month."),
    ("Business model",
     "20% take rate on each walk. Average walk $25. Subscriptions for "
     "5-walk weekly bundles drive 60% of revenue."),
    ("Team",
     "Two founders: ex-Uber ops lead and a full-stack engineer who built "
     "pet-sitting marketplace Snoutly (acquired 2023)."),
]


def main() -> None:
    prs = Presentation()
    layout = prs.slide_layouts[1]  # Title and Content
    for title, body in SLIDES:
        slide = prs.slides.add_slide(layout)
        slide.shapes.title.text = title
        slide.placeholders[1].text = body
    out = Path(tempfile.gettempdir()) / "rover-sample-deck.pptx"
    prs.save(out)
    print(out)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the live e2e**

From `backend/` (ensure no server already holds port 8000 — kill it if so):

```bash
DECK=$(../.venv/bin/python tests/make_sample_deck.py)
../.venv/bin/uvicorn src.api.server:app --port 8000 &   # background
sleep 3
# error path first (cheap): a fake tiny file must 422 without burning a run
printf 'not a deck' > /tmp/fake.pptx
curl -s -X POST http://localhost:8000/api/valuation -F name=Rover -F deck=@/tmp/fake.pptx
# expect: {"detail":"Could not read fake.pptx — ..."}
# happy path: full live valuation (3-6 minutes)
curl -sN --max-time 600 -X POST http://localhost:8000/api/valuation \
     -F name=Rover -F "deck=@${DECK}" | tee /tmp/e2e-deck-run.txt | tail -5
kill %1
```

Expected: 422 JSON for the fake file; for the real deck, the standard event stream ending in a `complete` event whose memo cites sources; a new `logs/agent-trace-*.md` whose **Pitch:** line contains slide text (e.g. "GPS-tracked walks"). If a transient rate limit kills an agent, retry once.

- [ ] **Step 3: Update `README.md`** — in the intro paragraph, replace the sentence describing input with:

```markdown
Upload a pitch deck (.pptx or .pdf) — six AI analysts extract the pitch,
research real market data (web search + scraping), and produce a cited
Investment Memo with a bear/base/bull pre-money valuation.
```

- [ ] **Step 4: Full suites once more**

`cd backend && ../.venv/bin/pytest -q` (all pass) and `cd frontend && npm test` (3 pass).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/make_sample_deck.py README.md
git commit -m "feat: sample deck generator, live deck-upload e2e verified; README update"
```

---

## Self-review notes

- **Spec coverage:** extractor + all four DeckError cases + truncation ✓ (T1); multipart endpoint, size guard, 422 detail, JSON removal ✓ (T2); drop zone, FormData, 422 banner surfacing ✓ (T3); live e2e incl. error path, README ✓ (T4). Trace auditability needs no change (pipeline records pitch already).
- **Type consistency:** `extract_deck_text(filename, data)` identical in T1 def, T2 import/monkeypatch, T4 exercise; `streamValuation(name, deckFile, onEvent)` matches PitchForm's `onSubmit(name, file)` and App's `start(name, deckFile)`.
- **Placeholder scan:** clean.
