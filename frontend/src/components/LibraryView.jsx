import { useEffect, useRef, useState } from "react";
import { ExternalLink, FileText, Loader2, RefreshCw, Trash2, Upload } from "lucide-react";
import { api } from "../api";

function List({ title, items }) {
  if (!items || items.length === 0) return null;
  return (<div className="field-block"><h4>{title}</h4><ul>{items.map((x, i) => <li key={i}>{x}</li>)}</ul></div>);
}
function Text({ title, text }) {
  return text ? (<div className="field-block"><h4>{title}</h4><p>{text}</p></div>) : null;
}

export default function LibraryView({ papers, refresh }) {
  const [sel, setSel] = useState(null);
  const [uploads, setUploads] = useState([]);
  const [sections, setSections] = useState([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [err, setErr] = useState("");
  const [drag, setDrag] = useState(false);
  const input = useRef(null);
  const paper = papers.find((p) => p.id === sel) || papers[0];

  useEffect(() => {
    if (paper) api.sections(paper.id).then(setSections).catch(() => setSections([]));
  }, [paper?.id]);

  async function addFiles(files) {
    const list = [...files].filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    for (const f of list) {
      setUploads((u) => [...u, { name: f.name, status: "Indexing…" }]);
      let status = "Added";
      try {
        const [res] = await api.upload(f);
        if (res.error) status = "Failed: " + res.error;
        else if (res.duplicate) status = "Already in your library";
        else setSel(res.paper.id);
      } catch (e) { status = "Failed: " + e.message; }
      setUploads((u) => u.map((x) => (x.name === f.name && x.status === "Indexing…" ? { ...x, status } : x)));
      await refresh();
    }
  }

  async function analyze(force) {
    setAnalyzing(true); setErr("");
    try { await api.analyze(paper.id, force); await refresh(); } catch (e) { setErr(e.message); }
    setAnalyzing(false);
  }
  async function remove(p) {
    if (!confirm(`Remove "${p.title}" from your library?`)) return;
    await api.deletePaper(p.id); setSel(null); refresh();
  }

  const a = paper?.analysis;
  const maxChunks = Math.max(1, ...sections.map((s) => s.chunks));

  return (
    <div className="page two">
      <section className="list-col">
        <h2>Library</h2>
        <div className={"drop" + (drag ? " over" : "")}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}
          onClick={() => input.current.click()}>
          <Upload size={20} />
          <strong>Drop PDFs here</strong>
          <span className="muted small">or click to choose. Papers are parsed, split by section and indexed.</span>
          <input ref={input} type="file" accept="application/pdf" multiple hidden onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
        </div>
        {uploads.slice(-4).map((u, i) => (
          <div key={i} className="up small">{u.status === "Indexing…" && <Loader2 size={13} className="spin" />} <b>{u.name}</b> · {u.status}</div>
        ))}
        <ul className="papers">
          {papers.map((p) => (
            <li key={p.id}>
              <button className={"paper" + (paper?.id === p.id ? " on" : "")} onClick={() => setSel(p.id)}>
                <FileText size={16} />
                <span><span className="p-title">{p.title}</span>
                  <span className="muted small">{(p.authors || []).slice(0, 2).join(", ")}{p.year ? ` · ${p.year}` : ""} · {p.pages} pages</span></span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="detail">
        {!paper ? (
          <div className="empty"><h1>No papers yet</h1><p>Upload research papers on the left. Then you can ask questions, compare them, and evaluate retrieval quality.</p></div>
        ) : (
          <>
            <header className="detail-head">
              <h1>{paper.title}</h1>
              <p className="muted">{(paper.authors || []).join(", ")}{paper.year ? ` · ${paper.year}` : ""}</p>
              <div className="actions">
                <a className="btn" href={api.pdfUrl(paper.id)} target="_blank" rel="noreferrer"><ExternalLink size={15} /> Open PDF</a>
                <button className="btn" onClick={() => remove(paper)}><Trash2 size={15} /> Remove</button>
              </div>
            </header>
            {paper.keywords?.length > 0 && <p className="tags">{paper.keywords.map((k) => <span key={k}>{k}</span>)}</p>}
            {paper.abstract && <div className="field-block"><h4>Abstract</h4><p className="prose">{paper.abstract}</p></div>}

            <div className="field-block">
              <h4>How the paper was split ({paper.chunks} passages)</h4>
              <div className="bars">
                {sections.map((s) => (
                  <div key={s.section} className="bar-row">
                    <span>{s.section.replace("_", " ")}</span>
                    <div className="track"><div style={{ width: `${(s.chunks / maxChunks) * 100}%` }} /></div>
                    <b>{s.chunks}</b>
                  </div>
                ))}
              </div>
            </div>

            <div className="analysis">
              <div className="analysis-head">
                <h2>Structured analysis</h2>
                <button className="btn primary" disabled={analyzing} onClick={() => analyze(!!a)}>
                  {analyzing ? <Loader2 size={15} className="spin" /> : <RefreshCw size={15} />} {a ? "Regenerate" : "Analyse paper"}
                </button>
              </div>
              {err && <p className="warn">{err}</p>}
              {!a && !analyzing && <p className="muted">Extracts the problem, method, datasets, metrics, results and limitations from the full text.</p>}
              {a && (
                <>
                  <p className="tldr">{a.tldr}</p>
                  <Text title="Problem" text={a.problem} />
                  <List title="Contributions" items={a.contributions} />
                  <Text title="Methodology" text={a.methodology} />
                  <List title="Datasets" items={a.datasets} />
                  <List title="Metrics" items={a.metrics} />
                  <List title="Key results" items={a.key_results} />
                  <List title="Limitations" items={a.limitations} />
                  <List title="Future work" items={a.future_work} />
                </>
              )}
            </div>
          </>
        )}
      </section>
    </div>
  );
}
