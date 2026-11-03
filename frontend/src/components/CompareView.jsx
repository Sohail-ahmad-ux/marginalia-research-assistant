import { useState } from "react";
import { GitCompare, Loader2 } from "lucide-react";
import { api } from "../api";
import Markdown from "./Markdown";
import { Source } from "./SourcesPanel";

const DEFAULT = "Research problem, Methodology, Datasets, Results and metrics, Limitations";

export default function CompareView({ papers }) {
  const [sel, setSel] = useState([]);
  const [aspects, setAspects] = useState(DEFAULT);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState("");
  const [cite, setCite] = useState(null);

  const toggle = (id) => setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  async function run() {
    setBusy(true); setErr(""); setRes(null); setCite(null);
    try { setRes(await api.compare({ paper_ids: sel, aspects: aspects.split(",").map((a) => a.trim()).filter(Boolean) })); }
    catch (e) { setErr(e.message); }
    setBusy(false);
  }

  return (
    <div className="page">
      <h2>Compare papers</h2>
      <p className="muted">Each cell is written from passages retrieved for that paper and aspect, with citations.</p>
      <div className="form">
        <h4>Papers (choose 2 or more)</h4>
        {papers.length === 0 && <p className="muted">Add papers in the Library first.</p>}
        {papers.map((p) => (
          <label key={p.id} className="check"><input type="checkbox" checked={sel.includes(p.id)} onChange={() => toggle(p.id)} /> {p.title}</label>
        ))}
        <label className="field">Aspects to compare (comma separated)
          <input value={aspects} onChange={(e) => setAspects(e.target.value)} />
        </label>
        <button className="btn primary" disabled={busy || sel.length < 2} onClick={run}>
          {busy ? <Loader2 size={16} className="spin" /> : <GitCompare size={16} />} Compare
        </button>
        {err && <p className="warn">{err}</p>}
      </div>

      {res && (
        <>
          <div className="table-wrap">
            <table className="cmp">
              <thead>
                <tr><th></th>{res.papers.map((p) => <th key={p.id}>{p.title}</th>)}</tr>
              </thead>
              <tbody>
                {res.rows.map((r) => (
                  <tr key={r.aspect}>
                    <th>{r.aspect}</th>
                    {res.papers.map((p) => <td key={p.id}><Markdown text={r.cells[p.id]} onCite={setCite} /></td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="field-block"><h4>Summary</h4><div className="prose"><Markdown text={res.summary} onCite={setCite} /></div></div>
          <div className="field-block">
            <h4>Sources {cite ? "" : "(click a citation to highlight)"}</h4>
            <div className="src-grid">{res.sources.map((s) => <Source key={s.n} s={s} active={cite === s.n} />)}</div>
          </div>
        </>
      )}
    </div>
  );
}
