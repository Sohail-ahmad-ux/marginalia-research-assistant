import { useEffect, useRef, useState } from "react";
import { Files, Loader2, Send, SlidersHorizontal } from "lucide-react";
import { api } from "../api";
import Markdown from "./Markdown";
import SourcesPanel from "./SourcesPanel";

const SECTIONS = ["abstract", "introduction", "related_work", "methods", "experiments", "results", "discussion", "limitations", "conclusion"];
const EXAMPLES = [
  "Summarise the methodology of each paper.",
  "Which datasets and metrics are used, and what are the main results?",
  "What limitations do the authors acknowledge?",
];

export default function ChatView({ papers, convId, setConvId, refreshConvs, goLibrary }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [scope, setScope] = useState([]); // empty = all papers
  const [opts, setOpts] = useState({ top_k: 6, rewrite: true, multi_query: true, rerank: true, section: "" });
  const [pop, setPop] = useState(null);
  const [focus, setFocus] = useState(null);
  const [cite, setCite] = useState(null);
  const justCreated = useRef(null);
  const endRef = useRef(null);

  useEffect(() => {
    if (!convId) { setMessages([]); setFocus(null); return; }
    if (justCreated.current === convId) { justCreated.current = null; return; }
    api.messages(convId).then((m) => { setMessages(m); setFocus(null); setCite(null); }).catch(() => {});
  }, [convId]);

  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [messages]);

  const updateLast = (fn) => setMessages((ms) => ms.map((m, i) => (i === ms.length - 1 ? fn(m) : m)));

  async function send(text) {
    const q = (text ?? input).trim();
    if (!q || busy) return;
    setInput(""); setBusy(true); setFocus(null); setCite(null); setPop(null);
    setMessages((m) => [...m, { role: "user", content: q }, { role: "assistant", content: "", sources: [], trace: null, streaming: true }]);
    try {
      await api.chatStream(
        { question: q, conversation_id: convId, paper_ids: scope, sections: opts.section ? [opts.section] : [],
          top_k: opts.top_k, rewrite: opts.rewrite, multi_query: opts.multi_query, rerank: opts.rerank },
        (ev) => {
          if (ev.type === "start" && !convId) { justCreated.current = ev.conversation_id; setConvId(ev.conversation_id); }
          else if (ev.type === "retrieval") updateLast((m) => ({ ...m, sources: ev.sources, trace: ev.trace }));
          else if (ev.type === "token") updateLast((m) => ({ ...m, content: m.content + ev.text }));
          else if (ev.type === "error") updateLast((m) => ({ ...m, error: ev.message }));
        });
    } catch (e) {
      updateLast((m) => ({ ...m, error: e.message }));
    } finally {
      updateLast((m) => ({ ...m, streaming: false }));
      setBusy(false);
      refreshConvs();
    }
  }

  const lastAssistant = messages.map((m) => m.role).lastIndexOf("assistant");
  const shown = messages[focus ?? lastAssistant];
  const toggleScope = (id) => setScope((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  return (
    <div className="chat">
      <section className="thread">
        <div className="scroll">
          {messages.length === 0 && (
            <div className="empty">
              <h1>Ask your papers</h1>
              {papers.length === 0 ? (
                <p>Add a few PDFs to your library, then ask questions across all of them. Every answer links back to the exact passage.</p>
              ) : (
                <p>Answers are written only from passages in your {papers.length} indexed {papers.length === 1 ? "paper" : "papers"}, with citations you can click.</p>
              )}
              {papers.length === 0 ? (
                <button className="btn primary" onClick={goLibrary}>Add papers</button>
              ) : (
                <ul className="examples">
                  {EXAMPLES.map((e) => <li key={e}><button onClick={() => send(e)}>{e}</button></li>)}
                </ul>
              )}
            </div>
          )}
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="msg user">{m.content}</div>
            ) : (
              <div key={i} className={"msg bot" + ((focus ?? lastAssistant) === i ? " focus" : "")}
                onClick={() => { setFocus(i); setCite(null); }}>
                {m.content ? <Markdown text={m.content} onCite={(n) => { setFocus(i); setCite(n); }} /> :
                  m.streaming && !m.error && <p className="muted"><Loader2 size={15} className="spin" /> Searching your papers…</p>}
                {m.error && <p className="warn">Error: {m.error}</p>}
              </div>
            ))}
          <div ref={endRef} />
        </div>

        <div className="composer">
          {pop && (
            <div className="pop">
              {pop === "scope" ? (
                <>
                  <h4>Search in</h4>
                  <label className="check"><input type="checkbox" checked={scope.length === 0} onChange={() => setScope([])} /> All papers</label>
                  {papers.map((p) => (
                    <label key={p.id} className="check"><input type="checkbox" checked={scope.includes(p.id)} onChange={() => toggleScope(p.id)} /> {p.title}</label>
                  ))}
                </>
              ) : (
                <>
                  <h4>Retrieval settings</h4>
                  <label className="check"><input type="checkbox" checked={opts.rewrite} onChange={(e) => setOpts({ ...opts, rewrite: e.target.checked })} /> Rewrite follow-up questions</label>
                  <label className="check"><input type="checkbox" checked={opts.multi_query} onChange={(e) => setOpts({ ...opts, multi_query: e.target.checked })} /> Search with extra phrasings</label>
                  <label className="check"><input type="checkbox" checked={opts.rerank} onChange={(e) => setOpts({ ...opts, rerank: e.target.checked })} /> Rerank results</label>
                  <label className="field">Passages used: {opts.top_k}
                    <input type="range" min="3" max="12" value={opts.top_k} onChange={(e) => setOpts({ ...opts, top_k: +e.target.value })} />
                  </label>
                  <label className="field">Only search in section
                    <select value={opts.section} onChange={(e) => setOpts({ ...opts, section: e.target.value })}>
                      <option value="">Any section</option>
                      {SECTIONS.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
                    </select>
                  </label>
                </>
              )}
            </div>
          )}
          <div className="bar">
            <textarea rows={1} value={input} placeholder="Ask about methods, results, limitations, or compare papers…"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
            <button className={"icon-btn" + (pop === "scope" ? " on" : "")} title="Choose papers" onClick={() => setPop(pop === "scope" ? null : "scope")}>
              <Files size={18} />{scope.length > 0 && <span className="dot">{scope.length}</span>}
            </button>
            <button className={"icon-btn" + (pop === "settings" ? " on" : "")} title="Retrieval settings" onClick={() => setPop(pop === "settings" ? null : "settings")}>
              <SlidersHorizontal size={18} />
            </button>
            <button className="btn primary send" disabled={busy || !input.trim()} onClick={() => send()}>
              {busy ? <Loader2 size={17} className="spin" /> : <Send size={17} />} Ask
            </button>
          </div>
        </div>
      </section>
      <SourcesPanel sources={shown?.sources} trace={shown?.trace} activeCite={cite} />
    </div>
  );
}
