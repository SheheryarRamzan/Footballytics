import { useState } from "react";
import { api } from "../api";
import { FOCUS_METRICS, LANGUAGES, focusLabel, tr } from "../i18n";
import { live, useStore } from "../store";
import type { FocusMetric, Mode } from "../types";
import { contrastText } from "../pitch/shared";

const MODES: { id: Mode; title: string; text: string }[] = [
  { id: "fan", title: "Fan", text: "The story, the drama, your players. Broadcast 3D camera." },
  { id: "analyst", title: "Analyst", text: "Tactics first: pitch control, pressing, xG, pass difficulty." },
  { id: "kids", title: "Kids", text: "Simple words, big moments, speed and saves." },
  { id: "audio", title: "Audio description", text: "Spoken descriptions of where and how the play happened." },
];

export function Setup() {
  const clubs = useStore((s) => s.clubs);
  const setFan = useStore((s) => s.setFan);
  const [club, setClub] = useState("KGA");
  const [mode, setMode] = useState<Mode>("fan");
  const [language, setLanguage] = useState("en");
  const [metric, setMetric] = useState<FocusMetric | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const fan = await api.createFan({
        favorite_club: club,
        mode,
        language,
        display_name: name.trim() || "Fan",
        focus_metric: metric,
      });
      localStorage.setItem("fbx_fan", fan.fan_id);
      setFan(fan);
      useStore.getState().setPitch(mode === "analyst" ? "2d" : "3d");
      live.send({ fan_id: fan.fan_id, languages: [language] });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const list = Object.values(clubs).sort((a, b) => a.name.localeCompare(b.name));
  return (
    <main className="setup">
      <div className="setup-card">
        <h1>
          Every match, <span className="accent">made for you.</span>
        </h1>
        <p className="lead">
          Ten matches kick off at once. Footballytics follows your club and your fantasy squad across all of them, cuts to
          the moments that matter to you, and explains why, in your language and at your depth.
        </p>
        <h2>1 · Your club</h2>
        <div className="club-grid" role="radiogroup" aria-label="Favourite club">
          {list.map((c) => (
            <button
              key={c.id}
              role="radio"
              aria-checked={club === c.id}
              className={`club${club === c.id ? " on" : ""}`}
              onClick={() => setClub(c.id)}
            >
              <span className="crest" style={{ background: c.primary, color: contrastText(c.primary), borderColor: c.secondary }}>
                {c.id}
              </span>
              <span>{c.name}</span>
            </button>
          ))}
        </div>
        <h2>2 · How you like to watch</h2>
        <div className="mode-grid" role="radiogroup" aria-label="Viewing mode">
          {MODES.map((m) => (
            <button key={m.id} role="radio" aria-checked={mode === m.id} className={`mode${mode === m.id ? " on" : ""}`} onClick={() => setMode(m.id)}>
              <b>{m.title}</b>
              <span>{m.text}</span>
            </button>
          ))}
        </div>
        <h2>
          3 · {tr("follow_stat", "en")} ({tr("optional", "en")})
        </h2>
        <div className="stat-grid" role="radiogroup" aria-label={tr("follow_stat", "en")}>
          {[null, ...FOCUS_METRICS].map((m) => {
            const [label, note] = m ? focusLabel(m, "en") : [tr("no_stat", "en"), "just my club and squad"];
            return (
              <button key={m ?? "none"} role="radio" aria-checked={metric === m} className={`mode${metric === m ? " on" : ""}`} onClick={() => setMetric(m)}>
                <b>{label}</b>
                <span>{note}</span>
              </button>
            );
          })}
        </div>
        <div className="setup-row">
          <label>
            Language
            <select value={language} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Name (optional)
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Fan" maxLength={24} />
          </label>
        </div>
        <p className="muted small">We'll pick a valid 15-player fantasy squad for you (budget 100, max 3 per club). Tap any player later to follow them on Player Cam. Follow a stat and the Director boosts those moments, with a live top 5 across all ten matches.</p>
        {error && <p className="error">{error}</p>}
        <button className="btn big" onClick={start} disabled={busy}>
          {busy ? "Setting up…" : "Start my matchday →"}
        </button>
        <p className="muted small">All clubs, players and match data are synthetic and fictional.</p>
      </div>
    </main>
  );
}
