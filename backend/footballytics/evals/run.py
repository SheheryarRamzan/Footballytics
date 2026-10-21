"""Newsroom evaluation suite (run locally or in CI; results are logged to Microsoft Foundry).

    python -m footballytics.evals.run --matchday 11 --items 24

1. Production quality (deterministic): runs the real newsroom workflow on moments from a simulated
   matchday. The simulation is paused at each moment, so agents see the live state exactly as in
   production. Measures verification rate, first-pass and final claim accuracy, numbers in the
   multilingual renditions that cannot be traced to evidence, language coverage, labels and latency.
2. Planted errors (adversarial): immediately after each item is produced (the live state unchanged), errors are
   planted and the Verifier's checks run on each: a claim inflated by 50%, a claim just outside its tolerance, the
   right number credited to the wrong player or team, the fixed fabricated sentence, a randomly drawn fabricated
   sentence (varied stats, units and phrasing), and a fabricated number in a translated rendition (in that
   language's digits). Controls measure false alarms: the untouched item, and a claim moved but kept inside its
   tolerance. Every rate is reported with its 95% confidence interval (Wilson), and the known blind spot (small
   whole numbers, exempt by design) is measured separately.
3. AI judges (Azure AI Evaluation SDK): groundedness, relevance, coherence and fluency of the
   explanations, plus content safety, logged to the Foundry project as an evaluation run.
4. Gates: thresholds that fail the run (non-zero exit) when quality regresses.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import random
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

from ..agents.audit import unsupported_numbers
from ..agents.clients import is_configured
from ..agents.newsroom import NewsTask, Newsroom, host_evidence, rendition_problems, review, scrub_rendition
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
# Drawn at random per item, so the auditor cannot be tuned to one sentence. Every number is above 11 (see below).
FABRICATIONS = [
    " It was his {a}th successful dribble of the season, at a {p}% success rate.",
    " He has now made {a} progressive carries since August.",
    " Their press has won the ball back {a} times in the final third this month.",
    " That strike left his boot at {s} km/h, the fastest of his career.",
    " He has covered {d} km in his last {b} matches.",
    " The keeper has saved {p}% of the shots on target he has faced this season.",
    " They have scored {a} goals from set pieces in {b} games.",
    " It was his {a}th touch inside the opposition box this season.",
    " The pass travelled {m} metres, the longest by any midfielder this season.",
    " His expected-goals tally for the season now stands at {x}.",
    " The side has won {p}% of its aerial duels since the break.",
    " He has completed {a} line-breaking passes in his last {b} appearances.",
]
# Whole numbers 0-11 are exempt from the number audit ("two defenders", "the 2nd goal"): this measures that gap.
SMALL_FABRICATION = " It was his 9th goal in his last 10 matches."
RENDITION_PLANTS = {
    "en": " It was his {n}th successful dribble of the season.",
    "es": " Fue su regate exitoso número {n} de la temporada.",
    "ar": " وكانت هذه مراوغته الناجحة رقم {n} هذا الموسم.",
}
ARABIC_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
GATES = {
    "verified_rate": (">=", 0.90),
    "final_claim_accuracy": (">=", 0.98),
    "planted_claim_catch_rate": (">=", 0.95),
    "planted_fabrication_catch_rate": (">=", 0.90),
    "control_false_alarm_rate": ("<=", 0.10),
    "near_miss_catch_rate": (">=", 0.95),
    "wrong_subject_catch_rate": (">=", 0.95),
    "varied_fabrication_catch_rate": (">=", 0.90),
    "rendition_number_catch_rate": (">=", 0.95),
    "tolerance_false_alarm_rate": ("<=", 0.10),
    "renditions_with_untraceable_numbers": ("<=", 0.02),
    "language_coverage": (">=", 0.95),
    "latency_p95_s": ("<=", 30.0),
    "groundedness": (">=", 3.5),
    "relevance": (">=", 3.5),
    "coherence": (">=", 3.5),
}


# ----------------------------------------------------------------------------- planted errors
def _rng(item: dict) -> random.Random:
    return random.Random(int(hashlib.sha1(item["moment_id"].encode()).hexdigest()[:8], 16))


def random_fabrication(rng: random.Random) -> str:
    return rng.choice(FABRICATIONS).format(
        a=rng.randint(23, 96), b=rng.randint(12, 30), p=f"{rng.uniform(51, 94.9):.1f}", s=f"{rng.uniform(87, 131.9):.1f}",
        d=f"{rng.uniform(41.2, 79.9):.1f}", m=rng.randint(38, 64), x=f"{rng.uniform(4.37, 9.81):.2f}")


def _set_claim(ins: Insight, i: int, **changes) -> Insight:
    out = ins.model_copy(deep=True)
    for k, v in changes.items():
        setattr(out.claims[i], k, v)
    return out


def plant_errors(item: dict) -> dict | None:
    """Plant errors in a verified item and run the Verifier's checks on each (the live state is unchanged)."""
    if item["status"] not in ("verified", "corrected"):
        return None
    rng = _rng(item)
    good = [c for c in item["claims"] if c.get("ok")]
    task = NewsTask(item["moment"], item["context"], ["en"])
    ins = item["insight"]
    base = Insight(headline=ins["headline"], why_it_matters=ins["why_it_matters"], tactical_angle=ins.get("tactical_angle"),
                   claims=[Claim(subject_id=c["subject_id"], metric=c["metric"], value=float(c["value"])) for c in good])
    checks, control = review(task, base)
    out = {"control_false_alarm": bool(control), "claim_caught": None, "near_miss_caught": None,
           "within_tolerance_false_alarm": None, "wrong_subject_caught": None}
    caught = lambda planted: bool(review(task, planted)[1])  # noqa: E731

    if base.claims:  # a claim inflated by 50%: far outside any tolerance
        v = base.claims[0].value
        out["claim_caught"] = caught(_set_claim(base, 0, value=round(v * 1.5 + (3 if abs(v) < 2 else 0), 3)))

    # just outside / just inside the tolerance the Verifier uses for that claim
    numeric = [(i, c) for i, c in enumerate(checks) if c.get("ok") and isinstance(c.get("actual"), int | float)
               and c.get("tolerance") is not None and i < len(base.claims)]
    if numeric:
        i, c = numeric[0]
        actual, tol = float(c["actual"]), float(c["tolerance"])
        outside = actual + 1 if actual.is_integer() and tol <= 0.5 else actual + 1.3 * tol + 1e-3
        out["near_miss_caught"] = caught(_set_claim(base, i, value=round(outside, 3)))
        out["within_tolerance_false_alarm"] = caught(_set_claim(base, i, value=round(actual + 0.5 * tol, 4)))

    # the right number credited to the wrong player or team
    owned = [(i, c) for i, c in enumerate(base.claims) if c.subject_id not in ("moment", task.moment["moment_id"])]
    if owned:
        i, c = owned[0]
        match_id = task.moment["match_id"]
        snap = tools.hub().match(match_id).proc.snapshot()
        teams, players = list(snap.get("teams", {})), list(snap.get("players", {}))
        pool = [t for t in teams if t != c.subject_id] if c.subject_id in teams else \
            [p for p in players if p != c.subject_id]
        rng.shuffle(pool)
        for cand in pool:
            r = tools.verify_claims(match_id, [{"subject_id": cand, "metric": c.metric, "value": c.value}])[0]
            if r.get("actual") is not None and not r["ok"]:
                out["wrong_subject_caught"] = caught(_set_claim(base, i, subject_id=cand))
                break

    fab = base.model_copy(deep=True)
    fab.why_it_matters += FABRICATION
    out["fabrication_caught"] = caught(fab)
    sentence = random_fabrication(rng)
    fab = base.model_copy(deep=True)
    fab.why_it_matters += sentence
    out["varied_fabrication_caught"], out["varied_fabrication"] = caught(fab), sentence.strip()
    small = base.model_copy(deep=True)
    small.why_it_matters += SMALL_FABRICATION
    out["small_number_fabrication_caught"] = caught(small)
    out.update(plant_in_renditions(item, rng))
    return out


def plant_in_renditions(item: dict, rng: random.Random | None = None) -> dict:
    """A fabricated number in each translated rendition (in that language's digits): caught, and removed?"""
    rng = rng or _rng(item)
    evidence = host_evidence(item["insight"], item["moment"])
    results = []
    for lang, r in item.get("renditions", {}).items():
        plant = RENDITION_PLANTS.get(lang)
        if not plant:
            continue
        n = str(rng.randint(23, 96))
        sentence = plant.format(n=n.translate(ARABIC_DIGITS) if lang == "ar" else n)
        planted = dict(r, fan=(r.get("fan") or "") + sentence)
        bad = rendition_problems({lang: planted}, evidence, item["minute"]).get(lang, [])
        cleaned = scrub_rendition(planted, bad) if bad else planted
        removed = sentence.strip() not in (cleaned.get("fan") or "")  # gone from what would air, not just unseen
        results.append({"language": lang, "caught": bool(bad), "removed": removed})
    return {"rendition_tests": results}


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
        evidence = host_evidence(it["insight"], it["moment"])  # what the Host was given
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
        "claims_checked": total_claims,
        "claims_ok": sum(r["claims_ok"] for r in verified),
    }
    summary.update(planted_summary(planted))
    return summary, rows


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    """95% confidence interval for k successes in n trials (Wilson score; honest at 0% and 100%)."""
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)]


PLANTED_TESTS = {  # key in each item's "planted" record -> (summary name, what was planted)
    "claim_caught": ("planted_claim", "a claim inflated by 50%"),
    "near_miss_caught": ("near_miss", "a claim just outside the Verifier's tolerance"),
    "wrong_subject_caught": ("wrong_subject", "the right number credited to the wrong player or team"),
    "fabrication_caught": ("fixed_fabrication", "the fixed fabricated sentence"),
    "varied_fabrication_caught": ("varied_fabrication", "a randomly drawn fabricated sentence"),
}


def planted_summary(planted: list[dict]) -> dict:
    tests = {}
    for key, (name, what) in PLANTED_TESTS.items():
        vals = [p[key] for p in planted if p.get(key) is not None]
        tests[name] = {"what": what, "caught": sum(vals), "n": len(vals)}
    rend = [t for p in planted for t in p.get("rendition_tests", [])]
    tests["rendition_number"] = {"what": "a fabricated number in a translated rendition (en, es, Arabic digits)",
                                 "caught": sum(t["caught"] for t in rend), "n": len(rend),
                                 "removed": sum(t["removed"] for t in rend)}
    for t in tests.values():
        t["rate"] = t["caught"] / t["n"] if t["n"] else None
        t["ci95"] = wilson(t["caught"], t["n"])
    alarms = {}
    for key, name, what in (("control_false_alarm", "untouched_item", "the untouched verified item"),
                            ("within_tolerance_false_alarm", "within_tolerance", "a claim moved but kept within tolerance")):
        vals = [p[key] for p in planted if p.get(key) is not None]
        k, n = sum(vals), len(vals)
        alarms[name] = {"what": what, "flagged": k, "n": n, "rate": k / n if n else None, "ci95": wilson(k, n)}
    small = [p["small_number_fabrication_caught"] for p in planted if p.get("small_number_fabrication_caught") is not None]
    blind = {"small_number_fabrication": {"what": "a fabricated sentence using only numbers 0-11 (exempt by design)",
                                          "caught": sum(small), "n": len(small),
                                          "rate": sum(small) / len(small) if small else None}}
    total_k = sum(t["caught"] for t in tests.values())
    total_n = sum(t["n"] for t in tests.values())
    return {
        "planted": tests, "false_alarms": alarms, "blind_spots": blind,
        "planted_total_caught": total_k, "planted_total_tests": total_n, "planted_total_ci95": wilson(total_k, total_n),
        "near_miss_catch_rate": tests["near_miss"]["rate"],
        "wrong_subject_catch_rate": tests["wrong_subject"]["rate"],
        "varied_fabrication_catch_rate": tests["varied_fabrication"]["rate"],
        "rendition_number_catch_rate": tests["rendition_number"]["rate"],
        "tolerance_false_alarm_rate": alarms["within_tolerance"]["rate"],
    }


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
        f"Run `{meta['name']}` on {meta['date']}: {summary['items']} moments from simulated matchday(s) {meta['matchday']}, "
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
        f"- Claims checked against live data: {summary['claims_ok']} of {summary['claims_checked']} published claims "
        f"matched (within the Verifier's tolerance: 5%, or 0.02 for small decimals / 0.5 for counts)",
        f"- Latency p50 {summary['latency_p50_s']:.1f}s, p95 {summary['latency_p95_s']:.1f}s (Analyst + Verifier + "
        f"{len(LANGS)}-language Host, end to end)",
        f"- AI judges (1-5): groundedness {num(summary.get('groundedness'))}, relevance {num(summary.get('relevance'))}, "
        f"coherence {num(summary.get('coherence'))}, fluency {num(summary.get('fluency'))}",
    ]
    if summary.get("content_safety_defect_rates"):
        lines.append(f"- Content safety defect rates: {summary['content_safety_defect_rates']}")
    if summary.get("foundry_url"):
        lines.append(f"- Foundry evaluation run: {summary['foundry_url']}")
    ci = lambda c: "–" if not c else f"{c[0]:.0%}–{c[1]:.0%}"  # noqa: E731
    if summary.get("planted"):
        lines += ["", "## Planted-error tests", "",
                  f"Every published item is attacked several ways at the moment it is produced. "
                  f"Overall: {summary['planted_total_caught']} of {summary['planted_total_tests']} planted errors caught "
                  f"(95% CI {ci(summary['planted_total_ci95'])}).", "",
                  "| Test | What is planted | Caught | 95% CI |", "|---|---|---|---|"]
        for name, t in summary["planted"].items():
            extra = f"; removed before air {t['removed']}/{t['n']}" if "removed" in t else ""
            lines.append(f"| {name.replace('_', ' ')} | {t['what']} | {t['caught']}/{t['n']}{extra} | {ci(t['ci95'])} |")
        lines += ["", "| False-alarm control | What is checked | Flagged | 95% CI |", "|---|---|---|---|"]
        for name, a in summary["false_alarms"].items():
            lines.append(f"| {name.replace('_', ' ')} | {a['what']} | {a['flagged']}/{a['n']} | {ci(a['ci95'])} |")
        b = summary["blind_spots"]["small_number_fabrication"]
        lines += ["", "## Known blind spots", "",
                  f"- **Small whole numbers.** The number audit lets 0-11 through, because prose uses them for counts and "
                  f"ordinals (\"two defenders\", \"the 2nd goal\"). A fabricated sentence using only such numbers was caught "
                  f"{b['caught']}/{b['n']} times.",
                  "- **Attribution in prose.** Structured claims are checked per player and team, but a correct number "
                  "credited to the wrong player in the prose itself is not.",
                  "- **Statements without numbers** (\"his first goal for the club\") are only assessed by the AI judge.",
                  f"- **The judge** is `{meta['judge_model']}`, the same model as the Host."]
    lines += ["", "## Items", "", "| Kind | Min | Status | Claims ok | Untraceable numbers | Latency | Headline |",
              "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['kind']} | {r['minute']} | {r['status']} | {r['claims_ok']}/{r['claims']} | "
                     f"{', '.join(r['untraceable_numbers']) or '–'} | {r['latency_s']:.1f}s | {r['headline']} |")
    return "\n".join(lines) + "\n"


async def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate the Footballytics agent newsroom")
    ap.add_argument("--matchday", type=int, default=11)
    ap.add_argument("--matchdays", help="comma list, e.g. 11,12,13: --items is split across them")
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
    mds = [int(x) for x in args.matchdays.split(",")] if args.matchdays else [args.matchday]
    md_label = f"{mds[0]}-{mds[-1]}" if len(mds) > 1 else str(mds[0])
    name = f"newsroom-md{md_label}-{time.strftime('%Y%m%d-%H%M%S')}"
    t0 = time.perf_counter()
    if args.reuse_items:
        items = json.loads(Path(args.reuse_items).read_text(encoding="utf-8"))
        print(f"Re-scoring {len(items)} saved items from {args.reuse_items}")
        for it in items:  # the fabrication test only needs the number audit, so it can be re-run offline
            if it.get("planted"):
                it["planted"]["fabrication_caught"] = fabrication_caught_offline(it)
                it["planted"].update(plant_in_renditions(it))
    else:
        items = []
        per = math.ceil(args.items / len(mds))
        for md in mds:
            print(f"Collecting {per} moments from matchday {md} ...")
            items += await collect(md, per, args.max_minutes)
        saved = RESULTS / f"{name}.items.json"
        saved.write_text(json.dumps(items, default=str, ensure_ascii=False), encoding="utf-8")
        print(f"Saved collected items to {saved}")
    summary, rows = deterministic(items)
    if not args.no_judges:
        print("Running AI judges (Azure AI Evaluation SDK) ...")
        judged = ai_judges(items, RESULTS, name)
        summary.update({k: v for k, v in judged.items() if k != "all_metrics"})
    gates = gate(summary)
    meta = {"name": name, "date": time.strftime("%Y-%m-%d %H:%M"), "matchday": ", ".join(map(str, mds)),
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
