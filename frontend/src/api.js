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

export async function streamValuation(name, pitch, onEvent) {
  const resp = await fetch("/api/valuation", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, pitch }),
  });
  if (!resp.ok) throw new Error(`Server error: HTTP ${resp.status}`);
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
