import { useStore } from "../store";

/** All live matches at a glance; your club and squad presence are marked; click to watch. */
export function ScoresRail() {
  const order = useStore((s) => s.order);
  const matches = useStore((s) => s.matches);
  const stage = useStore((s) => s.stage);
  const clubs = useStore((s) => s.clubs);
  const fan = useStore((s) => s.fan);
  const players = useStore((s) => s.players);
  const setStage = useStore((s) => s.setStage);
  const squadClubs: Record<string, number> = {};
  for (const pid of fan?.squad ?? []) {
    const c = players[pid]?.club_id;
    if (c) squadClubs[c] = (squadClubs[c] ?? 0) + 1;
  }
  return (
    <nav className="rail" aria-label="Live matches">
      {order.map((id) => {
        const m = matches[id];
        if (!m) return null;
        const mine = (squadClubs[m.home] ?? 0) + (squadClubs[m.away] ?? 0);
        const club = fan && (m.home === fan.favorite_club || m.away === fan.favorite_club);
        return (
          <button
            key={id}
            className={`chip${id === stage ? " on" : ""}${club ? " club" : ""}`}
            onClick={() => setStage(id)}
            aria-pressed={id === stage}
            title={`${m.home_name} v ${m.away_name}`}
          >
            <span className="chip-row">
              <i style={{ background: clubs[m.home]?.primary }} />
              <b>{m.home}</b>
              <span className="chip-score">{m.score[0]}</span>
            </span>
            <span className="chip-row">
              <i style={{ background: clubs[m.away]?.primary }} />
              <b>{m.away}</b>
              <span className="chip-score">{m.score[1]}</span>
            </span>
            <span className="chip-meta">
              {m.status === "LIVE" ? `${m.minute}'` : m.status}
              {mine > 0 && <em title={`${mine} of your players`}>★{mine}</em>}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
