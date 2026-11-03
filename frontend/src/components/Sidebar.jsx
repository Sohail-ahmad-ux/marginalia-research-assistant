import { FlaskConical, GitCompare, Library, MessageSquare, Plus, Trash2 } from "lucide-react";

const NAV = [
  ["chat", "Ask", MessageSquare],
  ["library", "Library", Library],
  ["compare", "Compare", GitCompare],
  ["eval", "Evaluate", FlaskConical],
];

export default function Sidebar({ tab, setTab, convs, convId, onPick, onNew, onDelete, health, paperCount }) {
  return (
    <aside className="side">
      <div className="brand">Marginalia</div>
      <nav>
        {NAV.map(([id, label, Icon]) => (
          <button key={id} className={"nav" + (tab === id ? " on" : "")} onClick={() => setTab(id)}>
            <Icon size={17} /> {label}
          </button>
        ))}
      </nav>
      <div className="convs">
        <div className="convs-head">
          <span>Conversations</span>
          <button className="icon" title="New conversation" onClick={onNew}><Plus size={16} /></button>
        </div>
        <div className="convs-list">
          {convs.length === 0 && <p className="muted small">Your questions will appear here.</p>}
          {convs.map((c) => (
            <div key={c.id} className={"conv" + (c.id === convId && tab === "chat" ? " on" : "")}>
              <button className="conv-title" onClick={() => onPick(c.id)}>{c.title}</button>
              <button className="icon del" title="Delete" onClick={() => onDelete(c.id)}><Trash2 size={14} /></button>
            </div>
          ))}
        </div>
      </div>
      <div className="side-foot muted small">
        {paperCount} {paperCount === 1 ? "paper" : "papers"} indexed
        {health?.ok && <div>{health.llm}{health.reranker === "cross-encoder" ? " + reranker" : ""}</div>}
      </div>
    </aside>
  );
}
