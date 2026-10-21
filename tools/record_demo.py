"""Record demo-video takes of a running Footballytics instance.

Headed Edge on the machine's real GPU, captured frame by frame through the DevTools screencast (not a screen grab,
so the window may sit behind others). Each take is scripted like a viewer would use the app, and key moments
(automatic cuts, picture-in-picture, a goal on stage, clicks) are logged so clips can be cut from the takes.

    backend/.venv/Scripts/python tools/record_demo.py --url https://<app>/ --out submission/recordings
    backend/.venv/Scripts/python tools/record_demo.py --url ... --pilot          # 15 s check of smoothness

Outputs per take: <take>.mp4 (1920x1080, 30 fps, no audio), <take>.log.json; Audio mode's speech as audio/*.mp3.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import re
import shutil
import time
from pathlib import Path

from playwright.async_api import Page, async_playwright

W, H, FPS = 1920, 1080, 30
HIDE_SCROLLBARS = "::-webkit-scrollbar{display:none} html{scrollbar-width:none}"  # cosmetic, for the camera


class Take:
    """One continuous recording: screencast frames with arrival times, plus a log of marked moments."""

    def __init__(self, page: Page, out: Path, name: str):
        self.page, self.out, self.name = page, out, name
        self.dir = out / f".{name}_frames"
        self.frames: list[tuple[float, str]] = []
        self.log: list[dict] = []
        self.t0 = time.monotonic()  # reset on start(); set here so early events get sane times

    async def start(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True)
        self.cdp = await self.page.context.new_cdp_session(self.page)
        self.cdp.on("Page.screencastFrame", self._frame)
        self.t0 = time.monotonic()
        await self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 90, "maxWidth": W,
                                                     "maxHeight": H, "everyNthFrame": 1})

    def _frame(self, p: dict) -> None:
        name = f"{len(self.frames):06d}.jpg"
        (self.dir / name).write_bytes(base64.b64decode(p["data"]))
        self.frames.append((time.monotonic() - self.t0, name))
        asyncio.ensure_future(self.cdp.send("Page.screencastFrameAck", {"sessionId": p["sessionId"]}))

    @property
    def now(self) -> float:
        return time.monotonic() - self.t0

    def mark(self, label: str, **info) -> None:
        self.log.append({"t": round(self.now, 2), "label": label, **info})
        print(f"  [{self.name} {self.now:6.1f}s] {label} {info if info else ''}", flush=True)

    async def stop(self) -> dict:
        await self.cdp.send("Page.stopScreencast")
        await asyncio.sleep(0.3)
        await self.cdp.detach()
        stats = encode(self.frames, self.dir, self.out / f"{self.name}.mp4")
        (self.out / f"{self.name}.log.json").write_text(json.dumps({"stats": stats, "events": self.log}, indent=1),
                                                       encoding="utf-8")
        shutil.rmtree(self.dir, ignore_errors=True)
        print(f"  saved {self.name}.mp4: {stats}", flush=True)
        return stats


def encode(frames: list[tuple[float, str]], src: Path, path: Path) -> dict:
    """Constant 30 fps H.264: each output frame shows the latest captured frame at that moment."""
    import imageio.v2 as imageio

    if not frames:
        return {"frames": 0}
    duration = frames[-1][0]
    n_out = int(duration * FPS) + 1
    j, last_name, last_img = 0, None, None
    with imageio.get_writer(path, fps=FPS, codec="libx264", quality=8, pixelformat="yuv420p",
                            macro_block_size=8) as w:
        for k in range(n_out):
            t = k / FPS
            while j + 1 < len(frames) and frames[j + 1][0] <= t:
                j += 1
            if frames[j][1] != last_name:
                last_name, last_img = frames[j][1], imageio.imread(src / frames[j][1])
            w.append_data(last_img)
    return {"seconds": round(duration, 1), "captured_frames": len(frames),
            "captured_fps": round(len(frames) / max(duration, 1e-6), 1)}


class Feed:
    """The app's own WebSocket messages, so a take can react to what the Director does."""

    def __init__(self) -> None:
        self.take: Take | None = None
        self.cuts: list[float] = []
        self.pips: list[float] = []
        self.goals: list[tuple[float, str]] = []

    def attach(self, page: Page) -> None:
        page.on("websocket", lambda ws: ws.on("framereceived", self._msg))

    def _msg(self, payload) -> None:
        if self.take is None or not isinstance(payload, str):
            return
        try:
            m = json.loads(payload)
        except ValueError:
            return
        d = m.get("data") or {}
        if m.get("kind") == "director" and d.get("action") in ("cut", "pip"):
            t = self.take.now
            (self.cuts if d["action"] == "cut" else self.pips).append(t)
            self.take.mark(d["action"], match=d.get("match_id"), kind=d.get("kind"), line=(d.get("line") or "")[:70])
        elif m.get("kind") == "moment" and d.get("kind") in ("goal", "wonder_strike"):
            self.goals.append((self.take.now, d.get("match_id", "")))
            self.take.mark("goal", match=d.get("match_id"))


async def scorebug(page: Page) -> str:
    return " ".join(((await page.evaluate("document.querySelector('.scorebug')?.innerText")) or "").split())


async def safe_click(page: Page, locator, take: Take, label: str, **info) -> bool:
    try:
        if await locator.count() == 0:
            return False
        await locator.first.click(timeout=3000)
        take.mark(label, **info)
        return True
    except Exception as exc:  # the UI moved on (a cut, a re-render): skip this beat
        print(f"  ({label} skipped: {type(exc).__name__})", flush=True)
        return False


async def take_matchday(page: Page, out: Path, url: str, feed: Feed, minutes: float) -> None:
    """Setup with Follow one stat, then the Director at work: cuts, picture-in-picture, why, like, Player Cam."""
    await page.goto(url)
    await page.evaluate("localStorage.clear()")
    await page.goto(url)
    await page.wait_for_selector(".setup")
    await page.add_style_tag(content=HIDE_SCROLLBARS)
    take = Take(page, out, "A_matchday")
    feed.take = take
    await take.start()
    take.mark("setup")
    await page.wait_for_timeout(2500)
    await safe_click(page, page.get_by_role("radio", name="KGA Kingsbridge Athletic"), take, "pick_club")
    await page.wait_for_timeout(900)
    await safe_click(page, page.get_by_role("radio", name=re.compile("^Top speed")), take, "pick_stat")
    await page.wait_for_timeout(1200)
    await safe_click(page, page.get_by_role("button", name="Start my matchday →"), take, "start")
    await page.wait_for_selector(".pitch3d canvas", timeout=30_000)

    done = {"why": False, "cam": False, "board": False, "watch": False}
    end = take.now + minutes * 60
    while take.now < end:
        await page.wait_for_timeout(500)
        t = take.now
        # picture-in-picture: let it be seen, then press Watch (once, and not right after a cut)
        if not done["watch"] and feed.pips and t - feed.pips[-1] > 2.5 and t - feed.pips[-1] < 6 \
                and (not feed.cuts or t - feed.cuts[-1] > 10) and t > 40:
            done["watch"] = await safe_click(page, page.locator(".pip button"), take, "pip_watch",
                                             stage=await scorebug(page))
        # why am I seeing this? then like
        if not done["why"] and t > 75 and await page.locator(".feed-card .fc-actions button.link").count():
            card = page.locator(".feed-card").first
            if await safe_click(page, card.locator(".fc-actions button.link"), take, "why_open"):
                await page.wait_for_timeout(3500)
                await safe_click(page, card.locator("button[title='More like this']"), take, "like")
                await page.wait_for_timeout(4500)
                await safe_click(page, card.locator(".fc-actions button.link"), take, "why_close")
                done["why"] = True
        # Player Cam on a squad player who is playing
        if not done["cam"] and t > 125:
            rows = page.locator(".squad li:not(.bench) .sq-row")
            for i in range(await rows.count()):
                pos = (await rows.nth(i).locator(".sq-pos").inner_text()).strip()
                if pos in ("MID", "FWD"):
                    name = (await rows.nth(i).locator(".sq-name").inner_text()).split("\n")[0]
                    if await safe_click(page, rows.nth(i), take, "player_cam", player=name):
                        await page.wait_for_timeout(15_000)
                        await safe_click(page, page.get_by_role("button", name="TV camera"), take, "tv_camera")
                    break
            done["cam"] = True
        # the Follow one stat board: tap the leader to watch their match
        if not done["board"] and t > 175 and await page.locator(".focus-board .lb-row").count():
            await page.locator(".focus-board").scroll_into_view_if_needed()
            await page.wait_for_timeout(2500)
            done["board"] = await safe_click(page, page.locator(".focus-board .lb-row"), take, "board_click",
                                             stage=await scorebug(page))
    feed.take = None
    await take.stop()


async def take_mode(page: Page, out: Path, feed: Feed, name: str, steps: list, seconds: float) -> None:
    take = Take(page, out, name)
    feed.take = take
    await take.start()
    for label, action in steps:
        await action()
        take.mark(label)
        await page.wait_for_timeout(1200)
    await page.wait_for_timeout(seconds * 1000)
    feed.take = None
    await take.stop()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", default="submission/recordings", type=Path)
    ap.add_argument("--minutes", type=float, default=8.0, help="length of the matchday take")
    ap.add_argument("--pilot", action="store_true", help="15 s smoothness check only")
    ap.add_argument("--only", default="", help="comma list: matchday,analyst,kids,audio,studio")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    want = set(filter(None, args.only.split(","))) or {"matchday", "analyst", "kids", "audio", "studio"}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            channel="msedge", headless=False,
            args=["--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
                  "--disable-background-timer-throttling", "--autoplay-policy=no-user-gesture-required"])
        ctx = await browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1)
        page = await ctx.new_page()
        feed = Feed()
        feed.attach(page)

        if args.pilot:
            await page.goto(args.url)
            await page.evaluate("localStorage.clear()")
            await page.goto(args.url)
            await page.get_by_role("radio", name="KGA Kingsbridge Athletic").click()
            await page.get_by_role("button", name="Start my matchday →").click()
            await page.wait_for_selector(".pitch3d canvas", timeout=30_000)
            await page.wait_for_timeout(3000)
            take = Take(page, args.out, "pilot")
            await take.start()
            await page.wait_for_timeout(15_000)
            await take.stop()
            await browser.close()
            return

        if "matchday" in want:
            await take_matchday(page, args.out, args.url, feed, args.minutes)
        else:
            await page.goto(args.url)
            await page.add_style_tag(content=HIDE_SCROLLBARS)
        bar = page.get_by_role("radiogroup", name="Mode")
        lang = page.get_by_label("Language")
        if "analyst" in want:
            await take_mode(page, args.out, feed, "B_analyst", [
                ("analyst_mode", lambda: bar.get_by_role("radio", name="Analyst").click()),
                ("tactical_2d", lambda: page.get_by_role("button", name="Tactical 2D").click()),
            ], 35)
        if "kids" in want:
            await take_mode(page, args.out, feed, "C_kids_urdu", [
                ("broadcast_3d", lambda: page.get_by_role("button", name="Broadcast 3D").click()),
                ("kids_mode", lambda: bar.get_by_role("radio", name="Kids").click()),
                ("urdu", lambda: lang.select_option("ur")),
            ], 45)
            await lang.select_option("en")
        if "audio" in want:
            audio_dir = args.out / "audio"
            audio_dir.mkdir(exist_ok=True)

            async def keep_tts(resp) -> None:
                if "/api/tts" in resp.url and resp.ok:
                    mid = re.search(r"moment_id=([^&]+)", resp.url)
                    (audio_dir / f"{mid.group(1) if mid else int(time.time())}.mp3").write_bytes(await resp.body())

            page.on("response", lambda r: asyncio.ensure_future(keep_tts(r)))
            await take_mode(page, args.out, feed, "D_audio", [
                ("audio_mode", lambda: page.get_by_role("radiogroup", name="Mode").get_by_role("radio", name="Audio").click()),
                ("gesture", lambda: page.locator(".stage-view").click(position={"x": 960, "y": 300})),
            ], 45)
            await bar.get_by_role("radio", name="Fan").click()
        if "studio" in want:
            async def open_item() -> None:
                rows = page.locator(".si-row")
                if await rows.count() > 1:
                    await rows.nth(1).click()

            await take_mode(page, args.out, feed, "E_studio", [
                ("studio", lambda: page.get_by_role("button", name="Studio").click()),
                ("item", open_item),
                ("scroll_trace", lambda: page.locator(".studio-detail").scroll_into_view_if_needed()),
            ], 12)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
