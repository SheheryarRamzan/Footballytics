import { api } from "../api";
import { usePoll } from "../hooks";
import { FOCUS_METRICS, focusLabel, useT } from "../i18n";
import { useStore } from "../store";
import type { FocusMetric } from "../types";

/** Follow one stat: pick (or change) the metric and see its live top 5 across every match; tap a row to watch. */
export function FocusBoard() {
  const fan = useStore((s) => s.fan);
  const setFan = useStore((s) => s.setFan);
  const setStage = useStore((s) => s.setStage);
  const stage = useStore((s) => s.stage);
  const clubs = useStore((s) => s.clubs);
  const t = useT();
  const metric = fan?.focus_metric ?? null;
  const board = usePoll(() => api.leaders(metric!), 3000, [metric], !!metric);
  if (!fan) return null;
  const lang = fan.language;
  const rows = board?.metric === metric ? board.rows : [];
  const choose = async (m: FocusMetric | null) => setFan(await api.patchFan(fan.fan_id, { focus_metric: m }));
  return (
    <section className="panel focus-board" aria-label={t("follow_stat")}>
      <h2>
        {metric ? t("leaders") : t("follow_stat")}
        <select
          value={metric ?? ""}
          onChange={(e) => choose((e.target.value || null) as FocusMetric | null)}
          aria-label={t("follow_stat")}
        >
          <option value="">{t("no_stat")}</option>
          {FOCUS_METRICS.map((m) => (
            <option key={m} value={m}>
              {focusLabel(m, lang)[0]}
            </option>
          ))}
        </select>
      </h2>
      {metric && (
        <>
          <p className="muted small fb-note">{focusLabel(metric, lang)[1]}</p>
          {rows.length ? (
            <ol className="board">
              {rows.map((r) => (
                <li key={r.player_id} className={`${fan.squad.includes(r.player_id) ? "mine" : ""}${r.match_id === stage ? " on-stage" : ""}`}>
                  <button className="lb-row" onClick={() => setStage(r.match_id)} title={t("watch")}>
                    <span className="lb-rank">{r.rank}</span>
                    <span className="lb-name">
                      <i className="dot" style={{ background: clubs[r.club]?.primary }} />
                      {r.name}
                    </span>
                    <span className="sq-club">{r.club}</span>
                    <span className="lb-val">
                      {r.value.toFixed(board!.digits)}
                      {board!.unit && <small> {board!.unit}</small>}
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          ) : (
            <p className="muted small">{t("leaders_empty")}</p>
          )}
        </>
      )}
    </section>
  );
}
