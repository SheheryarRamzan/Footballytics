"""Cut the demo video's R-clips from the takes recorded by tools/record_demo.py, using their event logs.

    backend/.venv/Scripts/python tools/cut_clips.py --dir submission/recordings

Writes clips/R1_setup.mp4 ... and SHOTS.md (what each clip shows, and where it came from in the take).
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

HOME_MATCH = "md09-HBC-KGA"  # the recorded fan supports Kingsbridge Athletic
AUTOEVENT = Path("backend/data/generated/autoevent/md09-HBC-KGA")


def ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def cut(src: Path, dst: Path, start: float, end: float) -> None:
    start = max(0.0, start)
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-i", str(src), "-t",
                    f"{end - start:.2f}", "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
                    "-an", str(dst)], check=True)


def first(events: list[dict], label: str, after: float = 0.0) -> dict | None:
    return next((e for e in events if e["label"] == label and e["t"] >= after), None)


def stage_at(events: list[dict], t: float) -> str:
    """Which match was on stage at time t: home, unless a cut (held 22 s) or a Watch click moved it."""
    stage, until = HOME_MATCH, None
    last_pip = None
    for e in events:
        if e["t"] > t:
            break
        if until is not None and e["t"] > until:
            stage, until = HOME_MATCH, None
        if e["label"] == "cut":
            stage, until = e.get("match") or stage, e["t"] + 22
        elif e["label"] == "pip":
            last_pip = e.get("match")
        elif e["label"] == "pip_watch" and last_pip:
            stage, until = last_pip, None
    if until is not None and t > until:
        stage = HOME_MATCH
    return stage


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("submission/recordings"))
    args = ap.parse_args()
    out = args.dir / "clips"
    out.mkdir(exist_ok=True)
    rows: list[tuple[str, str, str]] = []

    a = args.dir / "A_matchday.mp4"
    if a.exists():
        ev = json.loads((args.dir / "A_matchday.log.json").read_text(encoding="utf-8"))["events"]
        start = first(ev, "start")
        plan = []
        if start:
            plan.append(("R1_setup", 0.0, start["t"] + 3.0, "Setup: club, Follow one stat (Top speed), Start"))
        cut1 = first(ev, "cut", after=(start or {"t": 0})["t"] + 5)
        if cut1:
            plan.append(("R2_autocut", cut1["t"] - 1.0, cut1["t"] + 7.0, f"Automatic cut: {cut1.get('line', '')}"))
        watch = first(ev, "pip_watch")
        if watch:
            pip = max((e for e in ev if e["label"] == "pip" and e["t"] <= watch["t"]), key=lambda e: e["t"],
                      default=None)
            s = (pip or watch)["t"] - 0.5
            plan.append(("R3_pip_watch", s, watch["t"] + 5.0, f"Picture-in-picture, then Watch: {(pip or {}).get('line', '')}"))
        why, close = first(ev, "why_open"), first(ev, "why_close")
        if why:
            plan.append(("R4_why_like", why["t"] - 1.0, (close or why)["t"] + 1.0,
                         "Why am I seeing this? (reasons and relevance), then 👍 and what it learned"))
        cam = first(ev, "player_cam")
        if cam:
            plan.append(("R5_player_cam", cam["t"] - 1.0, cam["t"] + 14.0, f"Player Cam follows {cam.get('player', '')}"))
        goal = next((e for e in ev if e["label"] == "goal" and e.get("match") == stage_at(ev, e["t"])), None)
        if goal:
            plan.append(("R6_goal_on_stage", goal["t"] - 2.0, goal["t"] + 8.0, f"Goal on stage ({goal.get('match')})"))
        board = first(ev, "board_click")
        if board:
            plan.append(("R14_follow_stat", board["t"] - 4.5, board["t"] + 5.0,
                         "Follow one stat: live top 5 across ten matches, tap the leader to watch"))
        for name, s, e, what in plan:
            cut(a, out / f"{name}.mp4", s, e)
            rows.append((name, what, f"A_matchday.mp4 {max(0, s):.1f}–{e:.1f} s"))

    for name, take, what in (("R7_analyst_2d", "B_analyst", "Analyst mode and Tactical 2D with pitch control"),
                             ("R8_kids_urdu", "C_kids_urdu", "Kids mode in Urdu: right-to-left layout"),
                             ("R9_audio", "D_audio", "Audio mode (speech saved separately in audio/*.mp3)"),
                             ("R10_studio", "E_studio", "Studio: quality gates, auto-eventing, agent trace")):
        src = args.dir / f"{take}.mp4"
        if src.exists():
            dur = json.loads((args.dir / f"{take}.log.json").read_text(encoding="utf-8"))["stats"]["seconds"]
            cut(src, out / f"{name}.mp4", 0.0, dur)
            rows.append((name, what, f"{take}.mp4 (whole take)"))

    annotated = AUTOEVENT / "annotated.mp4"
    results = AUTOEVENT / "results.json"
    if annotated.exists() and results.exists():
        r = json.loads(results.read_text(encoding="utf-8"))
        found = [m for m in r["metrics"]["passes"]["matched"] if m["completed"] and m["true_speed_kmh"]]
        if found:
            m = min(found, key=lambda m: abs(m["speed_kmh"] - m["true_speed_kmh"]) - 0.1 * min(m["length_m"], 20))
            t = m["t"] - r["meta"]["start_t"]
        else:
            t = r["meta"]["seconds"] / 2
        cut(annotated, out / "R13_auto_eventing.mp4", t - 3.0, t + 7.0)
        rows.append(("R13_auto_eventing", "Auto-eventing: detections, tracked ball, pass ticker, minimap",
                     f"{annotated} {max(0, t - 3):.1f}–{t + 7:.1f} s"))

    lines = ["# Demo recordings", "",
             "Recorded from the live app (1920x1080, 30 fps, no audio) by tools/record_demo.py; clips cut by "
             "tools/cut_clips.py. The full takes sit next to this file for re-trimming.", "",
             "| Clip | What it shows | Source |", "|---|---|---|"]
    lines += [f"| `clips/{n}.mp4` | {w} | {s} |" for n, w, s in sorted(rows, key=lambda r: int(r[0][1:].split("_")[0]))]
    lines += ["", "Not recorded (needs your sign-in): R11 GitHub Copilot agent mode with the MCP server, "
                  "R12 Foundry portal (Evaluations, Tracing)."]
    (args.dir / "SHOTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
