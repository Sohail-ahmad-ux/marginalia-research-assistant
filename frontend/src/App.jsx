import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";
import LibraryView from "./components/LibraryView";
import CompareView from "./components/CompareView";
import EvalView from "./components/EvalView";

export default function App() {
  const [tab, setTab] = useState("chat");
  const [papers, setPapers] = useState([]);
  const [convs, setConvs] = useState([]);
  const [convId, setConvId] = useState(null);
  const [health, setHealth] = useState(null);

  const refreshPapers = useCallback(() => api.papers().then(setPapers).catch(() => {}), []);
  const refreshConvs = useCallback(() => api.conversations().then(setConvs).catch(() => {}), []);

  useEffect(() => {
    refreshPapers();
    refreshConvs();
    api.health().then(setHealth).catch(() => setHealth({ ok: false }));
  }, [refreshPapers, refreshConvs]);

  const newChat = () => {
    setConvId(null);
    setTab("chat");
  };
  const pickConv = (id) => {
    setConvId(id);
    setTab("chat");
  };
  const delConv = async (id) => {
    await api.deleteConversation(id);
    if (id === convId) setConvId(null);
    refreshConvs();
  };

  return (
    <div className="app">
      <Sidebar tab={tab} setTab={setTab} convs={convs} convId={convId} onPick={pickConv}
        onNew={newChat} onDelete={delConv} health={health} paperCount={papers.length} />
      <main className="main">
        {health && !health.ok && (
          <div className="banner">Cannot reach the backend. Start it with <code>uvicorn app.main:app --port 8000</code> in the backend folder.</div>
        )}
        {health?.ok && !health.has_key && (
          <div className="banner">No Gemini key found. Add <code>GOOGLE_API_KEY</code> to <code>backend/.env</code> and restart the backend.</div>
        )}
        {tab === "chat" && (
          <ChatView papers={papers} convId={convId} setConvId={setConvId}
            refreshConvs={refreshConvs} goLibrary={() => setTab("library")} />
        )}
        {tab === "library" && <LibraryView papers={papers} refresh={refreshPapers} />}
        {tab === "compare" && <CompareView papers={papers} />}
        {tab === "eval" && <EvalView papers={papers} />}
      </main>
    </div>
  );
}
