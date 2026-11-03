import { useEffect, useState } from "react";
import { FlaskConical, Loader2, Wand2 } from "lucide-react";
import { api } from "../api";

const LABELS = { dense: "Semantic only", bm25: "Keyword (BM25) only", hybrid: "Hybrid (RRF)", hybrid_rerank: "Hybrid + rerank" };

export default function EvalView({ papers }) {
  const [sets, setSets] = useState([]);
  const [runs, setRuns] = useState([]);
  const [setId, setSetId] = useState("");
  const [n, setN] = useState(10);
  const [k, setK] = useState(5);
  const [judge, setJudge] = useState(false);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [active, setActive] = useState(null);

  const load = async () => {
    const [s, r] = await Promise.all([api.evalSets(), api.evalRuns()]);
    setSets(s); setRuns(r);
    if (!setId && s[0]) setSetId(s[0].id);
    if (!active && r[0]) setActive(r[0]);
  };
  useEffect(() => { load().catch(() => {}); }, []);

  async function gen() {
    setBusy("gen"); setErr("");
    try { const s = await api.evalGenerate({ paper_ids: [], n }); await load(); setSetId(s.id); }
    catch (e) { setErr(e.message); }
    setBusy("");
  }
  async function run() {
    setBusy("run"); setErr("");
    try { const r = await api.evalRun({ set_id: setId, k, judge }); setActive(r); await load(); }
    catch (e) { setErr(e.message); }
    setBusy("");
  }

  const cur = sets.find((s) => s.id === setId);
  const metric = (m) => active.modes[m];

  return (
    <div className="page">
      <h2>Evaluate retrieval</h2>
      <p className="muted">
        The assistant writes test questions from random passages of your own papers. Each question is then searched
        four ways, and we check whether the source passage is found. This shows what hybrid search and reranking
        actually add on your data.
      </p>

      <div className="form row">
        <label className="field">Questions
          <input type="number" min="3" max="40" value={n} onChange={(e) => setN(+e.target.value)} />
        </label>
        <button className="btn" disabled={!!busy || papers.length === 0} onClick={gen}>
          {busy === "gen" ? <Loader2 size={16} className="spin" /> : <Wand2 size={16} />} Create test set
        </button>
      </div>

      {sets.length > 0 && (
        <div className="form row">
          <label className="field">Test set
            <select value={setId} onChange={(e) => setSetId(e.target.value)}>
              {sets.map((s) => <option key={s.id} value={s.id}>{s.n} questions · {s.created_at.replace("T", " ")}</option>)}
            </select>
          </label>
          <label className="field">Passages checked (k)
            <input type="number" min="1" max="10" value={k} onChange={(e) => setK(+e.target.value)} />
          </label>
          <label className="check"><input type="checkbox" checked={judge} onChange={(e) => setJudge(e.target.checked)} /> Also grade answers with the LLM (slower)</label>
          <button className="btn primary" disabled={!!busy || !setId} onClick={run}>
            {busy === "run" ? <Loader2 size={16} className="spin" /> : <FlaskConical size={16} />} Run evaluation
          </button>
        </div>
      )}
      {err && <p className="warn">{err}</p>}

      {active && (
        <>
          <h3>Results · {active.n} questions · k={active.k}</h3>
          <table className="cmp metrics">
            <thead><tr><th>Method</th><th>Hit rate @{active.k}</th><th>MRR @10</th><th>Avg time</th></tr></thead>
            <tbody>
              {Object.keys(LABELS).map((m) => (
                <tr key={m}>
                  <th>{LABELS[m]}</th>
                  <td><div className="track wide"><div style={{ width: `${metric(m).hit_rate * 100}%` }} /></div> {(metric(m).hit_rate * 100).toFixed(0)}%</td>
                  <td>{metric(m).mrr.toFixed(2)}</td>
                  <td>{metric(m).avg_ms.toFixed(0)} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
          {active.judge && (
            <p className="judge">LLM grades (1 to 5): faithfulness <b>{active.judge.faithfulness.toFixed(1)}</b> · relevance <b>{active.judge.relevance.toFixed(1)}</b> · correctness <b>{active.judge.correctness.toFixed(1)}</b></p>
          )}
          <details className="field-block">
            <summary>Per-question results</summary>
            {active.details.map((d, i) => (
              <div key={i} className="q">
                <p>{d.question}</p>
                <p className="muted small">
                  {Object.keys(LABELS).map((m) => `${LABELS[m]}: ${d.ranks[m] ? "rank " + d.ranks[m] : "missed"}`).join(" · ")}
                </p>
              </div>
            ))}
          </details>
        </>
      )}
      {cur && !active && <p className="muted">Press “Run evaluation” to score this test set.</p>}
      {runs.length > 1 && (
        <div className="field-block">
          <h4>Earlier runs</h4>
          <ul className="runs">
            {runs.map((r) => (
              <li key={r.id}><button onClick={() => setActive(r)}>{r.created_at.replace("T", " ")} · {r.n} questions · hybrid + rerank hit rate {(r.modes.hybrid_rerank.hit_rate * 100).toFixed(0)}%</button></li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
