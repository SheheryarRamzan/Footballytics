import { useState } from "react";
import { api } from "../api";
import { usePoll } from "../hooks";
import { useT } from "../i18n";
import { useStore } from "../store";

/** Live fantasy squad: points per player (captain doubled), tap a player to follow them on Player Cam. */
export function FantasyPanel() {
  const fan = useStore((s) => s.fan);
  const setFan = useStore((s) => s.setFan);
  const setCamera = useStore((s) => s.setCamera);
  const setPitch = useStore((s) => s.setPitch);
  const matches = useStore((s) => s.matches);
  const setStage = useStore((s) => s.setStage);
  const showToast = useStore((s) => s.showToast);
  const players = useStore((s) => s.players);
  const t = useT();
  const [open, setOpen] = useState(true);
  const ids = fan?.squad.join(",") ?? "";
  const pts = usePoll(() => fetch(`/api/fantasy?player_ids=${ids}`).then((r) => r.json()), 4000, [ids], !!fan);
  if (!fan) return null;
  const byId: Record<string, { points: number; breakdown: [string, number][]; match_id: string }> = {};
  for (const r of pts ?? []) byId[r.player_id] = r;
  const pointsOf = (pid: string) => (byId[pid]?.points ?? 0) * (pid === fan.captain ? 2 : 1);
  const total = fan.squad.reduce((acc, pid) => acc + pointsOf(pid), 0);
  const follow = async (pid: string) => {
    if (pts && !byId[pid]) {
      showToast(`${players[pid]?.name ?? pid} isn't playing this matchday, so there's no one for Player Cam to follow.`);
      return;
    }
    const updated = await api.patchFan(fan.fan_id, { focus_player: pid });
    setFan(updated);
    const club = players[pid]?.club_id;
    const m = Object.values(matches).find((x) => x.home === club || x.away === club);
    if (m) setStage(m.match_id);
    setPitch("3d");
    setCamera("player");
  };
  const groups = ["GK", "DEF", "MID", "FWD"];
  return (
    <section className="panel fantasy" aria-label={t("squad")}>
      <h2>
        <button className="link" onClick={() => setOpen(!open)} aria-expanded={open}>
          {t("squad")}
        </button>
        <span className="total">
          {total} <small>{t("points")}</small>
        </span>
      </h2>
      {open && (
        <ul className="squad">
          {groups.flatMap((g) =>
            fan.squad_detail
              .filter((p) => p.group === g)
              .map((p) => {
                const b = byId[p.player_id];
                const val = pointsOf(p.player_id);
                const bench = !!pts && !b;
                return (
                  <li key={p.player_id} className={`${p.player_id === fan.focus_player ? "following" : ""}${bench ? " bench" : ""}`}>
                    <button className="sq-row" onClick={() => follow(p.player_id)} title="Follow on Player Cam">
                      <span className="sq-pos">{p.group}</span>
                      <span className="sq-name">
                        {p.name}
                        {p.captain && <em className="cap">C</em>}
                        {p.vice_captain && <em className="vc">V</em>}
                        {bench && <em className="bn">BENCH</em>}
                      </span>
                      <span className="sq-club">{p.club}</span>
                      <span className="sq-pts" title={b?.breakdown.map(([r, v]) => `${r} ${v > 0 ? "+" : ""}${v}`).join(", ")}>
                        {val}
                      </span>
                    </button>
                  </li>
                );
              }),
          )}
        </ul>
      )}
    </section>
  );
}
