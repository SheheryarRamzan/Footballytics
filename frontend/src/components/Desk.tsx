import { useState } from "react";
import { api } from "../api";
import { useT } from "../i18n";
import { useStore } from "../store";

const SUGGESTIONS = [
  "Which match should I watch right now?",
  "How is my captain doing?",
  "Why is this game so chaotic?",
  "Who has been the best player so far?",
];

/** Ask the pundit (tool-using agent) and get the Director's personal rundown. */
export function Desk() {
  const fan = useStore((s) => s.fan);
  const stage = useStore((s) => s.stage);
  const setStage = useStore((s) => s.setStage);
  const t = useT();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState<"ask" | "brief" | null>(null);
  const [answer, setAnswer] = useState<{ answer: string; tool_calls: { tool: string; ms: number }[]; latency_ms: number } | null>(null);
  const [brief, setBrief] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const ask = async (question: string) => {
    if (!question.trim()) return;
    setBusy("ask");
    setError(null);
    try {
      setAnswer(await api.ask(question, fan?.fan_id, stage));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };
  const getBrief = async () => {
    if (!fan) return;
    setBusy("brief");
    setError(null);
    try {
      setBrief(await api.rundown(fan.fan_id));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="panel desk" aria-label={t("ask")}>
      <h2>
        {t("ask")}
        {fan && (
          <button className="btn small ghost" onClick={getBrief} disabled={busy !== null}>
            {busy === "brief" ? "Planning…" : `🎬 ${t("brief")}`}
          </button>
        )}
      </h2>
      <form
        className="ask"
        onSubmit={(e) => {
          e.preventDefault();
          ask(q);
        }}
      >
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask anything about the matchday…" aria-label="Question" />
        <button className="btn" disabled={busy !== null}>{busy === "ask" ? "…" : "Ask"}</button>
      </form>
      <div className="suggest">
        {SUGGESTIONS.map((s) => (
          <button key={s} className="pill" onClick={() => { setQ(s); ask(s); }} disabled={busy !== null}>
            {s}
          </button>
        ))}
      </div>
      {error && <p className="error">{error}</p>}
      {answer && (
        <div className="answer">
          <p>{answer.answer}</p>
          <div className="tools" title="Football Intelligence tools the agent called (the same tools our MCP server exposes)">
            {answer.tool_calls.map((c, i) => (
              <code key={i}>{c.tool}</code>
            ))}
            <span className="muted">{(answer.latency_ms / 1000).toFixed(1)}s</span>
          </div>
        </div>
      )}
      {brief && (
        <div className="brief">
          <h3>{brief.headline}</h3>
          <p>{brief.summary}</p>
          <p className="muted">{brief.squad}</p>
          <div className="watch-next">
            {brief.watch_next.map((w: any) => (
              <button key={w.match_id} className="watch-row" onClick={() => setStage(w.match_id)}>
                <b>▶ {w.match_id.replace(/^md\d+-/, "").replace("-", " v ")}</b>
                <span>{w.why}</span>
              </button>
            ))}
          </div>
          <ul className="storylines">
            {brief.storylines.map((s: string) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
