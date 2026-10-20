import { useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { Stage, StatsStrip, useMatchState } from "./Stage";

/** Analyst deep-dive for the match on stage: team comparison, player leaderboard, moment timeline with evidence. */
export function MatchCentre() {
  const state = useMatchState();
  const players = useStore((s) => s.players);
  const clubs = useStore((s) => s.clubs);
  const moments = useStore((s) => s.moments);
  const stage = useStore((s) => s.stage);
  const items = useStore((s) => s.items);
  const [explained, setExplained] = useState<any>(null);

  const rows = state
    ? Object.values(state.players)
        .filter((p: any) => p.passes + p.shots + p.tackles_won + p.saves > 0)
        .sort((a: any, b: any) => b.impact - a.impact)
        .slice(0, 12)
    : [];
  const timeline = moments.filter((m) => m.match_id === stage && m.importance >= 35).slice(0, 30);
  const team = (id: string) => clubs[id];

  return (
    <div className="centre">
      <div className="centre-main">
        <Stage analystControls />
        <StatsStrip state={state} />
      </div>
      <aside className="centre-side">
        <section className="panel">
          <h2>Team comparison</h2>
          {state && (
            <table className="compare">
              <thead>
                <tr>
                  <th style={{ color: team(state.home)?.primary }}>{state.home}</th>
                  <th />
                  <th style={{ color: team(state.away)?.primary }}>{state.away}</th>
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    ["Goals", "goals"], ["xG", "xg"], ["Shots", "shots"], ["On target", "shots_on_target"],
                    ["Big chances", "big_chances"], ["Passes", "passes"], ["Expected threat", "xt"],
                    ["High turnovers", "high_turnovers"], ["Tackles won", "tackles_won"], ["Interceptions", "interceptions"],
                    ["Corners", "corners"], ["Fouls", "fouls"], ["Distance (km)", "distance_km"],
                  ] as [string, string][]
                ).map(([label, key]) => {
                  const h = (state.teams[state.home] as any)[key];
                  const a = (state.teams[state.away] as any)[key];
                  const fmt = (v: number) => (typeof v === "number" && !Number.isInteger(v) ? v.toFixed(2) : v);
                  return (
                    <tr key={key}>
                      <td className={h > a ? "lead" : ""}>{fmt(h)}</td>
                      <th>{label}</th>
                      <td className={a > h ? "lead" : ""}>{fmt(a)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
        <section className="panel">
          <h2>Player impact</h2>
          <table className="leaders">
            <thead>
              <tr>
                <th>Player</th>
                <th title="Impact score: xG, xT, chances created, defensive actions">Imp</th>
                <th>xG</th>
                <th title="Expected threat added by passes and carries">xT</th>
                <th title="Average pass difficulty 1-10">Diff</th>
                <th title="Pass accuracy">Acc</th>
                <th title="Top speed km/h">Top</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p: any) => (
                <tr key={p.player_id}>
                  <td>
                    <i className="dot" style={{ background: clubs[players[p.player_id]?.club_id]?.primary }} />
                    {players[p.player_id]?.name ?? p.player_id}
                  </td>
                  <td>{p.impact.toFixed(1)}</td>
                  <td>{p.xg.toFixed(2)}</td>
                  <td>{p.xt_added.toFixed(2)}</td>
                  <td>{p.avg_pass_difficulty ?? "–"}</td>
                  <td>{p.pass_accuracy != null ? `${Math.round(p.pass_accuracy * 100)}%` : "–"}</td>
                  <td>{p.top_speed_kmh.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section className="panel">
          <h2>Key moments · evidence</h2>
          <ul className="timeline">
            {timeline.map((m) => {
              const it = items[m.moment_id];
              return (
                <li key={m.moment_id}>
                  <button className="tl-row" onClick={async () => setExplained(await api.explain(m.moment_id))}>
                    <span className="tl-min">{m.minute}'</span>
                    <span className="tl-text">
                      <b>{it?.insight.headline ?? m.caption.analyst}</b>
                      <small>{m.why.join(" · ")}</small>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          {explained && (
            <div className="explain">
              <h3>
                Evidence · {explained.kind.replace(/_/g, " ")} {explained.minute}'
                <button className="link" onClick={() => setExplained(null)}>close</button>
              </h3>
              {explained.evidence.map((ev: any) => (
                <div key={ev.event_id} className="ev">
                  <code>{ev.event_id}</code> {ev.type} by {ev.player} → {ev.outcome}
                  {ev.assessment && (
                    <pre>{JSON.stringify(ev.assessment, null, 1)}</pre>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
      </aside>
    </div>
  );
}
