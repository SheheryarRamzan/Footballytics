"""Fixtures, matchdays and season history for the fictional league.

* ``fixtures(league)`` builds a double round-robin (38 matchdays for 20 clubs).
* ``play_matchday`` simulates all fixtures of a matchday in parallel processes and writes
  one JSONL event file per match (plus optional gzipped 10 Hz tracking).
* ``build_season`` plays matchdays 1..N and aggregates a league table and player season
  stats, which the narrative agents use for context ("his 8th goal of the season").
"""

from __future__ import annotations

import gzip
import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from ..league import League, generate_league
from .engine import MatchSim

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "generated"


def fixtures(league: League, seed: int = 2026) -> list[list[tuple[str, str]]]:
    """Double round-robin via the circle method. Returns matchdays -> [(home, away), ...]."""
    import random

    clubs = list(league.clubs)
    random.Random(seed).shuffle(clubs)
    n = len(clubs)
    rounds: list[list[tuple[str, str]]] = []
    arr = clubs[:]
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = arr[i], arr[n - 1 - i]
            pairs.append((a, b) if (r + i) % 2 == 0 else (b, a))
        rounds.append(pairs)
        arr = [arr[0]] + [arr[-1]] + arr[1:-1]
    second_half = [[(b, a) for a, b in rnd] for rnd in rounds]
    return rounds + second_half


def match_id_for(matchday: int, home: str, away: str) -> str:
    return f"md{matchday:02d}-{home}-{away}"


@dataclass
class MatchResult:
    match_id: str
    matchday: int
    home: str
    away: str
    home_goals: int
    away_goals: int
    events_path: str
    tracking_path: str | None


def _play(args: tuple[int, str, str, int, str, bool]) -> MatchResult:
    matchday, home, away, seed, out_dir, with_tracking = args
    league = generate_league()
    mid = match_id_for(matchday, home, away)
    sim = MatchSim(league, home, away, mid, seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ev_path = out / f"{mid}.events.jsonl"
    tr_path = out / f"{mid}.tracking.jsonl.gz" if with_tracking else None
    meta = sim.meta()
    meta["matchday"] = matchday
    tr_file = gzip.open(tr_path, "wt", encoding="utf-8") if tr_path else None
    with ev_path.open("w", encoding="utf-8") as ev_file:
        ev_file.write(json.dumps({"_meta": meta}) + "\n")
        for frame, events in sim.run():
            for e in events:
                ev_file.write(json.dumps(e) + "\n")
            if tr_file is not None:
                tr_file.write(json.dumps(frame) + "\n")
    if tr_file is not None:
        tr_file.close()
    return MatchResult(mid, matchday, home, away, sim.score[0], sim.score[1], str(ev_path),
                       str(tr_path) if tr_path else None)


def play_matchday(matchday: int, out_dir: Path | None = None, with_tracking: bool = False,
                  workers: int = 8, league: League | None = None) -> list[MatchResult]:
    league = league or generate_league()
    rounds = fixtures(league)
    out_dir = out_dir or DATA_DIR / "season" / f"md{matchday:02d}"
    jobs = [(matchday, h, a, 10_000 * matchday + i, str(out_dir), with_tracking)
            for i, (h, a) in enumerate(rounds[matchday - 1])]
    with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as ex:
        return list(ex.map(_play, jobs))


def read_events(path: str | Path) -> tuple[dict, list[dict]]:
    meta: dict = {}
    events: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if "_meta" in row:
                meta = row["_meta"]
            else:
                events.append(row)
    return meta, events


def season_tables(results: list[MatchResult], league: League) -> dict:
    """League table + player season totals from played matches."""
    table: dict[str, dict] = {c: {"club": c, "name": league.clubs[c].name, "p": 0, "w": 0, "d": 0, "l": 0,
                                  "gf": 0, "ga": 0, "pts": 0, "form": []} for c in league.clubs}
    players: dict[str, dict] = defaultdict(lambda: {"apps": 0, "goals": 0, "assists": 0, "shots": 0,
                                                    "yellow": 0, "red": 0, "clean_sheets": 0})
    for r in sorted(results, key=lambda r: r.matchday):
        for club, gf, ga in ((r.home, r.home_goals, r.away_goals), (r.away, r.away_goals, r.home_goals)):
            row = table[club]
            row["p"] += 1
            row["gf"] += gf
            row["ga"] += ga
            res = "W" if gf > ga else "D" if gf == ga else "L"
            row[{"W": "w", "D": "d", "L": "l"}[res]] += 1
            row["pts"] += {"W": 3, "D": 1, "L": 0}[res]
            row["form"] = (row["form"] + [res])[-5:]
        meta, events = read_events(r.events_path)
        for pid in meta.get("home_lineup", []) + meta.get("away_lineup", []):
            players[pid]["apps"] += 1
        for e in events:
            if e["type"] == "substitution":
                players[e["qualifiers"]["replacement_id"]]["apps"] += 1
            elif e["type"] == "goal":
                players[e["player_id"]]["goals"] += 1
                if e["qualifiers"].get("assist_id"):
                    players[e["qualifiers"]["assist_id"]]["assists"] += 1
            elif e["type"] == "shot":
                players[e["player_id"]]["shots"] += 1
            elif e["type"] == "card":
                players[e["player_id"]]["yellow" if e["outcome"] == "yellow" else "red"] += 1
        for keeper_side, conceded in (("home_lineup", r.away_goals), ("away_lineup", r.home_goals)):
            if conceded == 0 and meta.get(keeper_side):
                gk = next((p for p in meta[keeper_side] if league.players[p].role == "GK"), None)
                if gk:
                    players[gk]["clean_sheets"] += 1
    ranked = sorted(table.values(), key=lambda r: (-r["pts"], -(r["gf"] - r["ga"]), -r["gf"], r["name"]))
    for i, row in enumerate(ranked, 1):
        row["pos"] = i
        row["gd"] = row["gf"] - row["ga"]
    return {"table": ranked, "players": dict(players)}


def build_season(upto: int, out_dir: Path | None = None, workers: int = 8) -> dict:
    """Play matchdays 1..upto (events only) and write season.json with table + player totals."""
    league = generate_league()
    out_dir = out_dir or DATA_DIR / "season"
    results: list[MatchResult] = []
    for md in range(1, upto + 1):
        results.extend(play_matchday(md, out_dir / f"md{md:02d}", workers=workers, league=league))
    season = season_tables(results, league)
    season["played_matchdays"] = upto
    season["results"] = [r.__dict__ for r in results]
    (out_dir / "season.json").write_text(json.dumps(season, indent=1), encoding="utf-8")
    return season
