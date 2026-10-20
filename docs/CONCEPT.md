# Footballytics: "Your Matchday"

> **One line:** an agentic, cloud-native *personal broadcast*. Footballytics simulates a whole synthetic matchday of concurrent matches. It turns every event into explainable match intelligence and produces a different live show for every fan. The show follows your fantasy squad and clubs across all matches and cuts to the moments that matter to *you*. It explains why each moment matters, in your language and at your depth.

Hackathon: Microsoft x Premier League *Inside the Game*.
Deadlines:
- **Register by Oct 20, 12:00 PM PT (19:00 UTC).**
- **Submit by Oct 27, 11:59 PM PT.**

---

## 1. Why this concept (based on the competitor landscape, Oct 19)

About 85 public competitor repos exist. Most of them converge on the same pattern:

- One match at a time.
- A Foundry and Agent Framework roster of Analyst, Writer, Fact-checker and Personalizer.
- A seeded Python simulator.
- A casual view and an analyst view of the same moment, side by side.

A verifier with a rewrite loop is now table stakes, and the Multi-Agent category is the most crowded.

Three gaps are still open:

| Gap | Competitor entries | Footballytics answer |
|---|---|---|
| Fantasy-driven personalization | **0** | Your fantasy squad drives what you see, live, across every match |
| Multi-match "whip-around" (a personal RedZone) | **0** | A Personal Director agent cuts between concurrent matches for you |
| Adaptive personalization that *learns* in-match | **0**; everyone uses static toggles | A Taste Learner agent updates your profile from skips, replays and questions |

The concept also maps onto the real Premier League x Microsoft roadmap:

- Live broadcast data overlays.
- A Copilot-based fan Companion with localization.
- An AI assistant for the league's fantasy game, which has 11.5M players.

Judges from the Premier League will recognise it as their own problem.

## 2. The five required stages

| Stage | What Footballytics does |
|---|---|
| **Ingest** | The **MatchForge** simulator streams events and 10 Hz tracking for N concurrent matches into Azure Event Hubs, with one partition key per match. |
| **Interpret** | A deterministic stats engine computes xG, xT, pass difficulty, pitch control, momentum and "control vs chaos", PPDA, speed and distance thresholds, plus live fantasy points. |
| **Explain** | Match Analyst agents use MCP tools to say *why* a moment matters, with evidence IDs. A Verifier checks every number. |
| **Render** | A timed, machine-readable overlay cue timeline (JSON). It feeds an in-browser broadcast graphics layer and a personal whip-around player. |
| **Personalize** | Fantasy squad, favourite club and player, depth (Analyst, Fan, Kids), language and voice. Your preference model is learned live. |

## 3. Architecture

```
MatchForge sim (×N matches) ──► Event Hubs ──► Stats & Fantasy Engine (deterministic, <50 ms)
                                                   │  moments + metrics
                                                   ▼
                     ┌────────── Agent Framework workflow (Foundry models) ──────────┐
                     │ Match Analyst ×N (concurrent) → Verifier ↺ → Graphics Producer │
                     │ Personal Director (per fan cohort) → Host (persona + language)  │
                     │ Recap agent (HT/FT, personal + match)   Taste Learner (memory)  │
                     └────────────────────────────┬──────────────────────────────────┘
                                                   ▼
          Cosmos DB (match state, profiles, memory)   Azure Web PubSub ──► Web app (fans/analysts/producer)
          Football Intelligence MCP server  ◄── used by agents *and* GitHub Copilot / any MCP client
```

- **Hosting:** Azure Container Apps (sim, engine, agents, MCP, web) and Azure Functions (kick-off scheduler and full-time recap triggers).
- **AI services:** Foundry (models, evaluations, tracing in App Insights), Azure AI Speech (multilingual host voice) and Content Safety.
- **Delivery:** azd + Bicep and GitHub Actions.

**Cost and latency design (the enterprise story):**

- Template captions appear instantly. The LLM upgrade replaces them about 1–2 s later.
- Each explanation is generated once per (moment × depth × language) and shared across fans. Only the cheap personal layer runs per fan.
- We publish a **cost per 1,000 fans** figure.

## 4. Agents, each with a role a single agent could not cover

1. **Match Analyst** (one per live match, fan-out): explains moments with tools (`pitch_control_at`, `xt_of_action`, `compare_to_baseline`) and cites event IDs.
2. **Verifier**: deterministic claim extraction and checks against the data. Failed claims go back to the Analyst for a rewrite.
3. **Personal Director**: the novel agent. It ranks moments across *all* matches by personal relevance (squad impact, club, learned taste) under an interruption budget. It then decides to **cut**, show **PiP** or **queue**.
4. **Host**: writes personal links, for example "Meanwhile at Riverside, your captain…", in persona and language. Azure AI Speech voices them.
5. **Graphics Producer**: emits overlay cues (template, data, in/out timecodes, priority, safe area).
6. **Recap**: "Your matchday in 60 seconds" plus standard match recaps at half time and full time.
7. **Taste Learner**: updates the fan's preference vector from implicit signals and persists memory across matchdays.

## 5. Synthetic data: MatchForge

- A fictional 20-club league with about 500 players. Attributes and tactical styles include high press, low block and possession.
- An agent-based simulation with fatigue and game-state effects, for example a chasing team pushes higher.
- Exports in **open standards**:
  - SPADL-style events.
  - Metrica-style tracking CSV.
  - Kloppy and socceraction tooling works out of the box.
- A **Realism Scorecard** compares generated matchdays with public league-average ranges: passes, completion %, shots, xG/shot, goals and distance per player.
- An LLM **Scenario Director** steers the simulator with prompts such as "late comeback after a red card". The LLM never invents events itself.
- No real clubs, players or Premier League marks appear, in line with the rules on trademarks.

## 6. Demo video storyboard (under 2:00)

| Time | Shot |
|---|---|
| 0:00 | Hook: "10 matches, 1 fan, 15 players spread across them. Footballytics produces a broadcast just for you." |
| 0:15 | Whip-around: the Director cuts to your captain's chance in another match. The overlay shows xG 0.31 and pass difficulty 8/10 with a "why it matters" line. |
| 0:40 | The same moment for an analyst (pitch control and xT) and a casual fan in Arabic with voice. |
| 1:00 | The Taste Learner adapts: you skip set pieces, so the Director stops cutting to them. |
| 1:15 | The Verifier catches a wrong stat and forces a rewrite (agent trace). |
| 1:30 | MCP: ask GitHub Copilot "who controlled midfield after 60'?". |
| 1:40 | Architecture and cost per 1,000 fans, then the full-time personal recap. |

## 7. Category targeting

- **Grand Prize.**
- **Best Azure Cloud Native Integration**, which is less crowded. Multi-match fan-out is inherently event-driven and scalable.
- Strong secondary fit for the Foundry category.

## 8. Eight-day plan

| Day | Date | Work |
|---|---|---|
| 1 | Oct 19–20 | **Register.** Repo scaffold, event and tracking schema, MatchForge v1 (multi-match) |
| 2 | Oct 21 | Stats engine (xG, xT, pass difficulty, momentum), fantasy points, moment detection, MCP server |
| 3 | Oct 22 | Agent Framework workflow and Foundry models: Analyst, Verifier, Director, Host, Graphics |
| 4 | Oct 23 | Web app: whip-around player, match view with overlays, modes, languages |
| 5 | Oct 24 | Azure: azd/Bicep, Container Apps, Event Hubs, Web PubSub, Cosmos, Speech |
| 6 | Oct 25 | Taste Learner, recaps, Foundry evaluations, cost per 1k fans |
| 7 | Oct 26 | Polish, tests, README, architecture diagram |
| 8 | Oct 27 | Record the demo video and submit before 11:59 PM PT |

## 9. Decisions (Oct 20)

**Core: Your Matchday.** We borrow the best ideas from the strongest rival and refine them:

| Idea | Our version |
|---|---|
| Live 3D broadcast view (three.js) | Rendered live in each viewer's browser (not a pre-rendered MP4). Overlays stay frame-accurate and personal. **Player Cam** follows your fantasy captain all match. |
| Audio description for blind and low-vision fans | A Host-agent persona with Azure AI Speech. Multilingual, and it prioritises *your* squad. |
| Content Safety, Foundry evaluations in CI, CodeQL, azd/Bicep | Same, plus a published cost per 1,000 fans. |

**Not borrowed:** computer-vision auto-eventing from rendered video. A possible separate stretch module for speed and distance only, decided at the Oct 24 checkpoint.

**MatchForge status:**
- An agent-based simulator with a fictional 20-club league, about 25 s of CPU per match.
- Each match runs in its own process.
- The realism scorecard passes **15/15** real-world benchmarks over 24 matches. The run is `python -m footballytics.cli realism`.
  - Goals per match: 2.58 (xG 2.60).
  - Shots: 23.9. xG per shot: 0.108.
  - Passes: 1,019 at 78% completion.
  - Ball in play: 61%.
  - Distance: 9.8 km per outfield player.

## 10. Alternatives considered

- **Synthetic broadcast video with CV auto-eventing.** Rejected as the core: one competitor, *the-ninety-labs* with 301 commits, already does this rigorously. Worth a small stretch module only if time allows.
- **A white-label broadcaster platform** (multi-tenant brand, tone and compliance). Its best parts, per-tenant language, tone and brand, fold into this concept as configuration.
