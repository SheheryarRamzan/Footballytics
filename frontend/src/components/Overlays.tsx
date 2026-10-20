import { useNow } from "../hooks";
import { useT } from "../i18n";
import { matchLabel, modeText, useStore } from "../store";
import type { ActiveOverlay } from "../store";

function Scorebug() {
  const stage = useStore((s) => s.stage);
  const m = useStore((s) => (s.stage ? s.matches[s.stage] : undefined));
  const clubs = useStore((s) => s.clubs);
  const t = useT();
  if (!m || !stage) return null;
  const h = clubs[m.home];
  const a = clubs[m.away];
  return (
    <div className="scorebug" role="status" aria-label={`${m.home_name} ${m.score[0]} ${m.away_name} ${m.score[1]}`}>
      <span className="sb-team" style={{ background: h?.primary }}>{m.home}</span>
      <span className="sb-score">
        {m.score[0]}<i>–</i>{m.score[1]}
      </span>
      <span className="sb-team" style={{ background: a?.primary }}>{m.away}</span>
      <span className="sb-clock">{m.status === "LIVE" ? `${m.minute}'` : m.status}</span>
      {m.status === "LIVE" && <span className="sb-live">{t("live")}</span>}
    </div>
  );
}

function OverlayCard({ o }: { o: ActiveOverlay }) {
  const mode = useStore((s) => s.fan?.mode ?? "fan");
  const lang = useStore((s) => s.fan?.language ?? "en");
  const players = useStore((s) => s.players);
  const clubs = useStore((s) => s.clubs);
  const t = useT();
  const m = o.moment;
  const r = o.item?.renditions[lang] ?? o.item?.renditions.en;
  const text = r ? modeText(mode, r) : modeText(mode, m.caption);
  const label = r?.label ?? o.item?.insight.headline ?? m.caption.fan;
  const verified = o.item && o.item.status !== "template";
  const badge = verified && (
    <span className={`badge ${o.item!.status}`} title="Every number was checked against live data by the Verifier agent">
      ✓ {o.item!.status === "corrected" ? t("corrected") : t("verified")}
    </span>
  );
  const team = m.team_id ? clubs[m.team_id] : undefined;
  const who = m.player_ids[0] ? players[m.player_ids[0]]?.name : undefined;

  if (o.template === "goal_card") {
    return (
      <div className="ov-goal" style={{ ["--team" as any]: team?.primary ?? "#22d3a6" }}>
        <div className="ov-goal-word">{m.kind === "wonder_strike" ? "WONDER GOAL" : "GOAL"}</div>
        <div className="ov-goal-who">{who} · {team?.name}</div>
        <div className="ov-goal-facts">
          {m.facts.xg != null && <span>xG {Number(m.facts.xg).toFixed(2)}</span>}
          {m.facts.shot_speed_kmh ? <span>{Math.round(m.facts.shot_speed_kmh)} km/h</span> : null}
          {m.facts.distance_m ? <span>{Math.round(m.facts.distance_m)} m</span> : null}
          <span>{m.facts.score}</span>
        </div>
        {r && <div className="ov-goal-line">{text} {badge}</div>}
      </div>
    );
  }
  if (o.template === "shot_card" || o.template === "stat_bubble" || o.template === "player_tag") {
    return (
      <div className="ov-chip">
        <b>{label}</b>
        <span>{text}</span>
        {badge}
      </div>
    );
  }
  if (o.template === "full_screen") {
    return (
      <div className="ov-full">
        <div className="ov-full-title">{m.kind === "full_time" ? "FULL TIME" : "HALF TIME"}</div>
        <div className="ov-full-score">{m.facts.score}</div>
        <div className="ov-full-stats">
          xG {Number(m.facts.xg_home ?? 0).toFixed(2)} – {Number(m.facts.xg_away ?? 0).toFixed(2)} · Shots {m.facts.shots_home} – {m.facts.shots_away}
        </div>
        {r && <div className="ov-full-line">{text}</div>}
      </div>
    );
  }
  return (
    <div className="ov-lower">
      <div className="ov-lower-label" style={{ borderColor: team?.primary ?? "var(--accent)" }}>
        {label}
      </div>
      <div className="ov-lower-text">
        {text} {badge}
      </div>
    </div>
  );
}

export function Overlays() {
  const now = useNow(400);
  const overlays = useStore((s) => s.overlays);
  const pip = useStore((s) => s.pip);
  const setStage = useStore((s) => s.setStage);
  const toast = useStore((s) => s.toast);
  const t = useT();
  const active = overlays.filter((o) => o.until > now);
  const goal = active.find((o) => o.template === "goal_card" || o.template === "full_screen");
  const lower = [...active].reverse().find((o) => o.template === "lower_third" || o.template === "pass_arc" || o.template === "momentum_ribbon");
  const chips = active.filter((o) => ["shot_card", "stat_bubble", "player_tag"].includes(o.template)).slice(-2);
  return (
    <div className="overlays" aria-live="polite">
      <Scorebug />
      {toast && <div className="toast">{toast}</div>}
      {pip && (
        <div className="pip" role="dialog" aria-label="Also happening">
          <div className="pip-head">
            <span className="pip-dot" /> {matchLabel(pip.match_id)} · {pip.minute}'
          </div>
          <div className="pip-line">{pip.line}</div>
          <button className="btn small" onClick={() => setStage(pip.match_id)}>
            {t("watch")} →
          </button>
        </div>
      )}
      <div className="ov-chips">
        {chips.map((o) => (
          <OverlayCard key={o.key} o={o} />
        ))}
      </div>
      {goal && <OverlayCard o={goal} />}
      {!goal && lower && <OverlayCard o={lower} />}
    </div>
  );
}
