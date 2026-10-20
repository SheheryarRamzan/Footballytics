import { api } from "../api";
import { LANGUAGES, useT } from "../i18n";
import { live, useStore } from "../store";
import type { Mode, View } from "../types";

export function TopBar() {
  const fan = useStore((s) => s.fan);
  const setFan = useStore((s) => s.setFan);
  const view = useStore((s) => s.view);
  const setView = useStore((s) => s.setView);
  const setPitch = useStore((s) => s.setPitch);
  const connected = useStore((s) => s.connected);
  const matchday = useStore((s) => s.matchday);
  const t = useT();

  const update = async (patch: { mode?: Mode; language?: string }) => {
    if (!fan) return;
    const updated = await api.patchFan(fan.fan_id, patch);
    setFan(updated);
    if (patch.language) live.send({ languages: [patch.language] });
    if (patch.mode) setPitch(patch.mode === "analyst" ? "2d" : "3d");
  };
  const views: [View, string][] = [
    ["matchday", t("your_matchday")],
    ["centre", t("match_centre")],
    ["studio", t("studio")],
  ];
  return (
    <header className="topbar">
      <div className="brand">
        <span className="logo" aria-hidden>◆</span>
        <b>Footballytics</b>
        <span className="md">{t("matchday")} {matchday ?? "–"}</span>
        <span className={`conn ${connected ? "ok" : ""}`} title={connected ? "Live" : "Reconnecting"} />
      </div>
      <nav className="tabs" aria-label="Views">
        {views.map(([v, label]) => (
          <button key={v} className={view === v ? "on" : ""} onClick={() => setView(v)} aria-current={view === v}>
            {label}
          </button>
        ))}
      </nav>
      {fan && (
        <div className="prefs">
          <div className="seg" role="radiogroup" aria-label="Mode">
            {(["fan", "analyst", "kids", "audio"] as Mode[]).map((m) => (
              <button key={m} role="radio" aria-checked={fan.mode === m} className={fan.mode === m ? "on" : ""} onClick={() => update({ mode: m })}>
                {t(m)}
              </button>
            ))}
          </div>
          <select value={fan.language} onChange={(e) => update({ language: e.target.value })} aria-label="Language">
            {LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </select>
          <button
            className="btn small ghost"
            title="Switch profile"
            onClick={() => {
              localStorage.removeItem("fbx_fan");
              setFan(null);
            }}
          >
            {fan.display_name}
          </button>
        </div>
      )}
    </header>
  );
}
