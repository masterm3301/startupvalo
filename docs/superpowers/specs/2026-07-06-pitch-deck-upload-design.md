# Pitch-Deck Upload — Design

**Date:** 2026-07-06
**Status:** Approved
**Builds on:** `2026-07-06-startupvalo-v2-design.md` (v2 is merged and live)

## Problem

The pitch input is a free-text box. Real pitches live in deck files; the user wants to upload a PowerPoint (or PDF) instead of typing. Decision: the file **replaces** the text box entirely — file-only input.

## Decisions (settled with user)

| Decision | Choice |
|---|---|
| Input mode | Deck file replaces the pitch textarea entirely |
| Formats | `.pptx` and `.pdf` only; legacy `.ppt` rejected with "save as .pptx" message |
| Flow | Direct upload → extraction → run in one step (no preview); near-empty extractions rejected before the run starts |

## Backend

### New module: `backend/src/engine/deck.py`

- `DeckError(ValueError)` — user-readable message, surfaced verbatim to the UI.
- `extract_deck_text(filename: str, data: bytes) -> str`
  - Dispatch on lowercased extension:
    - `.pptx` → `python-pptx`: for each slide, collect text from all shapes with text frames plus speaker-notes text; emit as `Slide N: <text>` blocks.
    - `.pdf` → `pypdf`: concatenate `page.extract_text()` per page as `Page N: <text>` blocks.
    - `.ppt` → `DeckError("Legacy .ppt is not supported — open it in PowerPoint and save as .pptx.")`
    - anything else → `DeckError("Unsupported file type <ext> — upload a .pptx or .pdf deck.")`
  - Corrupt/unparseable file → `DeckError("Could not read <filename> — the file appears corrupt or is not a valid <ext> file.")` (wrap parser exceptions).
  - Extracted text stripped; if `< 200` chars → `DeckError("The deck contains almost no readable text (image-only slides?). Export a text-based deck or PDF.")`
  - Truncate result to `15_000` chars (constant `MAX_DECK_CHARS`).

### `backend/src/api/server.py`

- `POST /api/valuation` changes from JSON body to multipart form: `name: str = Form(...)`, `deck: UploadFile = File(...)`.
- File size guard: reject bodies over `15 MB` (constant `MAX_DECK_BYTES`) with 422 before parsing.
- Call `extract_deck_text(deck.filename, await deck.read())`; on `DeckError` → `HTTPException(422, detail=str(err))`; on success → same `StreamingResponse(_sse(pipeline.run_valuation(name, pitch)))` as today.
- **Breaking change:** the JSON `{name, pitch}` body is removed. The trace file continues to record the pitch (now the extracted deck text), keeping every run auditable.
- New deps in `backend/requirements.txt`: `python-pptx>=1.0`, `pypdf>=5.0`.

## Frontend

- `PitchForm.jsx`: replace the textarea with a file drop zone — `<input type="file" accept=".pptx,.pdf">` styled as a drag-and-drop target (drag-over highlight, click to browse), showing the selected filename and size. Submit disabled until name and file are both present. `onSubmit(name, file)`.
- `api.js` `streamValuation(name, file, onEvent)`: build `FormData` (`name`, `deck`), POST without a manual `Content-Type` header (browser sets the multipart boundary). On non-OK, read the JSON body and throw `Error(detail)` so the App banner shows the server's message (e.g. image-only deck) and the user stays on the form with no run started.
- `App.jsx`: `start(name, file)` — event handling otherwise unchanged.

## Error handling summary

| Failure | Where caught | User sees |
|---|---|---|
| .ppt / unknown extension | deck.py → 422 | "save as .pptx" / "upload .pptx or .pdf" banner |
| Corrupt file | deck.py → 422 | "file appears corrupt" banner |
| Image-only deck (<200 chars text) | deck.py → 422 | "no readable text" banner, no credits spent |
| Oversized file (>15 MB) | server.py → 422 | size-limit banner |

## Testing

- `backend/tests/test_deck.py`: author a real minimal `.pptx` (python-pptx) and `.pdf` (pypdf writer) inside the tests; assert slide text + speaker notes extracted with `Slide N:` prefixes, PDF page text extracted, `.ppt`/`.docx` rejected with the right messages, near-empty deck rejected, long deck truncated to `MAX_DECK_CHARS`.
- `backend/tests/test_server.py`: multipart POST happy path (mock `server.extract_deck_text` and `server.pipeline.run_valuation`) streams SSE; `DeckError` → 422 with detail; missing file/name → 422.
- Frontend: existing `parseSSE` tests unchanged; `streamValuation`'s FormData change is exercised by the live e2e rather than a mocked-fetch unit test.
- Live e2e: generate a sample .pptx pitch deck, `curl -F` it against the running server, confirm the standard event stream and a memo.

## Out of scope

- Legacy `.ppt` conversion, OCR for image-only decks, extraction preview/editing, multiple files, keeping the JSON text API.
