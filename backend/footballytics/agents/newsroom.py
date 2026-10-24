"""Newsroom: a Microsoft Agent Framework workflow that turns a detected moment into verified,
multi-audience, multilingual broadcast content.

    Triage ──(importance >= threshold)──► Analyst ──► Verifier ──(claims ok)──┬─► Host ─────┐
      │                                     ▲              │                  └─► Graphics ─┴─► Publisher ─► output
      │                                     └─(corrections)┘  (max 2 rewrites)
      └──(below threshold: instant template output)

* Analyst (reasoning model): explains *why* the moment matters, returns structured claims.
* Verifier (deterministic): checks every claim against live data and audits every number in the
  prose against the evidence; on failure it sends precise corrections back to the Analyst.
* Host (fast model): renders the verified insight for fan / analyst / kids / audio-description
  audiences, natively in each requested language.
* Graphics (deterministic): builds the timed, machine-readable overlay cue.
* Publisher: fan-in; assembles the broadcast item with the full agent trace for the producer console.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agent_framework import Agent, Executor, WorkflowBuilder, WorkflowContext, handler

from ..engine.moments import Moment
from ..intel import tools
from . import prompts
from .audit import numbers_in, unsupported_numbers
from .clients import chat_client
from .schemas import Claim, Insight, Renditions

log = logging.getLogger("footballytics.newsroom")
MAX_ATTEMPTS = 3
RENDITION_TEXTS = ("fan", "analyst", "kids", "audio", "label")  # everything a viewer can see or hear
_SENTENCE = re.compile(r"(?<=[.!?۔؟])\s+")  # also the Urdu full stop and Arabic question mark


def rendition_problems(rend: dict[str, dict], evidence: list, minute: int) -> dict[str, list[str]]:
    """Language -> numbers in any audience text that cannot be traced to the verified evidence."""
    out = {}
    for lang, r in rend.items():
        bad = unsupported_numbers([r.get(k) or "" for k in RENDITION_TEXTS], evidence, always_ok=[minute])
        if bad:
            out[lang] = bad
    return out


def host_evidence(insight: dict, moment: dict) -> list:
    """The numbers a rendition may use: the verified insight (text and checked claims) and the moment's facts."""
    return [insight, moment.get("facts") or {}]


def scrub_rendition(r: dict, bad: list[str]) -> dict:
    """Last resort: drop every sentence that carries an untraceable number (never put one on air).

    If a text loses every sentence it falls back to another clean text of the same language, then to its label.
    """
    def scrub(text: str) -> str:
        keep = [x for x in _SENTENCE.split(text or "") if not any(raw in bad for _, _, raw in numbers_in(x))]
        return " ".join(keep).strip()

    out = {k: (scrub(v) if k in RENDITION_TEXTS else v) for k, v in r.items()}
    label = out.get("label") or ""
    for k in ("fan", "analyst", "kids", "audio"):
        if not out.get(k):
            out[k] = next((out[o] for o in ("fan", "kids", "analyst", "audio") if out.get(o)), label)
    return out


# ----------------------------------------------------------------------------- messages
@dataclass
class NewsTask:
    moment: dict
    context: dict
    languages: list[str]
    attempt: int = 1
    feedback: list[str] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    started: float = field(default_factory=time.perf_counter)


@dataclass
class Draft:
    task: NewsTask
    insight: Insight


@dataclass
class Verified:
    task: NewsTask
    insight: Insight
    checks: list[dict]
    status: str  # verified | corrected | partially_verified


@dataclass
class HostOut:
    verified: Verified
    renditions: dict[str, dict]


@dataclass
class GraphicsOut:
    verified: Verified
    overlay: dict


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def template_item(moment: dict, reason: str) -> dict:
    """Instant output that needs no model call (low-importance moments, or model unavailable)."""
    cap = moment["caption"]
    return {
        "item_id": f"bi-{moment['moment_id']}", "moment_id": moment["moment_id"], "match_id": moment["match_id"],
        "kind": moment["kind"], "minute": moment["minute"], "importance": moment["importance"], "status": "template",
        "insight": {"headline": cap["fan"], "why_it_matters": "; ".join(moment["why"]), "tactical_angle": None},
        "renditions": {"en": {"fan": cap["fan"], "analyst": cap["analyst"], "kids": cap["kids"], "audio": cap["fan"],
                              "label": cap["fan"][:28]}},
        "overlay": moment["overlay"], "claims": [], "evidence": moment["evidence"],
        "trace": [{"agent": "triage", "ms": 0, "note": reason}], "latency_ms": 0,
    }


# ----------------------------------------------------------------------------- executors
class Triage(Executor):
    def __init__(self, min_importance: float):
        super().__init__(id="triage")
        self.min_importance = min_importance

    @handler
    async def route(self, task: NewsTask, ctx: WorkflowContext[NewsTask, dict]) -> None:
        imp = task.moment["importance"]
        if imp < self.min_importance:
            await ctx.yield_output(template_item(task.moment, f"importance {imp:.0f} < {self.min_importance:.0f}"))
            return
        task.trace.append({"agent": "triage", "ms": 0, "note": f"importance {imp:.0f}: send to analyst"})
        await ctx.send_message(task)


class AnalystExecutor(Executor):
    def __init__(self, agent: Agent, reasoning: bool):
        super().__init__(id="analyst")
        self.agent = agent
        self.reasoning = reasoning

    @handler
    async def analyse(self, task: NewsTask, ctx: WorkflowContext[Draft]) -> None:
        t0 = time.perf_counter()
        msg = ("Explain why this moment matters.\n\nCONTEXT (JSON):\n" + json.dumps(task.context, default=str))
        if task.feedback:
            msg += "\n\nVERIFIER FEEDBACK - fix exactly these issues:\n- " + "\n- ".join(task.feedback)
        opts: dict = {"response_format": Insight, "store": False}
        if self.reasoning:
            opts["reasoning"] = {"effort": os.getenv("ANALYST_EFFORT", "minimal")}
        resp = await self.agent.run(msg, options=opts)
        insight = resp.value if isinstance(resp.value, Insight) else Insight.model_validate_json(resp.text)
        task.trace.append({"agent": "analyst", "attempt": task.attempt, "ms": _ms(t0), "note": insight.headline})
        await ctx.send_message(Draft(task, insight))


class VerifierExecutor(Executor):
    def __init__(self) -> None:
        super().__init__(id="verifier")

    @handler
    async def verify(self, draft: Draft, ctx: WorkflowContext[NewsTask | Verified]) -> None:
        t0 = time.perf_counter()
        task, ins = draft.task, draft.insight
        checks, problems = review(task, ins)
        note = "all claims verified" if not problems else f"{len(problems)} issue(s)"
        task.trace.append({"agent": "verifier", "attempt": task.attempt, "ms": _ms(t0), "note": note,
                           "issues": problems})
        if problems and task.attempt < MAX_ATTEMPTS:
            task.attempt += 1
            task.feedback = problems
            await ctx.send_message(task, target_id="analyst")
            return
        if problems:
            # Out of retries: drop failed claims and fall back to the deterministic reasons for prose.
            ins = Insight(headline=task.moment["caption"]["fan"], why_it_matters="; ".join(task.moment["why"]),
                          tactical_angle=None, claims=[], confidence=0.5)
            status = "partially_verified"
        else:
            status = "verified" if task.attempt == 1 else "corrected"
        await ctx.send_message(Verified(task, ins, checks, status))


class HostExecutor(Executor):
    def __init__(self, agent: Agent):
        super().__init__(id="host")
        self.agent = agent

    @handler
    async def render(self, v: Verified, ctx: WorkflowContext[HostOut]) -> None:
        t0 = time.perf_counter()

        async def one(lang: str, avoid: list[str] | None = None) -> list:
            payload = {"languages": [lang], "verified_insight": v.insight.model_dump(exclude={"claims"}),
                       "moment": {k: v.task.moment[k] for k in ("kind", "minute", "facts")},
                       "names": v.task.context.get("names", {})}
            ask = "Render this verified insight.\n"
            if avoid:
                ask = (f"Your previous draft used numbers that are not in the verified insight or the moment's facts: "
                       f"{', '.join(avoid)}. Rewrite it using only those numbers, or none.\n") + ask
            resp = await self.agent.run(ask + json.dumps(payload, default=str),
                                        options={"response_format": Renditions, "store": False})
            out = resp.value if isinstance(resp.value, Renditions) else Renditions.model_validate_json(resp.text)
            return out.renditions

        rend = {}
        for group in await asyncio.gather(*(one(lang) for lang in v.task.languages)):
            rend.update({r.language: r.model_dump(exclude={"language"}) for r in group})
        # The Host writes after the Verifier, so its numbers are audited too: one rewrite, then any sentence that
        # still carries an untraceable number is dropped. Nothing unverified goes on air. The evidence is exactly what
        # the Host was given (the verified insight and the moment's facts), not the whole match context: a wider pool
        # lets an invented number pass whenever it happens to equal some unrelated statistic.
        evidence = host_evidence(v.insight.model_dump(), v.task.moment)
        minute = v.task.moment["minute"]
        first = rendition_problems(rend, evidence, minute)
        notes, issues = [], [f"unsupported numbers ({lang}): {', '.join(b)}" for lang, b in first.items()]
        if first:
            for group in await asyncio.gather(*(one(lang, first[lang]) for lang in first)):
                rend.update({r.language: r.model_dump(exclude={"language"}) for r in group if r.language in first})
            notes.append(f"rewrote {', '.join(first)}")
            still = rendition_problems({lang: rend[lang] for lang in first if lang in rend}, evidence, minute)
            for lang, bad in still.items():
                rend[lang] = scrub_rendition(rend[lang], bad)
            if still:
                notes.append("removed " + "; ".join(f"{lang}: {', '.join(b)}" for lang, b in still.items()))
        v.task.trace.append({"agent": "host", "ms": _ms(t0),
                             "note": "; ".join([f"{len(rend)} language(s)", *notes]), "issues": issues})
        await ctx.send_message(HostOut(v, rend))


class GraphicsExecutor(Executor):
    def __init__(self) -> None:
        super().__init__(id="graphics")

    @handler
    async def design(self, v: Verified, ctx: WorkflowContext[GraphicsOut]) -> None:
        cue = dict(v.task.moment["overlay"])
        cue["headline"] = v.insight.headline
        cue["verified"] = v.status in ("verified", "corrected")
        v.task.trace.append({"agent": "graphics", "ms": 0, "note": cue["template"]})
        await ctx.send_message(GraphicsOut(v, cue))


class Publisher(Executor):
    def __init__(self) -> None:
        super().__init__(id="publisher")

    @handler
    async def publish(self, parts: list[HostOut | GraphicsOut], ctx: WorkflowContext[Any, dict]) -> None:
        host = next(p for p in parts if isinstance(p, HostOut))
        gfx = next(p for p in parts if isinstance(p, GraphicsOut))
        v, m = host.verified, host.verified.task.moment
        for r in host.renditions.values():
            r["label"] = short_label(r["label"])
        overlay = {**gfx.overlay, "label": {lang: r["label"] for lang, r in host.renditions.items()}}
        await ctx.yield_output({
            "item_id": f"bi-{m['moment_id']}", "moment_id": m["moment_id"], "match_id": m["match_id"],
            "kind": m["kind"], "minute": m["minute"], "importance": m["importance"], "status": v.status,
            "insight": v.insight.model_dump(exclude={"claims"}), "renditions": host.renditions,
            "overlay": overlay, "claims": v.checks, "evidence": m["evidence"], "trace": v.task.trace,
            "latency_ms": _ms(v.task.started),
        })


# ----------------------------------------------------------------------------- newsroom
class Newsroom:
    """Builds the agents once and runs one workflow instance per moment (concurrently, rate-limited)."""

    def __init__(self, min_importance: float = 50.0, max_concurrency: int = 6):
        self.min_importance = min_importance
        self.analyst_kind = os.getenv("ANALYST_MODEL", "reasoning")
        self.analyst = Agent(chat_client(self.analyst_kind), prompts.ANALYST, name="analyst",
                             description="Explains why a match moment matters, with verifiable claims",
                             tools=[tools.get_player_stats, tools.season_context, tools.get_events,
                                    tools.get_pitch_control])
        self.host = Agent(chat_client("fast"), prompts.HOST, name="host",
                          description="Renders verified insights for each audience and language")
        self._sem = asyncio.Semaphore(max_concurrency)

    def workflow(self):
        triage, verifier = Triage(self.min_importance), VerifierExecutor()
        analyst = AnalystExecutor(self.analyst, reasoning=self.analyst_kind == "reasoning")
        host, graphics, publisher = HostExecutor(self.host), GraphicsExecutor(), Publisher()
        return (WorkflowBuilder(name="newsroom", start_executor=triage, max_iterations=20,
                                output_from=[triage, publisher])
                .add_edge(triage, analyst)
                .add_edge(analyst, verifier)
                .add_edge(verifier, analyst, condition=lambda m: isinstance(m, NewsTask))
                .add_edge(verifier, host, condition=lambda m: isinstance(m, Verified))
                .add_edge(verifier, graphics, condition=lambda m: isinstance(m, Verified))
                .add_fan_in_edges([host, graphics], publisher)
                .build())

    async def process(self, moment: Moment | dict, languages: list[str] | None = None,
                      include_context: bool = False) -> dict:
        m = moment.to_dict() if isinstance(moment, Moment) else moment
        if m["importance"] < self.min_importance:
            return template_item(m, "below threshold")
        task = NewsTask(m, build_context(m), languages or ["en"])
        async with self._sem:
            try:
                result = await self.workflow().run(task)
                outputs = result.get_outputs()
                item = outputs[-1] if outputs else template_item(m, "no output")
                if include_context:  # used by the evaluation suite
                    item = {**item, "context": task.context, "moment": m}
                return item
            except Exception as exc:  # model outage must never blank the broadcast
                log.exception("newsroom failed for %s", m["moment_id"])
                item = template_item(m, f"fallback after error: {type(exc).__name__}")
                item["trace"] = task.trace + item["trace"]
                return item


def build_context(m: dict) -> dict:
    """Deterministic context assembly so the Analyst rarely needs a tool round-trip."""
    match_id = m["match_id"]
    exp = tools.explain_moment(m["moment_id"])
    state = tools.get_match_state(match_id)
    players = {}
    for pid in m["player_ids"][:3]:
        try:
            st = tools.get_player_stats(match_id, pid)
        except KeyError:
            continue
        keep = ("name", "goals", "assists", "shots", "xg", "xa", "xt_added", "passes", "pass_accuracy", "key_passes",
                "distance_km", "top_speed_kmh", "sprints", "saves", "impact")
        players[pid] = {k: st.get(k) for k in keep} | {"season": tools.season_context(pid).get("season"),
                                                        "fantasy_points": (st.get("fantasy") or {}).get("points")}
    team_ctx = {t: {k: v for k, v in tools.season_context(t).items() if k in ("club", "pos", "pts", "form")}
                for t in state["score"]}
    keep_team = ("possession", "shots", "shots_on_target", "xg", "big_chances", "pass_completion", "high_turnovers")
    match = {"minute_now": state["minute"], "moment_minute": m["minute"], "score_now": state["score"],
             "regime": state["regime"], "momentum_last_5_min": state["momentum"][-5:],
             "teams": {t: {k: s.get(k) for k in keep_team} for t, s in state["teams"].items()}}
    names = {pid: p["name"] for pid, p in players.items()} | {t: team_ctx[t].get("club") for t in team_ctx}
    return {"moment": {k: m[k] for k in ("moment_id", "kind", "minute", "importance", "facts", "why")},
            "evidence": exp["evidence"], "match": match, "players": players, "table_before_matchday": team_ctx,
            "names": names}


def review(task: NewsTask, ins: Insight,
           check_live: Callable[[list[dict]], list[dict]] | None = None) -> tuple[list[dict], list[str]]:
    """The Verifier's checks as a pure function (also used by the evaluation suite and "try a wrong number"):
    every claim against live data / moment facts, and every number in the prose against the evidence."""
    moment_ids = {"moment", task.moment["moment_id"]}
    own = [c.model_dump() for c in ins.claims if c.subject_id in moment_ids]
    live = [c.model_dump() for c in ins.claims if c.subject_id not in moment_ids]
    check_live = check_live or (lambda claims: tools.verify_claims(task.moment["match_id"], claims))
    checks = check_live(live) + check_moment_facts(task, own)
    problems = []
    for c in checks:
        if not c["ok"]:
            if c.get("actual") is None:
                problems.append(f"Claim {c['subject_id']}.{c['metric']}={c['value']} cannot be checked "
                                f"(unknown subject or metric). Remove it or use a supported metric.")
            else:
                problems.append(f"Claim {c['subject_id']}.{c['metric']}={c['value']} is wrong: the live value "
                                f"is {c['actual']}. Correct the text and the claim.")
    bad_numbers = unsupported_in_prose(task, ins, checks)
    if bad_numbers:
        problems.append(f"These numbers are not supported by the evidence: {', '.join(bad_numbers)}. "
                        f"Use only numbers from the context, or remove them.")
    return checks, problems


def unsupported_in_prose(task: NewsTask, ins: Insight, checks: list[dict]) -> list[str]:
    verified_values = [c["actual"] for c in checks if c["ok"]]
    texts = [ins.headline, ins.why_it_matters, ins.tactical_angle or ""]
    return unsupported_numbers(texts, [task.context, verified_values], always_ok=[task.moment["minute"]])


def checks_as_published(published: list[dict]) -> Callable[[list[dict]], list[dict]]:
    """Check live-data claims against the values the Verifier read when the item was published.

    Live statistics keep moving, so re-reading them minutes later would fault numbers that were right on air.
    """
    seen = {(c["subject_id"], c["metric"]): c["actual"] for c in published if c.get("actual") is not None}

    def check(claims: list[dict]) -> list[dict]:
        out = []
        for c in claims:
            actual = seen.get((c["subject_id"], c["metric"]))
            out.append(tools.check_value(c, actual) if actual is not None
                       else {**c, "ok": False, "actual": None, "reason": "unknown subject or metric"})
        return out

    return check


def subject_name(record: dict, subject_id: str) -> str | None:
    if subject_id in ("moment", record["moment"]["moment_id"]):
        return "this moment"
    name = record["context"].get("names", {}).get(subject_id)
    return name if name and name != subject_id else tools.display_name(subject_id)


def invented_sentence(record: dict) -> str:
    """A plausible sentence whose number the item's evidence cannot support (the "invent a number" button)."""
    evidence = [record["context"], [c.get("actual") for c in record["claims"]]]
    x = next((x for x in ("37.9", "36.4", "38.6", "35.2", "39.1") if unsupported_numbers([x], evidence)), "97.3")
    return f"The decisive run was clocked at {x} km/h."


def try_verifier(record: dict, headline: str, why_it_matters: str, tactical_angle: str | None,
                 claims: list[dict]) -> dict:
    """Run the Verifier on an edited copy of a published item ("try a wrong number"): the same review() that gates
    every broadcast item, against the evidence it had at the time. Nothing here goes on air."""
    task = NewsTask(record["moment"], record["context"], ["en"])
    ins = Insight(headline=headline, why_it_matters=why_it_matters, tactical_angle=tactical_angle or None,
                  claims=[Claim(**c) for c in claims])
    checks, problems = review(task, ins, check_live=checks_as_published(record["claims"]))
    return {"verdict": "rejected" if problems else "passed", "problems": problems,
            "unsupported_numbers": unsupported_in_prose(task, ins, checks),
            "checks": [{**c, "name": subject_name(record, c["subject_id"])} for c in checks],
            "next": (f"Sent back to the Analyst with this feedback for a rewrite (up to {MAX_ATTEMPTS} attempts). "
                     "If it still fails, the claims are dropped and only the deterministic explanation goes on air."
                     if problems else "Passed: on to the Host, who writes it for every audience and language.")}


def check_moment_facts(task: NewsTask, claims: list[dict]) -> list[dict]:
    """Verify claims about the moment itself against its measured facts and evidence assessments."""
    facts = dict(task.moment.get("facts") or {})
    for ev in task.context.get("evidence", []):
        facts.update({k: v for k, v in (ev.get("assessment") or {}).items() if isinstance(v, int | float)})
    out = []
    for c in claims:
        actual = facts.get(c["metric"])
        if not isinstance(actual, int | float) or isinstance(actual, bool):
            out.append({**c, "ok": False, "actual": None, "reason": "unknown moment fact"})
            continue
        actual = float(actual)
        tol =max(0.05 * abs(actual), 0.02 if abs(actual) < 1.5 else 0.6)
        out.append({**c, "ok": bool(abs(float(c["value"]) - actual) <= tol), "actual": actual,
                    "tolerance": round(tol, 3)})
    return out


def short_label(text: str, limit: int = 30) -> str:
    """Trim an overlay label on a word boundary."""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:-") + "…"
