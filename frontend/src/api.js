const BASE = "/api";

async function errText(r) {
  try {
    const d = await r.json();
    return typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail || d);
  } catch {
    return r.statusText || `HTTP ${r.status}`;
  }
}

async function j(path, opts) {
  const r = await fetch(BASE + path, opts);
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

const post = (path, body) =>
  j(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  health: () => j("/health"),
  papers: () => j("/papers"),
  upload: (file) => {
    const fd = new FormData();
    fd.append("files", file);
    return j("/papers", { method: "POST", body: fd });
  },
  deletePaper: (id) => j(`/papers/${id}`, { method: "DELETE" }),
  sections: (id) => j(`/papers/${id}/sections`),
  analyze: (id, force = false) => j(`/papers/${id}/analyze?force=${force}`, { method: "POST" }),
  pdfUrl: (id, page = 1) => `${BASE}/papers/${id}/pdf#page=${page}`,
  compare: (body) => post("/compare", body),
  conversations: () => j("/conversations"),
  deleteConversation: (id) => j(`/conversations/${id}`, { method: "DELETE" }),
  messages: (id) => j(`/conversations/${id}/messages`),
  evalSets: () => j("/eval/sets"),
  evalGenerate: (body) => post("/eval/sets", body),
  evalRun: (body) => post("/eval/run", body),
  evalRuns: () => j("/eval/runs"),

  // Server-Sent Events over fetch so we can POST a body
  async chatStream(body, onEvent) {
    const r = await fetch(BASE + "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(await errText(r));
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i);
        buf = buf.slice(i + 2);
        const line = chunk.split("\n").find((l) => l.startsWith("data: "));
        if (line) onEvent(JSON.parse(line.slice(6)));
      }
    }
  },
};
