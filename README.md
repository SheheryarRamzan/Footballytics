# Footballytics: Your Matchday

**Every match, made for you.** On a matchday, ten matches kick off at once. Footballytics follows *your* club and *your* fantasy squad across all of them. It cuts to the moments that matter to you and explains **why** they matter, in your language and at your depth: fan, analyst, kids or audio description.

Built for the **Microsoft × Premier League "Inside the Game" Developer Hackathon**. All clubs, players and match data are synthetic and fictional.

> **Live demo:** https://ca-fbx-api-5dn4hvp4.jollysmoke-ceff9f6d.eastus2.azurecontainerapps.io · **Demo video:** _link_
> **MCP endpoint:** `https://ca-fbx-api-5dn4hvp4.jollysmoke-ceff9f6d.eastus2.azurecontainerapps.io/mcp-server/mcp`
>
> Matchdays play on a loop at 4× speed, so a match is always live. Pick a club, and the app builds you a fantasy squad and starts your personal broadcast.

---

## What it does: one pipeline, five stages

| Stage | Footballytics |
|---|---|
| **Ingest** | **MatchForge**, our agent-based simulator, streams events and 10 Hz tracking for a whole matchday of concurrent matches. It calibrates against 15 real-world benchmarks and **passes 15/15** (see [Realism](#synthetic-data-matchforge)). |
| **Interpret** | A deterministic stats engine (about 0.06 ms per frame) computes: <ul><li>Shots: xG with pressure measured from tracking.</li><li>Passing: xT added, **pass difficulty 1–10**, pass accuracy, line-breaking passes.</li><li>Speed: ball and shot speed, sprint and speed tags.</li><li>Team shape: pitch control, momentum, **control vs chaos**, PPDA pressing shifts, tempo.</li><li>Live **fantasy points**.</li></ul> |
| **Explain** | An **agent newsroom** on Microsoft Agent Framework and Foundry explains *why* moments matter. A **Verifier** checks every number against live data and sends wrong claims back for a rewrite. |
| **Render** | Timed, machine-readable **overlay cues** drive a broadcast graphics layer on a live **3D broadcast camera** or a **2D tactical view**. |
| **Personalize** | A **Personal Director** cuts between matches for each fan. It weighs their fantasy squad (captain counts double), their club and their **learned taste**, and every decision answers "why am I seeing this?". |

## The agents (Microsoft Agent Framework + Microsoft Foundry)

```
   moment ─► Triage ──► Analyst (gpt-5-mini) ──► Verifier ──(claims ok)──┬─► Host (gpt-4.1-mini) ─┐
   (stats      │              ▲                     │                    └─► Graphics ────────────┴─► Publisher ─► broadcast item
   engine)     │              └──(corrections)──────┘ max 2 rewrites
               └─(low importance)─► instant template caption
```

| Agent | Role |
|---|---|
| **Analyst** | Explains why a moment matters (game state, momentum, control vs chaos, the player's season). Every statistic it uses is returned as a structured claim. |
| **Verifier** | Deterministic. Checks each claim against live data and audits every number in the prose against the evidence. Precise corrections go back to the Analyst. Every number on air is traceable. |
| **Host** | Renders the verified insight for **fan, analyst, kids and audio-description** audiences, natively in each language the audience requested. |
| **Graphics Producer** | Emits the timed overlay cue: template, in/out, priority, anchor and data. |
| **Personal Director** | Per-fan relevance and cut / picture-in-picture / ticker decisions under an interruption budget. |
| **Director planner** | LLM. Writes each fan's "watch next" brief. |
| **Taste Learner** | Adapts what each fan sees from skips, likes and replays, and explains what it learned. |
| **Pundit** | Answers free-form questions by calling the **Football Intelligence tools**. Every tool call is traced in the UI. |
| **Recap Editor** | Writes a verified full-time story for each match. |

Model calls use **keyless Entra ID auth** through a managed identity; local auth is disabled on every Azure service. Template captions appear instantly, and agent-written lines replace them about 10 s later. If the models are unavailable, the broadcast degrades to templates instead of going blank.

## Football Intelligence MCP server

The same 12 tools our agents use are exposed over **MCP (streamable HTTP)** at `/mcp-server/mcp`. Tools include:

- `list_live_matches`, `get_match_state`, `get_moments`
- `explain_moment`, `verify_claims`
- `get_pitch_control`, `fantasy_points`, …

GitHub Copilot agent mode, Claude or a Foundry agent can query the live matchday. `.vscode/mcp.json` is included.

## Architecture (Azure)

```
             ┌──────────────── Azure Container Apps ────────────────┐
 viewers ◄──►│ api: web app · REST · WebSocket · MCP                 │──► Microsoft Foundry (gpt-5-mini, gpt-4.1-mini)
 (browser)   │      MatchForge sim ► stats engine ► agent newsroom   │       keyless via managed identity
             │      Personal Directors (one per viewer)              │
             └───────────────┬───────────────────────────────────────┘
                             │ intelligence stream (partition key = match)
                             ▼
                      Azure Event Hubs ──► archiver (Container App) ──► Azure Cosmos DB (serverless)
                                              │  checkpoints                 fans · events · moments
                                              ▼                              broadcasts · recaps
                                        Blob Storage
 Observability: OpenTelemetry (app + Agent Framework spans) ──► Application Insights / Log Analytics
 Infrastructure as code: Bicep (infra/), azd (azure.yaml)
```

- **Always live:** matchdays loop, so judges always land on football in progress. Results fold into an evolving league table.
- **Cost-aware:** agents only spend tokens while someone is watching.

## Synthetic data: MatchForge

- **The world:** a fictional 20-club league with 440 players. Attributes, tactical styles and formations shape play; styles include possession, high press, low block and direct.
- **How players act:** each player chooses actions by expected value, using the same transparent xG and xT models.
- **Tracking:** off-ball movement follows formation, pressing, marking and attacking runs. Movement is acceleration-limited, so the 10 Hz tracking is physically plausible.
- **Event feed:** outcomes are resolved at release and *choreographed*, so events and tracking agree. Events are published when their outcome is known, like real feeds.
- **Ground truth:** shots carry the simulator's true goal probability, so analytics can be evaluated against an answer key.

```
python -m footballytics.cli realism --matches 24     # 15/15 real-world benchmarks
```

| Metric (per match) | MatchForge | Real-world range |
|---|---|---|
| Goals / xG | 2.58 / 2.60 | 2.3–3.3 |
| Shots / on target | 23.9 / 7.6 | 21–29 / 7–10.5 |
| xG per shot | 0.108 | 0.085–0.13 |
| Passes / completion | 1,019 / 78% | 780–1,050 / 77–87% |
| Corners, fouls, yellows, offsides | 10.7, 20.1, 3.8, 3.1 | in range |
| Distance per outfielder / top speed | 9.8 km / 32.4 km/h | 9.4–11.8 km / 31–37 |
| Ball in play | 61% | 52–64% |

## Run it locally

Requirements: Python 3.11+, Node 20+. For agents: an Azure subscription with a Foundry project and `az login`.

```bash
cd backend && python -m venv .venv && .venv/Scripts/pip install -e ".[cloud,dev]"   # (bin/ on macOS/Linux)
cp .env.example .env            # Foundry endpoint + model names (no keys)
cd ../frontend && npm ci && npm run build
cd ../backend && .venv/Scripts/python -m uvicorn footballytics.api.app:app --port 8000
# open http://localhost:8000
```

Without Foundry settings, everything except the LLM agents still runs: simulation, stats, moments, Director, overlays and template captions.

**Tests:** `cd backend && .venv/Scripts/python -m pytest -q` runs 28 tests covering the simulator, engine, tools, agent guard rails, personalisation and cloud routing.

## Deploy to Azure

```bash
azd up        # provisions infra/main.bicep, builds the image with local Docker, deploys api + archiver
```

Trial subscriptions cannot use ACR Tasks, so `azure.yaml` builds with local Docker.

## Repository layout

```
backend/footballytics/
  sim/        MatchForge simulator, matchday runner, realism scorecard
  engine/     stats engine: metrics, moments, fantasy ledger, live processor
  agents/     newsroom workflow, prompts, verifier audit, recap, pundit, Foundry clients
  personal/   fan profiles, Personal Director, Taste Learner, rundown agent, viewer sessions
  intel/      Football Intelligence tools + MCP server
  api/        FastAPI app (REST, WebSocket, MCP, static web app)
  hub.py      live matchday hub;  cloud.py  Event Hubs / Cosmos / telemetry;  archiver.py  worker
frontend/src/ React + three.js web app (Your Matchday, Match Centre, Studio)
infra/        Bicep: Foundry, Container Apps, Event Hubs, Cosmos DB, Storage, ACR, monitoring
```

## Responsible AI

- **Synthetic data only;** every club and player is fictional.
- **Numbers are verified:** each claim is checked against data, and numbers that can't be traced are rejected or replaced by deterministic text.
- **Explained personalization:** every cut and card carries its reasons, and the Taste Learner says what it learned.
- **Accessibility:** audio-description mode, right-to-left layouts for Arabic and Urdu, kids mode, and reduced-motion support.

## License

MIT
