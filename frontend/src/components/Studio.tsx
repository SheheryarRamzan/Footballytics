import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { usePoll } from "../hooks";
import { useStore } from "../store";
import type { VerifierItem, VerifierResult } from "../types";

type Draft = { headline: string; why: string; tactical: string; values: string[] };

const toDraft = (it: VerifierItem): Draft => ({
  headline: it.insight.headline,
  why: it.insight.why_it_matters,
  tactical: it.insight.tactical_angle ?? "",
  values: it.claims.map((c) => String(c.value)),
});

/** Inflate a stat by half, keeping its precision (0.34 -> 0.51, 212 -> 318). */
const inflate = (v: string) => {
  const n = Number(v);
  const decimals = (v.split(".")[1] ?? "").length;
  return (n === 0 ? 1 : n * 1.5).toFixed(decimals);
};

/** Try a wrong number: edit a published item and run the same Verifier that gates every broadcast. */
function TryWrongNumber() {
  const [items, setItems] = useState<VerifierItem[] | null>(null);
  const [pick, setPick] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [result, setResult] = useState<VerifierResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .verifierItems()
        .then((l) => alive && setItems(l))
        .catch(() => alive && setItems((prev) => prev ?? []));
    load();
    const t = setInterval(load, 20_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  useEffect(() => {
    if (location.hash === "#try-a-wrong-number") ref.current?.scrollIntoView({ block: "start" });
  }, []);
  // Pin the item being edited, so a newer item never replaces it mid-edit (re-pick only if it expired).
  useEffect(() => {
    if (items?.length && !items.some((i) => i.item_id === pick)) {
      setPick((items.find((i) => i.claims.length) ?? items[0]).item_id);
    }
  }, [items, pick]);

  const item = items?.find((i) => i.item_id === pick);
  useEffect(() => {
    if (item) setDraft(toDraft(item));
    setResult(null);
    setError(null);
  }, [item?.item_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (d: Draft) => {
    if (!item) return;
    setDraft(d);
    setBusy(true);
    setError(null);
    try {
      setResult(
        await api.verifierTry({
          item_id: item.item_id,
          headline: d.headline,
          why_it_matters: d.why,
          tactical_angle: d.tactical || null,
          claims: item.claims.map((c, i) => ({ subject_id: c.subject_id, metric: c.metric, value: Number(d.values[i]) })),
        }),
      );
    } catch (e) {
      setError(String(e).includes("404") ? "That item has expired: pick a newer one." : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel studio-try" id="try-a-wrong-number" ref={ref}>
      <h2>
        Try a wrong number
        <span className="badge verified">same Verifier as on air</span>
      </h2>
      <p className="muted small">
        Change any number in a published item, or add one, and run the Verifier that gates every broadcast. It checks
        claims against the values it read when the item was published, and every number in the text against the
        evidence. Nothing you type goes on air.
      </p>
      {!items && <p className="muted">Loading…</p>}
      {items && !items.length && (
        <p className="muted">
          Waiting for the first verified item. The newsroom writes one for each big moment while someone is watching,
          usually within a minute or two.
        </p>
      )}
      {item && draft && (
        <div className="try-grid">
          <div className="try-form">
            <label>
              Published item
              <select value={item.item_id} onChange={(e) => setPick(e.target.value)}>
                {items!.map((i) => (
                  <option key={i.item_id} value={i.item_id}>
                    {i.match_id.replace(/^md\d+-/, "")} {i.minute}' · {i.insight.headline}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Headline
              <input value={draft.headline} onChange={(e) => setDraft({ ...draft, headline: e.target.value })} />
            </label>
            <label>
              Why it matters
              <textarea rows={3} value={draft.why} onChange={(e) => setDraft({ ...draft, why: e.target.value })} />
            </label>
            {item.claims.length > 0 && (
              <table className="claims try-claims">
                <thead>
                  <tr>
                    <th>Claim</th>
                    <th>Value</th>
                    <th className="muted">Published</th>
                  </tr>
                </thead>
                <tbody>
                  {item.claims.map((c, i) => (
                    <tr key={i}>
                      <td>
                        {c.name ?? c.subject_id} · {c.metric}
                      </td>
                      <td>
                        <input
                          type="number"
                          step="any"
                          aria-label={`${c.name ?? c.subject_id} ${c.metric}`}
                          value={draft.values[i]}
                          onChange={(e) =>
                            setDraft({ ...draft, values: draft.values.map((v, j) => (j === i ? e.target.value : v)) })
                          }
                        />
                      </td>
                      <td className="muted">{c.value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="try-actions">
              {item.claims.length > 0 && (
                <button className="btn small ghost" disabled={busy} onClick={() => run({ ...draft, values: [inflate(draft.values[0]), ...draft.values.slice(1)] })}>
                  Inflate a stat by 50%
                </button>
              )}
              <button
                className="btn small ghost"
                disabled={busy}
                onClick={() => run(draft.why.includes(item.invent) ? draft : { ...draft, why: `${draft.why.trim()} ${item.invent}` })}
              >
                Invent a number
              </button>
              <button className="btn small ghost" disabled={busy} onClick={() => run(toDraft(item))}>
                Reset to published
              </button>
              <button className="btn small" disabled={busy} onClick={() => run(draft)}>
                {busy ? "Checking…" : "Run the Verifier"}
              </button>
            </div>
          </div>
          <div className="try-result" aria-live="polite">
            {error && <p className="error">{error}</p>}
            {!result && !error && (
              <p className="muted">Edit a number, or use a button on the left, then run the Verifier.</p>
            )}
            {result && (
              <>
                <div className={`try-verdict ${result.verdict}`}>
                  {result.verdict === "rejected" ? "✗ Rejected by the Verifier" : "✓ Passed the Verifier"}
                </div>
                {result.checks.length > 0 && (
                  <table className="claims">
                    <tbody>
                      {result.checks.map((c, i) => (
                        <tr key={i}>
                          <td>{c.ok ? "✓" : "✗"}</td>
                          <td>
                            {c.name ?? c.subject_id} · {c.metric}
                          </td>
                          <td>{c.value}</td>
                          <td className="muted">
                            {c.actual == null ? c.reason : `true value ${c.actual} (±${c.tolerance})`}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {result.unsupported_numbers.length > 0 && (
                  <p>
                    Numbers in the text with no evidence:{" "}
                    {result.unsupported_numbers.map((n) => (
                      <span key={n} className="num-chip">{n}</span>
                    ))}
                  </p>
                )}
                {result.problems.length > 0 && (
                  <>
                    <h3>Feedback sent to the Analyst</h3>
                    <div className="try-feedback">{result.problems.join("\n")}</div>
                  </>
                )}
                <p className="muted small">{result.next}</p>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

/** Producer console: the agent newsroom's work, machine-readable overlay cues, health and controls. */
function Quality() {
  const ev = usePoll(() => fetch("/api/evals").then((r) => (r.ok ? r.json() : null)), 60_000, []);
  if (!ev) return null;
  const s = ev.summary;
  const pct = (v?: number | null) => (v == null ? "–" : `${Math.round(v * 100)}%`);
  const passed = ev.gates.filter((g: any) => g.pass).length;
  const fa = s.false_alarms ? (Object.values(s.false_alarms) as { flagged: number; n: number }[]) : null;
  const alarms = fa ? { flagged: fa.reduce((a, x) => a + x.flagged, 0), n: fa.reduce((a, x) => a + x.n, 0) } : null;
  return (
    <section className="panel studio-quality">
      <h2>
        Quality gates · automated evaluation
        <span className={`badge ${passed === ev.gates.length ? "verified" : "pending"}`}>
          {passed}/{ev.gates.length} passed
        </span>
      </h2>
      <div className="kpis">
        {s.claims_checked != null ? (
          <div><b>{s.claims_ok}/{s.claims_checked}</b><span>published claims match live data</span></div>
        ) : (
          <div><b>{pct(s.final_claim_accuracy)}</b><span>claims accurate on air</span></div>
        )}
        {s.planted_total_tests != null ? (
          <div><b>{s.planted_total_caught}/{s.planted_total_tests}</b><span>planted errors caught ({Object.keys(s.planted ?? {}).length} kinds)</span></div>
        ) : (
          <div><b>{pct(s.planted_claim_catch_rate)}</b><span>planted wrong stats caught</span></div>
        )}
        {alarms ? (
          <div><b>{alarms.flagged}/{alarms.n}</b><span>false alarms on correct items</span></div>
        ) : (
          <div><b>{pct(s.planted_fabrication_catch_rate)}</b><span>invented stats caught</span></div>
        )}
        <div><b>{s.groundedness?.toFixed(2) ?? "–"}</b><span>groundedness (1-5, AI judge)</span></div>
        <div><b>{s.coherence?.toFixed(2) ?? "–"}</b><span>coherence (1-5)</span></div>
        <div><b>{pct(s.content_safety_defect_rates ? Math.max(...Object.values(s.content_safety_defect_rates as Record<string, number>)) : null)}</b><span>content-safety defects</span></div>
      </div>
      <p className="muted small">
        {ev.meta.name}: {s.items} moments, {pct(s.language_coverage)} language coverage, p95 {s.latency_p95_s?.toFixed(1)}s
        {s.planted_total_ci95 ? `; planted-error catch rate 95% CI ${pct(s.planted_total_ci95[0])}–${pct(s.planted_total_ci95[1])}` : ""}.{" "}
        {s.foundry_url && (
          <a href={s.foundry_url} target="_blank" rel="noreferrer">Open the run in Microsoft Foundry →</a>
        )}
      </p>
    </section>
  );
}

/** Auto-eventing: players, ball, passes and speeds recovered from broadcast video, scored against the answer key. */
function AutoEventing() {
  const ae = usePoll(() => fetch("/api/autoevent").then((r) => (r.ok ? r.json() : null)), 120_000, []);
  if (!ae) return null;
  const m = ae.metrics;
  const pct = (v?: number | null) => (v == null ? "–" : `${Math.round(v * 100)}%`);
  const num = (v?: number | null, d = 1) => (v == null ? "–" : v.toFixed(d));
  const p = ae.passes;
  return (
    <section className="panel studio-ae">
      <h2>
        Auto-eventing · broadcast video → events
        <span className="badge verified">scored vs answer key</span>
      </h2>
      <div className="ae-grid">
        <img src="/auto-eventing.jpg" alt="Annotated broadcast frame: detected players by team, the tracked ball and a pitch minimap" />
        <div>
          <div className="kpis">
            <div><b>{p.attempts.tp}/{p.attempts.true}</b><span>pass attempts found</span></div>
            <div><b>{pct(p.outcome_correct)}</b><span>completed vs intercepted right</span></div>
            <div><b>{num(p.speed_mae_kmh)}</b><span>pass speed error, km/h</span></div>
            <div><b>{pct(m.detection.recall)}</b><span>players found (precision {pct(m.detection.precision)})</span></div>
            <div><b>{num(m.localisation.mean_m, 2)} m</b><span>position error</span></div>
            <div><b>{num(m.player_speed.top_speed_mae_kmh)}</b><span>top speed error, km/h</span></div>
          </div>
          <p className="muted small">
            {ae.meta.seconds}s of {ae.meta.home} v {ae.meta.away} rendered by our 3D broadcast renderer; {ae.meta.detector}
            {" "}finds players (plus a zoomed pass around the ball), a classical detector and path search follow the ball, and
            passes, interceptions and speeds come from the tracks alone. Ball within 2 m {pct(m.ball.within_2m_share)}{" "}
            of the time; team colours {pct(m.teams.accuracy)} correct.
          </p>
        </div>
      </div>
    </section>
  );
}

export function Studio() {
  const items = useStore((s) => s.items);
  const health = usePoll(() => api.health(), 3000, []);
  const [selected, setSelected] = useState<string | null>(null);
  const list = Object.values(items).sort((a, b) => b.item_id.localeCompare(a.item_id)).slice(0, 40);
  const sel = selected ? items[selected] : list[0];
  const agents = health?.agents;
  const locked = !!health?.controls_locked;
  // Items published before this page opened (the live stream only carries new ones).
  useEffect(() => {
    api
      .broadcast()
      .then((past) =>
        useStore.setState((st) => ({ items: { ...Object.fromEntries(past.map((it) => [it.moment_id, it])), ...st.items } })),
      )
      .catch(() => {});
  }, []);
  return (
    <div className="studio">
      <section className="panel studio-stats">
        <h2>Newsroom</h2>
        <div className="kpis">
          <div><b>{agents?.items ?? 0}</b><span>verified items</span></div>
          <div><b>{agents?.by_status?.corrected ?? 0}</b><span>corrected by Verifier</span></div>
          <div><b>{agents?.latency_p50_ms ? (agents.latency_p50_ms / 1000).toFixed(1) + "s" : "–"}</b><span>p50 latency</span></div>
          <div><b>{agents?.latency_p95_ms ? (agents.latency_p95_ms / 1000).toFixed(1) + "s" : "–"}</b><span>p95 latency</span></div>
          <div><b>{health?.viewers ?? 0}</b><span>viewers</span></div>
          <div><b>{(agents?.languages ?? []).join(" · ") || "en"}</b><span>languages on air</span></div>
        </div>
        <div className="controls">
          <span className="muted">Sim speed ×{health?.speed}</span>
          {[2, 4, 8].map((s) => (
            <button key={s} className="btn small ghost" disabled={locked} onClick={() => api.speed(s)}>×{s}</button>
          ))}
          <button className="btn small ghost" disabled={locked} onClick={() => api.restart(health?.matchday ?? 9, health?.speed ?? 4)}>
            Restart matchday
          </button>
          {locked && (
            <span className="muted small locked-note">
              🔒 Locked on the public demo: these change the live matchday for everyone watching.
            </span>
          )}
          <code className="mcp" title="Connect GitHub Copilot, Claude or any MCP client">MCP: {location.origin}/mcp-server/mcp</code>
        </div>
      </section>
      <TryWrongNumber />
      <Quality />
      <AutoEventing />
      <section className="panel studio-list">
        <h2>Broadcast items</h2>
        <ul>
          {list.map((it) => (
            <li key={it.item_id}>
              <button className={`si-row${sel?.item_id === it.item_id ? " on" : ""}`} onClick={() => setSelected(it.moment_id)}>
                <span className={`badge ${it.status}`}>{it.status}</span>
                <b>{it.match_id.replace(/^md\d+-/, "")} {it.minute}'</b>
                <span>{it.insight.headline}</span>
                <span className="muted">{(it.latency_ms / 1000).toFixed(1)}s</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
      <section className="panel studio-detail">
        <h2>Agent trace</h2>
        {!sel && <p className="muted">Waiting for the first verified item…</p>}
        {sel && (
          <>
            <ol className="trace">
              {sel.trace.map((s, i) => (
                <li key={i} className={`step ${s.agent}`}>
                  <b>{s.agent}</b>
                  {s.attempt ? <small> attempt {s.attempt}</small> : null}
                  <span className="ms">{s.ms} ms</span>
                  <div>{s.note}</div>
                  {s.issues?.map((x) => (
                    <div key={x} className="issue">⚠ {x}</div>
                  ))}
                </li>
              ))}
            </ol>
            <h3>Verified claims</h3>
            <table className="claims">
              <tbody>
                {sel.claims.map((c, i) => (
                  <tr key={i}>
                    <td>{c.ok ? "✓" : "✗"}</td>
                    <td>{c.subject_id}</td>
                    <td>{c.metric}</td>
                    <td>{c.value}</td>
                    <td className="muted">live {String(c.actual)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3>Overlay cue (machine-readable)</h3>
            <pre className="cue">{JSON.stringify(sel.overlay, null, 2)}</pre>
            <h3>Renditions</h3>
            {Object.entries(sel.renditions).map(([lang, r]) => (
              <div key={lang} className="rend" dir={lang === "ar" || lang === "ur" ? "rtl" : "ltr"}>
                <b>{lang}</b> {r.analyst}
                <div className="muted">🔊 {r.audio}</div>
              </div>
            ))}
          </>
        )}
      </section>
    </div>
  );
}
