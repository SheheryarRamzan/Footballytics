# Footballytics user guide

**Footballytics: Your Matchday** turns a whole matchday into your own broadcast. Ten matches play at once, and the app
follows your club and your fantasy squad across all of them. It cuts to the moments that matter to you and explains
why they matter, in your language and at your depth.

- **Live app:** https://ca-fbx-api-5dn4hvp4.jollysmoke-ceff9f6d.eastus2.azurecontainerapps.io
- **Access:** no sign-in.
- **Browser:** works best in desktop Edge or Chrome.
- **Data:** every club, player and match is synthetic and fictional.

Matchdays play on a loop at 4× speed, so a match is always live. A full match takes about 25 minutes.

To save cost, the live matchday pauses when nobody has had the page open for 3 minutes. It picks up where it stopped as soon as someone opens it.

---

## The 2-minute tour (for judges)

1. **Pick a club and start.** Choose any club, keep **Fan** mode, and press **Start my matchday →**. The app builds
   you a 15-player fantasy squad and puts your club's match on the main stage.
2. **Wait for a cut.** Within a minute or two the **Personal Director** usually cuts to another match on its own.
   It does this when one of your players scores, wins a penalty or makes a big save there. A green banner says
   *"Cutting to …"*. Smaller moments appear as a **picture-in-picture** card with a **Watch →** button.
3. **Ask why.** Open **Why am I seeing this?** on any card in **Your feed** to see the reasons and the relevance
   score. Press 👍 or ✕ and the app says what it learned about your taste.
4. **Follow a player.** Tap a player in **Your squad**. The app switches to their match, and **Player Cam** follows
   them.
5. **Change the audience.** At the top right, switch to **Analyst**, then **Kids**, then choose **اردو** (Urdu) in
   the language menu. The same moments are rewritten for each audience, and the layout flips right-to-left.
6. **Look behind the scenes.** Open **Studio** to see:
   - the agent trace for every item, with each claim checked against live data;
   - the automated quality gates;
   - the auto-eventing results (players and passes recovered from broadcast video).

---

## Screen by screen

### 1. Setup

| Control | What it does |
|---|---|
| **1 · Your club** | Your favourite club. Its match starts on the main stage, and its moments count more for you. |
| **2 · How you like to watch** | **Fan**: the story and drama, in the 3D broadcast view.<br>**Analyst**: tactics first (pitch control, pressing, xG, pass difficulty), in the 2D tactical view.<br>**Kids**: simple words, big moments, speed and saves.<br>**Audio description**: spoken descriptions of where and how the play happened. |
| **3 · Follow one stat (optional)** | Top speed, shot speed, pass difficulty, xG, distance covered or line-breaking passes. Moments of that stat count more for you, and a live top-5 board appears. |
| **Language** | English, Español, العربية, اردو, Français, Português or हिन्दी. Arabic and Urdu switch the whole layout to right-to-left. |
| **Name (optional)** | Your display name. |
| **Start my matchday →** | Picks a valid 15-player fantasy squad: budget 100, at most 3 players per club, and only players who are starting this matchday. It also saves your profile. |

### 2. Top bar

| Control | What it does |
|---|---|
| **Footballytics · Matchday N** and the green dot | The current matchday. The dot is green while the live connection is up. |
| **Your Matchday / Match Centre / Studio** | The three views, described below. |
| **Fan · Analyst · Kids · Audio** | Changes your viewing mode at any time. The Taste Learner keeps what it learned about you. |
| **Language menu** | Changes the language at any time. New stories arrive written natively in that language. |
| **Your name** (button) | **Switch profile**: forgets this profile on this browser and returns to Setup. |

### 3. Scores rail (the ten matches)

Each tile shows a live match: both clubs, the score and the minute.

- **★N** means N of your fantasy players are in that match.
- Your club's match is outlined.
- **Click a tile** to put that match on the main stage.

### 4. Your Matchday

#### Main stage

| Element | What it is |
|---|---|
| **Scorebug** (top left) | The score, the match clock and a LIVE pill for the match on stage. |
| **Banner** (top centre) | *"Cutting to X v Y: …"* appears when the Director cuts there automatically. |
| **Picture-in-picture card** (top right) | Something big in another match. **Watch →** switches to it. |
| **Graphics on the pitch** | Lower-thirds (for example *LINE-BREAKER*, *TOP SPEED*, *CONTROL vs CHAOS*), goal cards and speed tags. Each is driven by a timed, machine-readable overlay cue, and a **✓ Verified** badge appears once the agents' text has been fact-checked. |
| **Name tags and rings** | Gold rings mark your fantasy players, and **©** marks your captain. Name tags appear for your players, the player on the ball, and anyone in a current graphic. |

#### View controls (under the stage)

| Button | What it does |
|---|---|
| **Broadcast 3D** | The 3D stadium view, with a moving TV camera. |
| **Tactical 2D** | A top-down pitch with player numbers. In Analyst mode it is shaded by **pitch control** (who controls each space). |
| **TV camera** | A high touchline camera that pans with the ball. |
| **Player Cam** | Follows one player from close behind (details below). |
| **Overhead** | A high, wide view of the whole pitch. |

How **Player Cam** chooses who to follow:
1. Your followed player (picked by tapping them in **Your squad**), or your captain, if they are in this match.
2. Otherwise, one of your squad players who is in this match.
3. Otherwise, the player on the ball.

**🎥 Following …** shows who it is following. When your own player is in a different match, a button such as
**Follow Okafor in IRV 0-0 MLH →** takes you there.

#### Stats strip (under the stage)

| Element | What it is |
|---|---|
| **Possession, xG, Shots (on target), Pass acc., Field tilt** | The live team stats for the match on stage. The bars use club colours. |
| **Contested / Chaos / X in control** | The *control vs chaos* state over the last 5 minutes, worked out from possession share, turnovers and duels. |
| **Momentum · last 30'** | A bar per minute showing which team holds the attacking threat. |

#### Your squad (side panel)

- Your 15 players with live fantasy points. **C** is your captain (points doubled) and **V** your vice-captain.
- **BENCH** means that player isn't playing this matchday, so they score no points and Player Cam can't follow them.
- **Tap a player** to follow them: the app switches to their match and turns on Player Cam.
- The total at the top is your matchday score.

#### Follow one stat (side panel)

- **Pick or change your stat** with the selector. Choose *None* to stop following one.
- The panel shows the **top 5 players for that stat across all ten matches**. Your players are highlighted.
- **Tap a row** to watch that player's match.

#### Your feed (side panel)

Every moment the Director thinks matters to you appears here, newest first.

| Element | What it is |
|---|---|
| **live** badge | An instant card, shown while the agents write the full story (about 10 s). |
| **✓ Verified / Corrected** | The agents' story, with every number checked against live data. *Corrected* means the Verifier caught a mistake and the Analyst rewrote it. |
| **Why am I seeing this?** | The personal relevance score and the reasons: your squad, your club, your captain, your followed stat, your taste. |
| **👍 / ✕** | More or less like this. The Taste Learner updates your profile and tells you what it learned. ✕ also removes the card. |
| **+N lines** | Fantasy points as they happen (for example *+8 Tom Andersson: goal (captain x2)*). |
| **Full-time recap** | When a match ends: a verified recap with the turning point and player of the match. |

#### Ask the pundit (side panel)

- **Type a question**, or tap a suggestion such as *"How is my captain doing?"*. The Pundit agent answers by calling
  the Football Intelligence tools, and the tools it used are listed with their timings. These are the same tools
  the MCP server exposes.
- **🎬 Brief me**: the Director's planner writes your personal "what to watch next" rundown.

### 5. Match Centre

An analyst desk for the match on stage. It has the same stage, view controls and stats strip as Your Matchday, plus:

| Panel | What it shows |
|---|---|
| **Team comparison** | Goals, xG, shots, on target, big chances, passes, expected threat, high turnovers, tackles, interceptions, corners, fouls and distance. The better value is highlighted. |
| **Player impact** | Every player ranked by impact. **Imp** is the impact score, **xG** and **xT** are expected goals and threat, **Diff** is average pass difficulty (1–10), **Acc** is pass accuracy, and **Top** is top speed in km/h. |
| **Key moments · evidence** | The match timeline. **Click a moment** to see its evidence: the exact events (with their IDs) and the numbers behind it. |

### 6. Studio (the producer's console)

| Panel | What it shows |
|---|---|
| **Newsroom** | Verified items, items corrected by the Verifier, agent latency (p50/p95), viewers and languages on air. |
| **Sim speed ×2 / ×4 / ×8** | Changes the simulation speed. 🔒 **Locked on the public demo**: there is one live matchday for every viewer, so the buttons are greyed out there. They work when you run the app locally. |
| **Restart matchday** | Restarts the current matchday from kick-off. 🔒 Locked on the public demo for the same reason; available locally. |
| **MCP: …/mcp-server/mcp** | The live MCP endpoint. Connect GitHub Copilot, Claude or any MCP client to query the matchday. |
| **Quality gates · automated evaluation** | The latest automated evaluation of the agent newsroom: claim accuracy, planted wrong stats caught, invented stats caught, AI-judge scores and content safety. **Open the run in Microsoft Foundry →** opens it (needs access to our Azure tenant). |
| **Auto-eventing · broadcast video → events** | Players, ball, passes and speeds recovered from rendered broadcast video by a vision pipeline, and scored against the simulator's answer key. See [AUTO_EVENTING.md](AUTO_EVENTING.md). |
| **Broadcast items** | Every agent-written item. Click one to inspect it. |
| **Agent trace** | For the selected item:<ul><li>each workflow step (triage, analyst, verifier, graphics, host) with its timing;</li><li>the **verified claims** (value said vs live value);</li><li>the machine-readable **overlay cue** (JSON);</li><li>the **renditions** in each language.</li></ul> |

---

## Modes and languages

| Mode | Text | Default view |
|---|---|---|
| **Fan** | The story and drama, about your players | Broadcast 3D |
| **Analyst** | Tactics: pitch control, pressing (PPDA), xG, pass difficulty, *why it matters* | Tactical 2D with pitch control |
| **Kids** | Short, simple sentences: speed, saves, big moments | Broadcast 3D |
| **Audio** | Spoken description of where and how the play happened. It plays automatically for verified moments in your match, and for very big moments anywhere. The voice is an Azure OpenAI text-to-speech model, with the browser's own voice as a fallback. Click once anywhere on the page so your browser allows sound. | Broadcast 3D |

There are seven languages. Stories are written natively in each language, not translated afterwards. Until a story
arrives, instant graphics show translated labels with names and numbers.

## What happens on its own

- **Automatic match switching.** The Director scores every moment in every match for you, based on:
  - your squad (your captain counts double);
  - your club;
  - your followed stat;
  - your learned taste.

  It then decides what to do with it:

  | Relevance | What the Director does |
  |---|---|
  | 0.78 or more | **Cuts** the main stage to that match |
  | 0.5 or more | **Picture-in-picture** card |
  | 0.3 or more | A card in **Your feed** |

  To avoid ping-pong there are at least 18 s between cuts, but your player's goal or penalty always cuts. After
  22 s it **returns** you to your match.
- **The matchday loop.** When all ten matches finish, recaps arrive. The next matchday starts 45 s later, and the
  results update the league table (`/api/table`). After matchday 38 the loop starts again at matchday 9.
- **Agents only when someone is watching.** The newsroom writes stories only while a viewer is connected, so
  tokens aren't spent on an empty room.

## For developers

**MCP endpoint**
- `https://<app>/mcp-server/mcp` serves 12 tools, including `list_live_matches`, `get_match_state`,
  `get_moments`, `explain_moment`, `verify_claims`, `get_pitch_control` and `fantasy_points`.
- `.vscode/mcp.json` connects GitHub Copilot agent mode to it.

**REST API**

| Area | Endpoints |
|---|---|
| Health and league | `/api/health`, `/api/league`, `/api/table` |
| Matches and players | `/api/matches`, `/api/matches/{id}`, `/api/matches/{id}/pitch-control`, `/api/players` |
| Moments | `/api/moments`, `/api/moments/{id}/explain` |
| Agent output | `/api/broadcast`, `/api/recaps` |
| Fantasy and leaders | `/api/fantasy`, `/api/leaders?metric=top_speed` |
| Quality and vision | `/api/evals`, `/api/autoevent` |
| Fans and pundit | `/api/fans` (create, update, feedback, rundown), `/api/ask` |
| Live stream | the WebSocket at `/ws` |

**More reading:** the architecture, how to run it locally, the evaluation harness and the auto-eventing pipeline
are in the [README](../README.md), [EVALUATION.md](EVALUATION.md) and [AUTO_EVENTING.md](AUTO_EVENTING.md).

## Troubleshooting

| You see | Why, and what to do |
|---|---|
| **Player Cam** doesn't seem to follow your player | Your player is in another match. Use the **Follow … →** button next to *Following*, or tap them in **Your squad**. |
| **No sound in Audio mode** | Browsers block sound until you interact. Click anywhere once, and check the tab isn't muted. |
| **Cards stay on *live*** | The agents are writing (about 10 s). Small moments stay as instant cards, because only important moments go to the agents. |
| **The match on stage changed by itself** | That's the Personal Director cutting to something that matters to you. You'll be returned to your match after about 22 s. |
| **The Studio's speed and restart buttons are greyed out** | They are locked on the public demo, because they would change the live matchday for everyone watching. Run Footballytics locally to use them. |
| **A blank 3D view** | The 3D view needs WebGL. Try **Tactical 2D**, or another browser. |
