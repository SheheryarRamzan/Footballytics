"""Footballytics command line.

Examples:
    python -m footballytics.cli realism --matches 16
    python -m footballytics.cli fixtures --md 1
    python -m footballytics.cli matchday --md 1 --tracking
    python -m footballytics.cli season --upto 10
"""

from __future__ import annotations

import argparse
import json


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="footballytics")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("realism", help="Simulate random fixtures and compare with real-world ranges")
    p.add_argument("--matches", type=int, default=16)
    p.add_argument("--json", action="store_true", help="Print the full report as JSON")

    p = sub.add_parser("fixtures", help="Show fixtures for a matchday")
    p.add_argument("--md", type=int, default=1)

    p = sub.add_parser("matchday", help="Simulate all fixtures of a matchday")
    p.add_argument("--md", type=int, required=True)
    p.add_argument("--tracking", action="store_true", help="Also write gzipped 10 Hz tracking")

    p = sub.add_parser("season", help="Simulate matchdays 1..N and write season.json")
    p.add_argument("--upto", type=int, required=True)

    args = parser.parse_args(argv)

    if args.cmd == "realism":
        from .sim.realism import scorecard

        rep = scorecard(args.matches)
        if args.json:
            print(json.dumps(rep, indent=2))
            return
        checks = {k: v for k, v in rep.items() if not k.startswith("_")}
        for v in checks.values():
            print(f"{'PASS' if v['ok'] else 'FAIL'}  {v['label']:<34} {v['value']:>9}   range {v['range']}")
        print(f"realism: {sum(v['ok'] for v in checks.values())}/{len(checks)}")
    elif args.cmd == "fixtures":
        from .league import generate_league
        from .sim.matchday import fixtures

        league = generate_league()
        for h, a in fixtures(league)[args.md - 1]:
            print(f"{league.clubs[h].name:>22}  v  {league.clubs[a].name}")
    elif args.cmd == "matchday":
        from .sim.matchday import play_matchday

        for r in play_matchday(args.md, with_tracking=args.tracking):
            print(f"{r.home} {r.home_goals}-{r.away_goals} {r.away}   {r.events_path}")
    elif args.cmd == "season":
        from .sim.matchday import build_season

        season = build_season(args.upto)
        for row in season["table"][:20]:
            print(f"{row['pos']:>2}. {row['name']:<22} P{row['p']:>2} W{row['w']:>2} D{row['d']:>2} "
                  f"L{row['l']:>2} GD{row['gd']:>+4} {row['pts']:>3} pts  {''.join(row['form'])}")


if __name__ == "__main__":
    main()
