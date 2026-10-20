"""Newsroom evaluation suite (run locally or in CI; results are logged to Microsoft Foundry).

    python -m footballytics.evals.run --matchday 11 --items 24

1. Production quality (deterministic): runs the real newsroom workflow on moments from a simulated
   matchday. The simulation is paused at each moment, so agents see the live state exactly as in
   production. Measures verification rate, first-pass and final claim accuracy, numbers in the
   multilingual renditions that cannot be traced to evidence, language coverage, labels and latency.
2. Planted errors (adversarial): immediately after each item is produced, one claim is corrupted
   and a fabricated statistic is planted in the prose. Measures how often the Verifier catches each,
   and how often it raises a false alarm on the untouched item.
3. AI judges (Azure AI Evaluation SDK): groundedness, relevance, coherence and fluency of the
   explanations, plus content safety, logged to the Foundry project as an evaluation run.
4. Gates: thresholds that fail the run (non-zero exit) when quality regresses.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

from ..agents.audit import unsupported_numbers
from ..agents.clients import is_configured
from ..agents.newsroom import NewsTask, Newsroom, review
from ..agents.schemas import Claim, Insight
from ..hub import LiveHub
from ..intel import tools

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "evals" / "results"
QUOTAS = {"goal": 4, "wonder_strike": 1, "big_chance": 3, "great_save": 3, "momentum_swing": 3, "control_shift": 2,
          "line_breaking_pass": 2, "pressing_shift": 2, "high_turnover": 2, "penalty_awarded": 1, "red_card": 1,
          "milestone": 2, "tempo_shift": 1}
LANGS = ["en", "es", "ar"]
FABRICATION = " It was his 47th successful dribble of the season, at an 83.6% success rate."
GATES = {
    "verified_rate": (">=", 0.90),
    "final_claim_accuracy": (">=", 0.98),
    "planted_claim_catch_rate": (">=", 0.95),
    "planted_fabrication_catch_rate": (">=", 0.90),
    "control_false_alarm_rate": ("<=", 0.10),
    "renditions_with_untraceable_numbers": ("<=", 0.15),
    "language_coverage": (">=", 0.95),
    "latency_p95_s": ("<=", 30.0),
    "groundedness": (">=", 3.5),
    "relevance": (">=", 3.5),
    "coherence": (">=", 3.5),
}


# ----------------------------------------------------------------------------- planted errors
def plant_errors(item: dict) -> dict | None:
    """Corrupt a verified item two ways and run the Verifier's checks on each (state is still live)."""
    if item["status"] not in ("verified", "corrected"):
        return None
    good = [c for c in item["claims"] if c.get("ok")]
    task = NewsTask(item["moment"], item["context"], ["en"])
    ins = item["insight"]
    base = Insight(headline=ins["headline"], why_it_matters=ins["why_it_matters"], tactical_angle=ins.get("tactical_angle"),
                   claims=[Claim(subject_id=c["subject_id"], metric=c["metric"], value=float(c["value"])) for c in good])
    _, control = review(task, base)
    out = {"control_false_alarm": bool(control), "claim_caught": None}
    if base.claims:
        wrong = base.model_copy(deep=True)
        v = wrong.claims[0].value
        wrong.claims[0].value = round(v * 1.5 + (3 if abs(v) < 2 else 0), 3)  # well outside any tolerance
        _, problems = review(task, wrong)
        out["claim_caught"] = bool(problems)
    fab = base.model_copy(deep=True)
    fab.why_it_matters += FABRICATION
    _, problems = review(task, fab)
    out["fabrication_caught"] = bool(problems)
    return out


def fabrication_caught_offline(item: dict) -> bool:
    ins = item["insight"]
    fab = ins["why_it_matters"] + FABRICATION
    verified = [c.get("actual") for c in item["claims"] if c.get("ok")]
    return bool(unsupported_numbers([ins["headline"], fab, ins.get("tactical_angle") or ""],
                                    [item["context"], verified], always_ok=[item["moment"]["minute"]]))


# ----------------------------------------------------------------------------- collection
async def collect(matchday: int, max_items: int, max_minutes: int) -> list[dict]:
    hub = LiveHub()
    hub.load_matchday(matchday)
    tools.bind(hub)
    newsroom = Newsroom(min_importance=40, max_concurrency=4)
    counts: Counter[str] = Counter()
    items: list[dict] = []
    for _ in range(max_minutes * 600):
        pending = []
        for m in hub.matches.values():
            if m.done:
                continue
            _, _, moments, _ = m.step()
            for mo in moments:
                hub.moment_log.append(mo)
                if (mo.importance >= 40 and counts[mo.kind] < QUOTAS.get(mo.kind, 0)
                        and len(items) + len(pending) < max_items):
                    counts[mo.kind] += 1
                    pending.append(mo)
        if pending:
            batch = await asyncio.gather(*(newsroom.process(mo, LANGS, include_context=True) for mo in pending))
            for it in batch:
                it["planted"] = plant_errors(it)  # same instant: live state unchanged
                items.append(it)
                print(f"  [{len(items):>2}/{max_items}] {it['kind']:<18} {it['minute']:>3}' {it['status']:<18} "
                      f"{it['latency_ms'] / 1000:5.1f}s  {it['insight']['headline'][:60]}", flush=True)
        if len(items) >= max_items:
            break
    return items


# ----------------------------------------------------------------------------- metrics
def deterministic(items: list[dict]) -> tuple[dict, list[dict]]:
    rows = []
    for it in items:
        claims = it["claims"]
        first = next((t for t in it["trace"] if t["agent"] == "verifier" and t.get("attempt") == 1), None)
        rend = it["renditions"]
        evidence = [it["context"], it["insight"], [c.get("actual") for c in claims if c.get("ok")]]
        untraceable = unsupported_numbers([" ".join((r["fan"], r["analyst"], r["kids"], r["audio"])) for r in rend.values()],
                                          evidence, always_ok=[it["minute"]])
        rows.append({
            "moment_id": it["moment_id"], "kind": it["kind"], "minute": it["minute"], "status": it["status"],
            "claims": len(claims), "claims_ok": sum(1 for c in claims if c.get("ok")),
            "first_pass_clean": bool(first and not first.get("issues")),
            "rewrites": sum(1 for t in it["trace"] if t["agent"] == "analyst") - 1,
            "languages": sorted(rend), "untraceable_numbers": untraceable,
            "labels_ok": all(len(r["label"]) <= 31 for r in rend.values()),
            "latency_s": it["latency_ms"] / 1000, "headline": it["insight"]["headline"],
        })
    n = max(1, len(rows))
    lat = sorted(r["latency_s"] for r in rows) or [0.0]
    verified = [r for r in rows if r["status"] in ("verified", "corrected")]
    planted = [it["planted"] for it in items if it.get("planted")]
    claim_tests = [p["claim_caught"] for p in planted if p["claim_caught"] is not None]
    total_claims = sum(r["claims"] for r in verified)
    summary = {
        "items": len(rows),
        "kinds": dict(Counter(r["kind"] for r in rows)),
        "verified_rate": len(verified) / n,
        "first_pass_clean_rate": sum(r["first_pass_clean"] for r in rows) / n,
        "rewrites_per_item": sum(r["rewrites"] for r in rows) / n,
        "final_claim_accuracy": (sum(r["claims_ok"] for r in verified) / total_claims) if total_claims else 1.0,
        "renditions_with_untraceable_numbers": sum(1 for r in rows if r["untraceable_numbers"]) / n,
        "language_coverage": sum(len(set(r["languages"]) & set(LANGS)) for r in rows) / (n * len(LANGS)),
        "labels_within_limit": sum(r["labels_ok"] for r in rows) / n,
        "latency_p50_s": statistics.median(lat),
        "latency_p95_s": lat[min(len(lat) - 1, int(0.95 * len(lat)))],
        "planted_claim_catch_rate": (sum(claim_tests) / len(claim_tests)) if claim_tests else None,
        "planted_fabrication_catch_rate": (sum(p["fabrication_caught"] for p in planted) / len(planted)) if planted else None,
        "control_false_alarm_rate": (sum(p["control_false_alarm"] for p in planted) / len(planted)) if planted else None,
        "planted_tests": len(planted),
    }
    return summary, rows


def ai_judges(items: list[dict], out_dir: Path, name: str) -> dict:
    """Azure AI Evaluation SDK judges; results are logged to the Foundry project when possible."""
    from azure.ai.evaluation import (
        AzureOpenAIModelConfiguration,
        CoherenceEvaluator,
        ContentSafetyEvaluator,
        FluencyEvaluator,
        GroundednessEvaluator,
        RelevanceEvaluator,
        evaluate,
    )
    from azure.identity import AzureCliCredential, ManagedIdentityCredential

    cred = (ManagedIdentityCredential(client_id=os.environ["AZURE_CLIENT_ID"]) if os.getenv("AZURE_CLIENT_ID")
            else AzureCliCredential())
    # No api_key: the SDK authenticates to Azure OpenAI with Entra ID (DefaultAzureCredential) - keyless.
    model = AzureOpenAIModelConfiguration(azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                                          azure_deployment=os.getenv("JUDGE_MODEL", os.getenv("MODEL_FAST", "gpt-4.1-mini")),
                                          api_version="2025-04-01-preview")
    data = out_dir / f"{name}.judge-input.jsonl"
    with data.open("w", encoding="utf-8") as f:
        for it in items:
            ctx = {"moment": it["context"]["moment"], "evidence": it["context"]["evidence"],
                   "match": it["context"]["match"], "players": it["context"]["players"]}
            ins = it["insight"]
            f.write(json.dumps({
                "query": f"Explain why this {it['kind'].replace('_', ' ')} in minute {it['minute']} matters.",
                "context": json.dumps(ctx, default=str),
                "response": " ".join(x for x in (ins["headline"] + ".", ins["why_it_matters"], ins.get("tactical_angle") or "") if x),
            }, ensure_ascii=False) + "\n")
    evaluators = {"groundedness": GroundednessEvaluator(model), "relevance": RelevanceEvaluator(model),
                  "coherence": CoherenceEvaluator(model), "fluency": FluencyEvaluator(model)}
    project = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    if os.getenv("EVAL_CONTENT_SAFETY", "1") == "1" and project:
        evaluators["content_safety"] = ContentSafetyEvaluator(credential=cred, azure_ai_project=project)
    mapping = {"column_mapping": {"query": "${data.query}", "context": "${data.context}", "response": "${data.response}"}}
    kwargs = dict(data=str(data), evaluators=evaluators, evaluator_config={"default": mapping},
                  evaluation_name=name, output_path=str(out_dir / f"{name}.judges.json"))
    try:
        result = evaluate(**kwargs, azure_ai_project=project) if project else evaluate(**kwargs)
    except Exception as exc:  # e.g. project logging or safety service unavailable: still score locally
        print(f"  (Foundry logging/content safety unavailable: {type(exc).__name__}: {str(exc)[:160]}; scoring locally)")
        evaluators.pop("content_safety", None)
        kwargs["evaluators"] = evaluators
        result = evaluate(**kwargs)
    metrics = result.get("metrics", {})
    pick = lambda key: next((v for k, v in metrics.items() if k.endswith(f"{key}.{key}") or k == f"{key}.{key}"), None)  # noqa: E731
    out = {"groundedness": pick("groundedness"), "relevance": pick("relevance"), "coherence": pick("coherence"),
           "fluency": pick("fluency"), "foundry_url": result.get("studio_url")}
    safety = {k.split(".", 1)[1]: v for k, v in metrics.items() if k.startswith("content_safety.") and "defect_rate" in k}
    if safety:
        out["content_safety_defect_rates"] = safety
    out["all_metrics"] = metrics
    return out


def gate(summary: dict) -> list[dict]:
    results = []
    for metric, (op, threshold) in GATES.items():
        value = summary.get(metric)
        if value is None:
            results.append({"metric": metric, "value": None, "threshold": f"{op} {threshold}", "pass": None})
            continue
        ok = value >= threshold if op == ">=" else value <= threshold
        results.append({"metric": metric, "value": round(value, 3), "threshold": f"{op} {threshold}", "pass": ok})
    return results


def report_markdown(summary: dict, gates: list[dict], rows: list[dict], meta: dict) -> str:
    pct = lambda v: "–" if v is None else f"{v:.0%}"  # noqa: E731
    num = lambda v: "–" if v is None else f"{v:.2f}"  # noqa: E731
    lines = [
        "# Newsroom evaluation",
        "",
        f"Run `{meta['name']}` on {meta['date']}: {summary['items']} moments from simulated matchday {meta['matchday']}, "
        f"rendered in {', '.join(LANGS)}. Analyst `{meta['analyst_model']}`, Host `{meta['host_model']}`, "
        f"judge `{meta['judge_model']}`.",
        "",
        "## Quality gates",
        "",
        "| Metric | Value | Gate | |",
        "|---|---|---|---|",
    ]
    for g in gates:
        v = g["value"]
        shown = "–" if v is None else (f"{v:.2f}" if g["metric"] in ("groundedness", "relevance", "coherence", "latency_p95_s")
                                       else f"{v:.0%}")
        lines.append(f"| {g['metric'].replace('_', ' ')} | {shown} | {g['threshold']} | "
                     f"{'✅' if g['pass'] else ('–' if g['pass'] is None else '❌')} |")
    lines += [
        "",
        "## Details",
        "",
        f"- First-pass clean (no Verifier corrections needed): {pct(summary['first_pass_clean_rate'])}; "
        f"rewrites per item: {summary['rewrites_per_item']:.2f}",
        f"- Planted-error tests: {summary['planted_tests']} items; corrupted claims caught "
        f"{pct(summary['planted_claim_catch_rate'])}, fabricated statistics caught "
        f"{pct(summary['planted_fabrication_catch_rate'])}, false alarms on untouched items "
        f"{pct(summary['control_false_alarm_rate'])}",
        f"- Latency p50 {summary['latency_p50_s']:.1f}s, p95 {summary['latency_p95_s']:.1f}s (Analyst + Verifier + "
        f"{len(LANGS)}-language Host, end to end)",
        f"- AI judges (1-5): groundedness {num(summary.get('groundedness'))}, relevance {num(summary.get('relevance'))}, "
        f"coherence {num(summary.get('coherence'))}, fluency {num(summary.get('fluency'))}",
    ]
    if summary.get("content_safety_defect_rates"):
        lines.append(f"- Content safety defect rates: {summary['content_safety_defect_rates']}")
    if summary.get("foundry_url"):
        lines.append(f"- Foundry evaluation run: {summary['foundry_url']}")
    lines += ["", "## Items", "", "| Kind | Min | Status | Claims ok | Untraceable numbers | Latency | Headline |",
              "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['kind']} | {r['minute']} | {r['status']} | {r['claims_ok']}/{r['claims']} | "
                     f"{', '.join(r['untraceable_numbers']) or '–'} | {r['latency_s']:.1f}s | {r['headline']} |")
    return "\n".join(lines) + "\n"


async def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate the Footballytics agent newsroom")
    ap.add_argument("--matchday", type=int, default=11)
    ap.add_argument("--items", type=int, default=24)
    ap.add_argument("--max-minutes", type=int, default=95)
    ap.add_argument("--no-judges", action="store_true", help="skip the Azure AI Evaluation judges")
    ap.add_argument("--no-gate", action="store_true", help="always exit 0")
    ap.add_argument("--reuse-items", help="skip collection and re-score a saved *.items.json")
    args = ap.parse_args()
    if not is_configured():
        print("FOUNDRY_PROJECT_ENDPOINT is not set; cannot run the newsroom.")
        return 2
    RESULTS.mkdir(parents=True, exist_ok=True)
    name = f"newsroom-md{args.matchday}-{time.strftime('%Y%m%d-%H%M%S')}"
    t0 = time.perf_counter()
    if args.reuse_items:
        items = json.loads(Path(args.reuse_items).read_text(encoding="utf-8"))
        print(f"Re-scoring {len(items)} saved items from {args.reuse_items}")
        for it in items:  # the fabrication test only needs the number audit, so it can be re-run offline
            if it.get("planted"):
                it["planted"]["fabrication_caught"] = fabrication_caught_offline(it)
    else:
        print(f"Collecting {args.items} moments from matchday {args.matchday} ...")
        items = await collect(args.matchday, args.items, args.max_minutes)
        saved = RESULTS / f"{name}.items.json"
        saved.write_text(json.dumps(items, default=str, ensure_ascii=False), encoding="utf-8")
        print(f"Saved collected items to {saved}")
    summary, rows = deterministic(items)
    if not args.no_judges:
        print("Running AI judges (Azure AI Evaluation SDK) ...")
        judged = ai_judges(items, RESULTS, name)
        summary.update({k: v for k, v in judged.items() if k != "all_metrics"})
    gates = gate(summary)
    meta = {"name": name, "date": time.strftime("%Y-%m-%d %H:%M"), "matchday": args.matchday,
            "analyst_model": os.getenv("MODEL_REASONING", "gpt-5-mini"), "host_model": os.getenv("MODEL_FAST", "gpt-4.1-mini"),
            "judge_model": os.getenv("JUDGE_MODEL", os.getenv("MODEL_FAST", "gpt-4.1-mini")),
            "duration_s": round(time.perf_counter() - t0, 1)}
    out = {"meta": meta, "summary": summary, "gates": gates, "items": rows}
    (RESULTS / f"{name}.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    (RESULTS / "latest.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    md = report_markdown(summary, gates, rows, meta)
    (ROOT.parent / "docs" / "EVALUATION.md").write_text(md, encoding="utf-8")
    seed = Path(__file__).resolve().parents[1] / "seed" / "evals_latest.json"
    seed.write_text(json.dumps({"meta": meta, "summary": summary, "gates": gates}, default=str), encoding="utf-8")
    print("\n" + "\n".join(f"{'PASS' if g['pass'] else ('n/a ' if g['pass'] is None else 'FAIL')}  {g['metric']:<36} "
                           f"{g['value']}  (gate {g['threshold']})" for g in gates))
    failed = [g for g in gates if g["pass"] is False]
    print(f"\n{len(gates) - len(failed)}/{len(gates)} gates passed; report: docs/EVALUATION.md")
    return 1 if failed and not args.no_gate else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
