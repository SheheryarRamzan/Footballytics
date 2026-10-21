import { api } from "../api";
import { usePoll } from "../hooks";
import { Pitch2D } from "../pitch/Pitch2D";
import { Pitch3D } from "../pitch/Pitch3D";
import { matchLabel, useStore } from "../store";
import type { MatchState } from "../types";
import { Overlays } from "./Overlays";

export function Stage({ analystControls = false }: { analystControls?: boolean }) {
  const pitch = useStore((s) => s.pitch);
  const camera = useStore((s) => s.camera);
  const setPitch = useStore((s) => s.setPitch);
  const setCamera = useStore((s) => s.setCamera);
  const mode = useStore((s) => s.fan?.mode ?? "fan");
  const showControl = analystControls || mode === "analyst";
  return (
    <section className="stage" aria-label="Main stage">
      <div className="stage-view">
        {pitch === "3d" ? <Pitch3D /> : <Pitch2D showControl={showControl} />}
        <Overlays />
      </div>
      <div className="stage-controls" role="toolbar" aria-label="View options">
        <div className="seg">
          <button className={pitch === "3d" ? "on" : ""} onClick={() => setPitch("3d")}>Broadcast 3D</button>
          <button className={pitch === "2d" ? "on" : ""} onClick={() => setPitch("2d")}>Tactical 2D</button>
        </div>
        {pitch === "3d" && (
          <div className="seg">
            <button className={camera === "broadcast" ? "on" : ""} onClick={() => setCamera("broadcast")}>TV camera</button>
            <button className={camera === "player" ? "on" : ""} onClick={() => setCamera("player")}>Player Cam</button>
            <button className={camera === "tactical" ? "on" : ""} onClick={() => setCamera("tactical")}>Overhead</button>
          </div>
        )}
        {pitch === "3d" && camera === "player" && <FollowChip />}
        {pitch === "2d" && showControl && <span className="hint">Shaded: who controls each space (pitch control)</span>}
      </div>
    </section>
  );
}

/** Who Player Cam is following; if your own player is in another match, one tap takes you there. */
function FollowChip() {
  const following = useStore((s) => s.following);
  const players = useStore((s) => s.players);
  const fan = useStore((s) => s.fan);
  const stage = useStore((s) => s.stage);
  const matches = useStore((s) => s.matches);
  const setStage = useStore((s) => s.setStage);
  const preferred = fan?.focus_player ?? fan?.captain ?? null;
  const club = preferred ? players[preferred]?.club_id : undefined;
  const elsewhere = club && preferred !== following
    ? Object.values(matches).find((m) => (m.home === club || m.away === club) && m.match_id !== stage)
    : undefined;
  const who = following ? players[following] : undefined;
  return (
    <span className="follow-chip" role="status">
      {who ? <>🎥 Following <b>{who.name}</b></> : "🎥 Finding a player…"}
      {elsewhere && preferred && (
        <button className="btn small ghost" onClick={() => setStage(elsewhere.match_id)}>
          Follow {players[preferred]?.short_name ?? "your player"} in {matchLabel(elsewhere.match_id)} →
        </button>
      )}
    </span>
  );
}

const REGIME_TEXT: Record<string, string> = {
  balanced: "Contested",
  chaos: "Chaos",
  home_control: "Home in control",
  away_control: "Away in control",
};

export function useMatchState(): MatchState | null {
  const stage = useStore((s) => s.stage);
  return usePoll(() => api.match(stage!), 2000, [stage], !!stage);
}

export function StatsStrip({ state }: { state: MatchState | null }) {
  const clubs = useStore((s) => s.clubs);
  if (!state) return <div className="stats-strip muted">Loading match stats…</div>;
  const h = state.teams[state.home];
  const a = state.teams[state.away];
  const hp = clubs[state.home]?.primary;
  const ap = clubs[state.away]?.primary;
  const rows: [string, string | number, string | number, number][] = [
    ["Possession", pct(h.possession), pct(a.possession), h.possession ?? 0.5],
    ["xG", h.xg.toFixed(2), a.xg.toFixed(2), share(h.xg, a.xg)],
    ["Shots", `${h.shots} (${h.shots_on_target})`, `${a.shots} (${a.shots_on_target})`, share(h.shots, a.shots)],
    ["Pass acc.", pct(h.pass_completion), pct(a.pass_completion), share(h.pass_completion ?? 0, a.pass_completion ?? 0)],
    ["Field tilt", pct(state.field_tilt[state.home]), pct(state.field_tilt[state.away]), state.field_tilt[state.home] ?? 0.5],
  ];
  const regime = state.regime.replace("home", state.home).replace("away", state.away);
  return (
    <div className="stats-strip">
      {rows.map(([label, hv, av, s]) => (
        <div className="stat" key={label}>
          <div className="stat-vals">
            <b>{hv}</b>
            <span>{label}</span>
            <b>{av}</b>
          </div>
          <div className="bar">
            <i style={{ width: `${Math.round(s * 100)}%`, background: hp }} />
            <i style={{ width: `${Math.round((1 - s) * 100)}%`, background: ap }} />
          </div>
        </div>
      ))}
      <div className={`regime r-${state.regime}`} title="Control vs chaos: possession share, turnovers and duels in the last 5 minutes">
        {REGIME_TEXT[state.regime] ? REGIME_TEXT[state.regime].replace("Home", state.home).replace("Away", state.away) : regime}
      </div>
      <Momentum state={state} />
    </div>
  );
}

function Momentum({ state }: { state: MatchState }) {
  const clubs = useStore((s) => s.clubs);
  const series = state.momentum.slice(-30);
  const w = 240;
  const hgt = 46;
  const bw = w / 30;
  return (
    <figure className="momentum" aria-label="Momentum: share of attacking threat over the last minutes">
      <svg viewBox={`0 0 ${w} ${hgt}`} width="100%" height={hgt} preserveAspectRatio="none">
        <line x1="0" x2={w} y1={hgt / 2} y2={hgt / 2} stroke="var(--line)" />
        {series.map((p, i) => {
          const v = Math.max(-1, Math.min(1, p.value));
          const hpx = Math.abs(v) * (hgt / 2 - 2);
          return (
            <rect
              key={p.minute}
              x={i * bw + 1}
              width={bw - 2}
              y={v > 0 ? hgt / 2 - hpx : hgt / 2}
              height={Math.max(1, hpx)}
              rx="1.5"
              fill={v > 0 ? clubs[state.home]?.primary : clubs[state.away]?.primary}
            />
          );
        })}
      </svg>
      <figcaption>Momentum · last 30'</figcaption>
    </figure>
  );
}

const pct = (v?: number | null) => (v == null ? "–" : `${Math.round(v * 100)}%`);
const share = (a: number, b: number) => (a + b > 0 ? a / (a + b) : 0.5);
