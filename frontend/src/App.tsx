import { useEffect } from "react";
import { api } from "./api";
import { Desk } from "./components/Desk";
import { FantasyPanel } from "./components/Fantasy";
import { Feed } from "./components/Feed";
import { FocusBoard } from "./components/FocusBoard";
import { MatchCentre } from "./components/MatchCentre";
import { ScoresRail } from "./components/ScoresRail";
import { Setup } from "./components/Setup";
import { Stage, StatsStrip, useMatchState } from "./components/Stage";
import { Studio } from "./components/Studio";
import { TopBar } from "./components/TopBar";
import { useAudioDescription } from "./hooks";
import { isRtl } from "./i18n";
import { live, useStore } from "./store";

function Matchday() {
  const state = useMatchState();
  return (
    <div className="matchday">
      <div className="md-main">
        <Stage />
        <StatsStrip state={state} />
      </div>
      <aside className="md-side">
        <FantasyPanel />
        <FocusBoard />
        <Feed />
        <Desk />
      </aside>
    </div>
  );
}

export function App() {
  const fan = useStore((s) => s.fan);
  const view = useStore((s) => s.view);
  const clubs = useStore((s) => s.clubs);
  const setLeague = useStore((s) => s.setLeague);
  const setFan = useStore((s) => s.setFan);
  useAudioDescription();

  useEffect(() => {
    api.league().then((l) => setLeague(l.clubs));
    const saved = localStorage.getItem("fbx_fan");
    if (saved) {
      api
        .getFan(saved)
        .then((f) => {
          setFan(f);
          live.send({ fan_id: f.fan_id, languages: [f.language] });
        })
        .catch(() => localStorage.removeItem("fbx_fan"));
    }
    live.connect();
  }, [setLeague, setFan]);

  useEffect(() => {
    document.documentElement.dir = fan && isRtl(fan.language) ? "rtl" : "ltr";
    document.documentElement.lang = fan?.language ?? "en";
    document.body.dataset.mode = fan?.mode ?? "fan";
  }, [fan]);

  const toast = useStore((s) => s.toast);
  if (!Object.keys(clubs).length) return <div className="loading">Loading the league…</div>;
  if (!fan && view === "matchday") {
    return (
      <>
        <TopBar />
        <Setup />
      </>
    );
  }
  return (
    <div className="app">
      <TopBar />
      <ScoresRail />
      {view === "matchday" && <Matchday />}
      {view === "centre" && <MatchCentre />}
      {view === "studio" && <Studio />}
      {toast && view !== "matchday" && <div className="toast floating">{toast}</div>}
    </div>
  );
}
