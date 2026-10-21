"""Trust guarantees: unverified numbers never reach air, and the evaluation's planted-error machinery works.

No model or Azure access needed: the Host's language model is replaced by a scripted fake.
"""

import asyncio
import random
import re
import types

from footballytics.agents.newsroom import (
    HostExecutor,
    NewsTask,
    Verified,
    rendition_problems,
    scrub_rendition,
)
from footballytics.agents.schemas import Claim, Insight, Rendition, Renditions
from footballytics.evals.run import FABRICATIONS, planted_summary, plant_in_renditions, random_fabrication, wilson

EVIDENCE = [{"facts": {"xg": 0.43, "speed_kmh": 31.2, "distance_m": 18.4}}]


def _rend(fan: str, analyst: str = "xG 0.43.", kids: str = "Wow!", audio: str = "He ran at 31.2 km/h.",
          label: str = "BIG CHANCE") -> dict:
    return {"fan": fan, "analyst": analyst, "kids": kids, "audio": audio, "label": label}


def test_every_audience_text_and_language_is_audited():
    rend = {
        "en": _rend("What a chance from 18 metres!", kids="That was his 47th shot!"),
        "ar": _rend("فرصة كبيرة. وكانت مراوغته رقم ٤٧ هذا الموسم."),  # Arabic-Indic digits
        "es": _rend("¡Qué ocasión! Fue en el minuto 12."),  # the moment's minute is always allowed
    }
    bad = rendition_problems(rend, EVIDENCE, minute=12)
    assert bad == {"en": ["47"], "ar": ["٤٧"]}  # "18" truncates 18.4; "12" is the minute


def test_scrubbing_drops_only_the_sentences_with_unverified_numbers():
    r = _rend("Huge chance. He has 47 dribbles this season.", analyst="He has 47 dribbles this season.")
    clean = scrub_rendition(r, ["47"])
    assert clean["fan"] == "Huge chance."
    assert clean["analyst"] == "Huge chance."  # emptied text falls back to a clean one in the same language
    assert clean["audio"] == r["audio"] and clean["label"] == r["label"]
    assert not rendition_problems({"en": clean}, EVIDENCE, minute=12)


class _ScriptedHost:
    """Fake Host model: the first draft invents numbers; the rewrite fixes English but not Arabic."""

    def __init__(self):
        self.calls = []

    async def run(self, prompt: str, options=None):
        self.calls.append(prompt)
        lang = re.search(r'"languages": \["(\w+)"\]', prompt).group(1)
        retry = prompt.startswith("Your previous draft")
        if lang == "en":
            fan = "Huge chance at 0.43 xG." if retry else "Huge chance, his 47th of the season."
        else:
            fan = "فرصة كبيرة. وكانت مراوغته رقم ٥٣ هذا الموسم."
        r = Rendition(language=lang, **_rend(fan))
        return types.SimpleNamespace(value=Renditions(renditions=[r]), text="")


def test_host_rewrites_then_removes_numbers_it_cannot_verify():
    moment = {"moment_id": "m1", "match_id": "md01-AAA-BBB", "kind": "big_chance", "minute": 12, "facts": EVIDENCE[0]["facts"]}
    task = NewsTask(moment, {"moment": {"facts": moment["facts"]}, "evidence": []}, ["en", "ar"])  # as build_context
    insight = Insight(headline="Big chance", why_it_matters="xG 0.43 from 18.4 m.", claims=[
        Claim(subject_id="moment", metric="xg", value=0.43)])
    host = HostExecutor(agent=_ScriptedHost())
    sent = []
    ctx = types.SimpleNamespace(send_message=lambda msg: _record(sent, msg))
    asyncio.run(host.render(Verified(task, insight, [], "verified"), ctx))

    out = sent[0].renditions
    assert out["en"]["fan"] == "Huge chance at 0.43 xG."  # fixed by the rewrite
    assert out["ar"]["fan"] == "فرصة كبيرة."  # still wrong after the rewrite: the sentence is removed
    assert not rendition_problems(out, [task.context, insight.model_dump()], minute=12)
    step = task.trace[-1]
    assert step["agent"] == "host" and "rewrote en, ar" in step["note"] and step["note"].endswith("removed ar: ٥٣")
    assert len(host.agent.calls) == 4  # two first drafts, two rewrites


async def _record(sent: list, msg) -> None:
    sent.append(msg)


def test_wilson_interval_is_honest_at_the_extremes():
    lo, hi = wilson(24, 24)
    assert hi == 1.0 and 0.85 < lo < 0.87  # 24/24 is "very likely above 86%", not "always"
    assert wilson(0, 24)[1] < 0.14
    assert wilson(0, 0) is None


def test_random_fabrications_vary_and_only_use_auditable_numbers():
    rng = random.Random(7)
    seen = {random_fabrication(rng) for _ in range(40)}
    assert len(seen) > 30
    templates = {re.sub(r"[\d.]+", "#", s) for s in seen}
    assert len(templates) >= len(FABRICATIONS) - 3
    for sentence in seen:  # the audit exempts whole numbers 0-11 only, so every planted number must be auditable
        assert all("." in n or float(n) > 11 for n in re.findall(r"\d+(?:\.\d+)?", sentence))


def test_rendition_plants_are_caught_and_removed_in_every_language():
    item = {"moment_id": "m9", "minute": 12, "moment": {"facts": {}}, "context": {}, "insight": {"headline": "x"}, "claims": [],
            "renditions": {lang: _rend("Huge chance.") for lang in ("en", "es", "ar")}}
    tests = plant_in_renditions(item)["rendition_tests"]
    assert [t["language"] for t in tests] == ["en", "es", "ar"]
    assert all(t["caught"] and t["removed"] for t in tests)


def test_planted_summary_counts_each_test_type_with_intervals():
    planted = [{"claim_caught": True, "near_miss_caught": True, "wrong_subject_caught": None,
                "fabrication_caught": True, "varied_fabrication_caught": i != 0, "control_false_alarm": False,
                "within_tolerance_false_alarm": False, "small_number_fabrication_caught": False,
                "rendition_tests": [{"language": "en", "caught": True, "removed": True}]} for i in range(4)]
    s = planted_summary(planted)
    assert s["planted"]["varied_fabrication"]["caught"] == 3 and s["planted"]["varied_fabrication"]["n"] == 4
    assert s["planted"]["wrong_subject"]["n"] == 0 and s["wrong_subject_catch_rate"] is None
    assert s["false_alarms"]["within_tolerance"]["flagged"] == 0
    assert s["blind_spots"]["small_number_fabrication"]["caught"] == 0
    assert s["planted_total_tests"] == 4 * 4 + 4  # four claim/fabrication tests per item plus one rendition test
