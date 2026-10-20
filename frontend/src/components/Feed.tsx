import { useState } from "react";
import { api } from "../api";
import { useT } from "../i18n";
import { matchLabel, modeText, useStore } from "../store";
import type { FeedEntry } from "../store";

const KIND_ICON: Record<string, string> = {
  goal: "⚽", wonder_strike: "🚀", big_chance: "🎯", great_save: "🧤", penalty_awarded: "⚠️", red_card: "🟥",
  yellow_card: "🟨", momentum_swing: "📈", control_shift: "🧭", pressing_shift: "🔥", tempo_shift: "⏱️",
  line_breaking_pass: "🪡", sprint_tag: "⚡", shot_speed: "💥", high_turnover: "🔁", milestone: "🏅",
  substitution: "🔄", half_time: "⏸️", full_time: "🏁",
};

function Card({ e }: { e: FeedEntry }) {
  const fan = useStore((s) => s.fan);
  const setFan = useStore((s) => s.setFan);
  const setStage = useStore((s) => s.setStage);
  const dismiss = useStore((s) => s.dismissFeed);
  const showToast = useStore((s) => s.showToast);
  const t = useT();
  const [open, setOpen] = useState(false);
  const mode = fan?.mode ?? "fan";
  const d = e.decision;

  if (e.recap) {
    const r = e.recap;
    return (
      <li className="feed-card recap">
        <div className="fc-head">
          <span className="fc-icon" aria-hidden>🏁</span>
          <b>Full-time recap</b>
          <span className="fc-min">{r.home} {Object.values(r.score)[0]}–{Object.values(r.score)[1]} {r.away}</span>
          {r.status === "verified" && <span className="badge verified">✓ {t("verified")}</span>}
        </div>
        <div className="fc-headline">{r.headline}</div>
        <p className="fc-body">{r.summary}</p>
        <p className="fc-why-text"><b>Turning point:</b> {r.turning_point}</p>
        {mode === "analyst" && <p className="fc-why-text"><b>Tactics:</b> {r.tactical_story}</p>}
        <p className="muted small">⭐ {r.player_of_the_match_name}: {r.player_of_the_match_reason}</p>
      </li>
    );
  }
  if (d?.action === "points") {
    const pts = d.data?.points ?? 0;
    return (
      <li className={`feed-points ${pts >= 0 ? "up" : "down"}`}>
        <span className="pts">{pts > 0 ? `+${pts}` : pts}</span>
        <span>{d.line}</span>
      </li>
    );
  }
  const kind = e.moment?.kind ?? e.item?.kind ?? d?.kind ?? "";
  const r = e.item ? e.item.renditions[fan?.language ?? "en"] ?? e.item.renditions.en : undefined;
  const headline = r?.label ?? e.item?.insight.headline ?? d?.line ?? e.moment?.caption.fan;
  const body = r ? modeText(mode, r) : e.moment ? modeText(mode, e.moment.caption) : "";
  const minute = e.moment?.minute ?? e.item?.minute ?? d?.minute;
  const feedback = async (signal: string) => {
    if (!fan || !kind) return;
    const res = await api.feedback(fan.fan_id, signal, kind, e.key);
    if (res.message) showToast(res.message);
    setFan({ ...fan, taste: res.taste, weights: res.taste.weights });
    if (signal === "skip") dismiss(e.key);
  };
  return (
    <li className={`feed-card${d?.action === "cut" ? " is-cut" : ""}${d?.action === "pip" ? " is-pip" : ""}`}>
      <div className="fc-head">
        <span className="fc-icon" aria-hidden>{KIND_ICON[kind] ?? "•"}</span>
        <button className="fc-match" onClick={() => setStage(e.match_id)} title="Watch this match">
          {matchLabel(e.match_id)}
        </button>
        <span className="fc-min">{minute ? `${minute}'` : ""}</span>
        {e.item && e.item.status !== "template" && (
          <span className={`badge ${e.item.status}`} title="Claims checked against live data">
            ✓ {e.item.status === "corrected" ? t("corrected") : t("verified")}
          </span>
        )}
        {!e.item && <span className="badge pending" title="Instant template; the agents are writing the full story">live</span>}
      </div>
      {d?.line && d.line !== headline && <div className="fc-personal">{d.line}</div>}
      <div className="fc-headline">{headline}</div>
      {body && body !== headline && <p className="fc-body">{body}</p>}
      {mode === "analyst" && e.item?.insight.why_it_matters && (
        <p className="fc-why-text">{e.item.insight.why_it_matters}</p>
      )}
      <div className="fc-actions">
        {d && (
          <button className="link" onClick={() => setOpen(!open)} aria-expanded={open}>
            {t("why")}
          </button>
        )}
        <span className="spacer" />
        {fan && (
          <>
            <button className="icon" title={t("more")} onClick={() => feedback("like")}>👍</button>
            <button className="icon" title={t("less")} onClick={() => feedback("skip")}>✕</button>
          </>
        )}
      </div>
      {open && d && (
        <div className="fc-why">
          <div>Personal relevance <b>{d.relevance.toFixed(2)}</b> → {d.action === "cut" ? "cut to this match" : d.action === "pip" ? "picture-in-picture" : "feed"}</div>
          <ul>
            {d.reasons.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
          {e.moment?.why?.length ? <div className="muted">Engine: {e.moment.why.join(" · ")}</div> : null}
        </div>
      )}
    </li>
  );
}

export function Feed() {
  const feed = useStore((s) => s.feed);
  const t = useT();
  return (
    <section className="panel feed" aria-label={t("feed")}>
      <h2>{t("feed")}</h2>
      {feed.length === 0 && <p className="muted">Moments that matter to you will appear here as the matchday unfolds.</p>}
      <ul>
        {feed.map((e) => (
          <Card key={e.key} e={e} />
        ))}
      </ul>
    </section>
  );
}
