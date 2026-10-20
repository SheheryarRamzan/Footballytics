import { useState } from "react";
import { api } from "../api";
import { usePoll } from "../hooks";
import { useStore } from "../store";

/** Producer console: the agent newsroom's work, machine-readable overlay cues, health and controls. */
export function Studio() {
  const items = useStore((s) => s.items);
  const health = usePoll(() => api.health(), 3000, []);
  const [selected, setSelected] = useState<string | null>(null);
  const list = Object.values(items).sort((a, b) => b.item_id.localeCompare(a.item_id)).slice(0, 40);
  const sel = selected ? items[selected] : list[0];
  const agents = health?.agents;
  return (
    <div className="studio">
      <section className="panel studio-stats">
        <h2>Newsroom</h2>
        <div className="kpis">
          <div><b>{agents?.items ?? 0}</b><span>verified items</span></div>
          <div><b>{agents?.by_status?.corrected ?? 0}</b><span>corrected by Verifier</span></div>
          <div><b>{agents?.latency_p50_ms ? (agents.latency_p50_ms / 1000).toFixed(1) + "s" : "–"}</b><span>p50 latency</span></div>
          <div><b>{agents?.latency_p95_ms ? (agents.latency_p95_ms / 1000).toFixed(1) + "s" : "–"}</b><span>p95 latency</span></div>
          <div><b>{health?.viewers ?? 0}</b><span>viewers</span></div>
          <div><b>{(agents?.languages ?? []).join(" · ") || "en"}</b><span>languages on air</span></div>
        </div>
        <div className="controls">
          <span className="muted">Sim speed ×{health?.speed}</span>
          {[2, 4, 8].map((s) => (
            <button key={s} className="btn small ghost" onClick={() => api.speed(s)}>×{s}</button>
          ))}
          <button className="btn small ghost" onClick={() => api.restart(health?.matchday ?? 9, health?.speed ?? 4)}>Restart matchday</button>
          <code className="mcp" title="Connect GitHub Copilot, Claude or any MCP client">MCP: {location.origin}/mcp-server/mcp</code>
        </div>
      </section>
      <section className="panel studio-list">
        <h2>Broadcast items</h2>
        <ul>
          {list.map((it) => (
            <li key={it.item_id}>
              <button className={`si-row${sel?.item_id === it.item_id ? " on" : ""}`} onClick={() => setSelected(it.moment_id)}>
                <span className={`badge ${it.status}`}>{it.status}</span>
                <b>{it.match_id.replace(/^md\d+-/, "")} {it.minute}'</b>
                <span>{it.insight.headline}</span>
                <span className="muted">{(it.latency_ms / 1000).toFixed(1)}s</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
      <section className="panel studio-detail">
        <h2>Agent trace</h2>
        {!sel && <p className="muted">Waiting for the first verified item…</p>}
        {sel && (
          <>
            <ol className="trace">
              {sel.trace.map((s, i) => (
                <li key={i} className={`step ${s.agent}`}>
                  <b>{s.agent}</b>
                  {s.attempt ? <small> attempt {s.attempt}</small> : null}
                  <span className="ms">{s.ms} ms</span>
                  <div>{s.note}</div>
                  {s.issues?.map((x) => (
                    <div key={x} className="issue">⚠ {x}</div>
                  ))}
                </li>
              ))}
            </ol>
            <h3>Verified claims</h3>
            <table className="claims">
              <tbody>
                {sel.claims.map((c, i) => (
                  <tr key={i}>
                    <td>{c.ok ? "✓" : "✗"}</td>
                    <td>{c.subject_id}</td>
                    <td>{c.metric}</td>
                    <td>{c.value}</td>
                    <td className="muted">live {String(c.actual)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3>Overlay cue (machine-readable)</h3>
            <pre className="cue">{JSON.stringify(sel.overlay, null, 2)}</pre>
            <h3>Renditions</h3>
            {Object.entries(sel.renditions).map(([lang, r]) => (
              <div key={lang} className="rend" dir={lang === "ar" || lang === "ur" ? "rtl" : "ltr"}>
                <b>{lang}</b> {r.analyst}
                <div className="muted">🔊 {r.audio}</div>
              </div>
            ))}
          </>
        )}
      </section>
    </div>
  );
}
