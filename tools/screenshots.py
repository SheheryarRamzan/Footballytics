"""Capture README / submission screenshots of a running Footballytics instance with Playwright + Edge.

    backend/.venv/Scripts/python tools/screenshots.py --url https://<app> --out docs/images [--only player-cam]

Drives the real UI: creates a fan, waits for live play, then captures each view at 1920x1080.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import Page, async_playwright

ARGS = ["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]


async def start_fan(page: Page, url: str, club: str = "KGA", mode: str = "Fan", lang: str = "en") -> None:
    await page.goto(url)
    await page.evaluate("localStorage.clear()")
    await page.goto(url)
    await page.get_by_role("radio", name=club_name(club)).click()
    await page.get_by_role("radio", name=mode).first.click()
    await page.get_by_label("Language").select_option(lang)
    await page.get_by_role("button", name="Start my matchday →").click()
    await page.wait_for_selector(".pitch3d canvas, .pitch-canvas", timeout=30_000)


def club_name(code: str) -> str:
    return {"KGA": "KGA Kingsbridge Athletic", "RIV": "RIV Riverside Rovers"}.get(code, code)


async def follow_playing_outfielder(page: Page) -> str:
    rows = page.locator(".squad li:not(.bench) .sq-row")
    n = await rows.count()
    for i in range(n):
        pos = (await rows.nth(i).locator(".sq-pos").inner_text()).strip()
        if pos in ("MID", "FWD"):
            name = (await rows.nth(i).locator(".sq-name").inner_text()).split("\n")[0]
            await rows.nth(i).click()
            return name
    return ""


async def shot(page: Page, out: Path, name: str, selector: str | None = None) -> None:
    path = out / f"{name}.png"
    if selector:
        await page.locator(selector).first.screenshot(path=str(path))
    else:
        await page.screenshot(path=str(path))
    print("saved", path)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000/")
    ap.add_argument("--out", default="docs/images")
    ap.add_argument("--only", default="", help="comma-separated subset of shots")
    ap.add_argument("--wait", type=float, default=25, help="seconds of live play before the first capture")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    only = set(filter(None, args.only.split(",")))
    want = lambda n: not only or n in only  # noqa: E731

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel="msedge", headless=True, args=ARGS)
        page = await browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        if want("setup"):
            await page.goto(args.url)
            await page.evaluate("localStorage.clear()")
            await page.goto(args.url)
            await page.wait_for_selector(".setup")
            await shot(page, out, "setup")
        if any(want(n) for n in ("matchday", "player-cam", "broadcast", "analyst", "centre", "studio")):
            await start_fan(page, args.url)
            await page.wait_for_timeout(args.wait * 1000)
        if want("matchday"):
            await shot(page, out, "matchday")
        if want("player-cam"):
            who = await follow_playing_outfielder(page)
            await page.wait_for_timeout(6000)
            print("following", who)
            await shot(page, out, "player-cam", ".stage-view")
        if want("broadcast"):
            await page.get_by_role("button", name="TV camera").click()
            await page.wait_for_timeout(5000)
            await shot(page, out, "broadcast-3d", ".stage-view")
        if want("analyst"):
            await page.get_by_role("radio", name="Analyst").click()
            await page.get_by_role("button", name="Tactical 2D").click()
            await page.wait_for_timeout(6000)
            await shot(page, out, "analyst-2d")
        if want("centre"):
            await page.get_by_role("button", name="Match Centre").click()
            await page.wait_for_timeout(5000)
            await shot(page, out, "match-centre")
        if want("studio"):
            await page.get_by_role("button", name="Studio").click()
            await page.wait_for_timeout(4000)
            rows = page.locator(".si-row")
            if await rows.count() > 1:
                await rows.nth(1).click()
            await page.wait_for_timeout(1000)
            await shot(page, out, "studio")
        if want("urdu"):
            # a second fan who signs up in Urdu, Kids mode: the agents write for them from the first moment
            ur = await browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
            await start_fan(ur, args.url, club="RIV", mode="Kids", lang="ur")
            await ur.wait_for_timeout(max(args.wait, 60) * 1000)
            await shot(ur, out, "urdu-kids")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
