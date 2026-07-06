export function parseSSE(buffer) {
  const events = [];
  let idx;
  while ((idx = buffer.indexOf("\n\n")) !== -1) {
    const chunk = buffer.slice(0, idx);
    buffer = buffer.slice(idx + 2);
    if (chunk.startsWith("data: ")) events.push(JSON.parse(chunk.slice(6)));
  }
  return [events, buffer];
}

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

export async function fetchHealth() {
  const resp = await fetch("/api/health");
  return resp.json();
}
