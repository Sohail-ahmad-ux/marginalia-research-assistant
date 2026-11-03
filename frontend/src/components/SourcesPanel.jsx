import { useEffect, useRef, useState } from "react";
import { ExternalLink } from "lucide-react";
import { api } from "../api";

function Trace({ trace }) {
  if (!trace) return null;
  const ms = (k) => (trace[k] != null ? `${trace[k]} ms` : null);
  return (
    <div className="trace">
      <h4>How this was retrieved</h4>
      <dl>
        {trace.intent && (<><dt>Intent</dt><dd>{trace.intent}</dd></>)}
        {trace.standalone && (<><dt>Search question</dt><dd>{trace.standalone}</dd></>)}
        {trace.queries?.length > 1 && (
          <><dt>Extra queries</dt><dd>{trace.queries.slice(1).join(" · ")}</dd></>
        )}
        <dt>Candidates</dt>
        <dd>{trace.candidates ?? 0} from dense + keyword search, {trace.reranked ? "reranked" : "not reranked"}</dd>
        <dt>Timing</dt>
        <dd>{[ms("plan_ms") && `plan ${ms("plan_ms")}`, ms("retrieve_ms") && `search ${ms("retrieve_ms")}`, ms("rerank_ms") && `rerank ${ms("rerank_ms")}`].filter(Boolean).join(", ")}</dd>
      </dl>
      {trace.warning && <p className="warn small">{trace.warning}</p>}
    </div>
  );
}

export function Source({ s, active }) {
  const ref = useRef(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (active) {
      setOpen(true);
      ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [active]);
  const sc = s.scores || {};
  return (
    <article ref={ref} className={"src" + (active ? " active" : "")}>
      <header>
        <span className="n">{s.n}</span>
        <div>
          <div className="src-title">{s.title}</div>
          <div className="muted small">
            page {s.page} · {s.section.replace("_", " ")}
            {sc.rerank != null && ` · relevance ${(sc.rerank * 100).toFixed(0)}%`}
            {sc.dense_rank != null && ` · semantic #${sc.dense_rank}`}
            {sc.bm25_rank != null && ` · keyword #${sc.bm25_rank}`}
          </div>
        </div>
        <a className="icon" title="Open PDF at this page" href={api.pdfUrl(s.paper_id, s.page)} target="_blank" rel="noreferrer">
          <ExternalLink size={15} />
        </a>
      </header>
      <p className={open ? "" : "clamp"} onClick={() => setOpen(!open)}>{s.text}</p>
    </article>
  );
}

export default function SourcesPanel({ sources, trace, activeCite }) {
  return (
    <aside className="margin">
      <Trace trace={trace} />
      <h4>Passages used</h4>
      {(!sources || sources.length === 0) && <p className="muted small">Passages the answer is based on will appear here. Click a citation number to jump to its passage.</p>}
      {sources?.map((s) => <Source key={s.id} s={s} active={activeCite === s.n} />)}
    </aside>
  );
}
