"""Pre-demo smoke test: fly the simulator in headless Chromium like a person would.

Needs both servers up (engine on :8765, `npm run dev` in web/ on :3000) and Playwright
(`pip install playwright && playwright install chromium`).

    python scripts/ui_smoke.py mock                  # free
    python scripts/ui_smoke.py mock 0 warehouse      # free, other place
    python scripts/ui_smoke.py mock-tune             # auto-tune in the practice world, free
    python scripts/ui_smoke.py reactor 60 warehouse  # real credit: at most 60 s ($0.42)

Screenshots land in engine/data/ui_shots/. Exits non-zero on a failed run or browser errors.
"""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "data" / "ui_shots"
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://localhost:3000"
PLACES = {"forest": "Woodland path", "warehouse": "Warehouse floor"}


def state(page) -> dict:
    return page.evaluate("fetch('/engine/state').then(r => r.json())")


def wait_idle(page, timeout: float = 600) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = state(page)
        if s["job"] is None and s["status"] not in ("starting", "running"):
            return s
        time.sleep(1)
    raise TimeoutError(f"job did not finish within {timeout}s")


def hold(page, keys: list[str], seconds: float):
    for k in keys:
        page.keyboard.down(k)
    time.sleep(seconds)
    for k in reversed(keys):
        page.keyboard.up(k)


def main(phase: str, cap: str, scene: str = "forest") -> int:
    world = "reactor" if phase.startswith("reactor") else "mock"
    tag = f"{phase}-{scene}"
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script("localStorage.setItem('lucid-tour-done', '1')")  # skip the first-visit tour
        page.goto(f"{URL}/sim", timeout=90000)
        page.wait_for_selector("text=Ready for take-off", timeout=60000)
        page.get_by_role("radio", name="Real AI world" if world == "reactor" else "Practice world").click()
        page.get_by_role("radio", name=PLACES[scene]).click()
        if world == "reactor":
            page.get_by_label("Time cap in seconds").fill(cap)
        page.screenshot(path=OUT / f"{tag}-0-ready.png")

        if phase.endswith("tune"):
            page.get_by_role("tab", name="Lab").click()
            page.get_by_role("button", name="Auto-tune", exact=False).click()
            if world == "reactor":
                page.get_by_role("button", name="Yes, spend", exact=False).click()
            time.sleep(3)
            s = wait_idle(page)
            page.screenshot(path=OUT / f"{tag}-1-tuned.png")
        else:
            page.get_by_role("button", name="Fly", exact=True).click()
            if world == "reactor":  # the spend pop-up: this test only runs paid when you asked for "reactor"
                page.get_by_role("button", name="Yes, spend", exact=False).click()
            page.get_by_text("Flying", exact=True).wait_for(timeout=180000)
            time.sleep(8 if world == "mock" else 14)
            page.screenshot(path=OUT / f"{tag}-1-autopilot.png")
            hold(page, ["w", "ArrowLeft"], 3)  # a human curve, overriding the autopilot
            page.get_by_role("button", name="worker steps in", exact=True).click()
            time.sleep(6 if world == "mock" else 12)
            page.screenshot(path=OUT / f"{tag}-2-event.png")
            page.keyboard.press(" ")  # autopilot off
            time.sleep(2)
            page.keyboard.press(" ")  # and back on
            time.sleep(4 if world == "mock" else 8)
            stop = page.get_by_role("button", name="Stop", exact=True)
            if stop.count() and stop.is_enabled():
                stop.click()
            s = wait_idle(page)
            page.get_by_role("tab", name="Calls").click()
            time.sleep(1)
        page.screenshot(path=OUT / f"{tag}-3-done.png")
        browser.close()

    f = s["flight"]
    summary = {"status": s["status"], "counts": f["counts"], "usage": s["usage"], "budget": s["budget"],
               "alerts": [a["reasons"] for a in f["alerts"]][-5:], "narration": f["narration"],
               "tune": [{k: r[k] for k in ("params", "score", "forward", "warnings", "collisions")} for r in f["tune"]],
               "log_tail": s["log"][-8:], "console_errors": errors[:10]}
    print(json.dumps(summary, indent=1))
    ok = s["status"] in ("done", "stopped", "stopped: budget") and not errors
    print("SMOKE", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "60", sys.argv[3] if len(sys.argv) > 3 else "forest"))
