"""Console errors and horizontal overflow across the SoloSim pages, desktop and phone.

    python scripts/ui_check.py                 # every page, both widths
    python scripts/ui_check.py /intake         # one page

Overflow is checked rather than eyeballed because a sideways scrollbar on a judge's laptop reads
as a broken build, and it is the one regression a screenshot review reliably misses.
"""
import json
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

API = "http://127.0.0.1:8765"
WIDTHS = [("desktop", 1440, 900), ("phone", 390, 844)]
# Noise the pages do not own: the browser's own media chatter and extension traffic.
SKIP = ("favicon", "Download the React DevTools", "ERR_BLOCKED_BY_CLIENT")


def pages():
    clips = json.loads(urllib.request.urlopen(API + "/clips").read())
    paths = ["/", "/intake", "/annotator", "/queue", "/qa"]
    if clips:
        paths.append("/review/" + clips[0]["id"])
    return paths


def main():
    asked = [a for a in sys.argv[1:] if a.startswith("/")]
    paths = asked or pages()
    bad = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        for label, w, h in WIDTHS:
            page = b.new_page(viewport={"width": w, "height": h})
            errs: list[str] = []
            page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errs.append(str(e)))
            for path in paths:
                del errs[:]
                page.goto("http://localhost:3000" + path, wait_until="load")
                time.sleep(3.0)
                over = page.evaluate(
                    "() => {const d=document.documentElement;"
                    "return {scroll: d.scrollWidth, client: d.clientWidth,"
                    " wide: [...document.querySelectorAll('*')]"
                    "  .filter(e => e.getBoundingClientRect().right > d.clientWidth + 2)"
                    "  .slice(0,4).map(e => e.tagName.toLowerCase()+'.'+(e.className||'').toString().slice(0,40))};}"
                )
                real = [e for e in errs if not any(s in e for s in SKIP)]
                spill = over["scroll"] - over["client"]
                ok = not real and spill <= 2
                bad += 0 if ok else 1
                print(f"[{'ok ' if ok else 'BAD'}] {label:7} {path}")
                if spill > 2:
                    print(f"        overflows by {spill}px: {over['wide']}")
                for e in real[:5]:
                    print(f"        console: {e[:180]}")
            page.close()
        b.close()
    print("\nall clean" if not bad else f"\n{bad} page/width combinations need a look")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
