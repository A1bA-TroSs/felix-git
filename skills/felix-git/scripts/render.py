#!/usr/bin/env python3
"""Render an HTML or SVG file Claude wrote to PNG. No image model and no API key.

  render.py in.html out.png [--width 1280 --height 640 --scale 2 --dark]

Sets data-theme="light" or "dark" on the root element, so write theme styles against
[data-theme=dark]; prefers-color-scheme is not reliable across renderers. Network is blocked,
so the page must be self-contained.
Uses Python Playwright, then a Chrome or Chromium binary, then rsvg-convert for SVG.
"""
import argparse, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

CHROMES = ["google-chrome", "chromium", "chromium-browser", "chrome",
           "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
           "/Applications/Chromium.app/Contents/MacOS/Chromium"]


# A dead proxy stops http and WebSocket.
NO_NETWORK = ["--proxy-server=http://127.0.0.1:9", "--proxy-bypass-list=<-loopback>"]
# Scripts stay off: an image needs none, and WebRTC goes around any proxy over UDP. This comes first
# in the file, so it covers every script after it. Chrome's own switch for this also stops its screenshot.
NO_SCRIPT = """<!doctype html><meta http-equiv="Content-Security-Policy" content="script-src 'none'; object-src 'none'">"""


def with_playwright(src, out, a):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        # The dead proxy also stops WebSocket traffic, which page.route doesn't see.
        b = p.chromium.launch(args=NO_NETWORK)
        page = b.new_page(java_script_enabled=False, viewport={"width": a.width, "height": a.height}, device_scale_factor=a.scale,
                          color_scheme="dark" if a.dark else "light")
        page.route("**/*", lambda r: r.continue_() if r.request.url.startswith("file:") else r.abort())
        page.goto(src.as_uri())
        page.wait_for_load_state("load")
        page.screenshot(path=str(out))
        b.close()


def with_chrome(src, out, a):
    exe = next((c for c in CHROMES if shutil.which(c) or Path(c).exists()), None)
    if not exe:
        raise RuntimeError("no Chrome")
    # Headless Chrome occasionally hangs on a busy machine, so one retry with a fresh profile.
    for attempt in (1, 2):
        try:
            return chrome_once(exe, src, out, a)
        except subprocess.TimeoutExpired:
            if attempt == 2:
                raise


def chrome_once(exe, src, out, a):
    with tempfile.TemporaryDirectory() as profile:
        cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={profile}",
               *NO_NETWORK,
               f"--window-size={a.width},{a.height}", f"--force-device-scale-factor={a.scale}",
               f"--screenshot={out}"]
        cmd.append(src.as_uri())
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)


def with_rsvg(src, out, a):
    if src.suffix != ".svg" or not shutil.which("rsvg-convert"):
        raise RuntimeError("no rsvg")
    subprocess.run(["rsvg-convert", "-w", str(a.width * a.scale), "-o", str(out), str(src)], check=True)


def themed_copy(src, dark):
    """A copy beside the source, so relative images still load, with the theme set in the markup."""
    attr = f'data-theme="{"dark" if dark else "light"}"'
    try:
        text = src.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        sys.exit(f"{src.name} isn't UTF-8; convert it first")
    fd, name = tempfile.mkstemp(suffix=".html", prefix=".render-", dir=src.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        if src.suffix == ".svg":
            f.write(f"{NO_SCRIPT}<html {attr}><head><style>body{{margin:0}}</style></head><body>{text}</body></html>")
        elif re.search(r"<html\b", text, re.I):
            f.write(NO_SCRIPT + re.sub(r"<html\b", f"<html {attr}", text, count=1, flags=re.I))
        else:
            f.write(f"{NO_SCRIPT}<html {attr}>{text}</html>")
    return Path(name)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src"); p.add_argument("out")
    p.add_argument("--width", type=int, default=1280); p.add_argument("--height", type=int, default=640)
    p.add_argument("--scale", type=int, default=2); p.add_argument("--dark", action="store_true")
    a = p.parse_args()
    if min(a.width, a.height, a.scale) < 1:
        sys.exit("width, height and scale must be at least 1")
    src, out = Path(a.src).resolve(), Path(a.out).resolve()
    if not src.is_file():
        sys.exit(f"no such file: {src}")
    out.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    try:
        themed = themed_copy(src, a.dark)
    except OSError as e:
        sys.exit(f"can't write beside {src.name}: {e}")
    try:
        for fn, source in ((with_playwright, themed), (with_chrome, themed), (with_rsvg, src)):
            try:
                fn(source, out, a)
                print(f"{fn.__name__}: {out} ({out.stat().st_size} bytes)")
                return
            except Exception as e:  # each renderer is optional; report them all if none works
                errors.append(f"{fn.__name__}: {e}")
    finally:
        themed.unlink(missing_ok=True)
    sys.exit("no renderer worked. Install Chrome or `pip install playwright`.\n" + "\n".join(errors))


if __name__ == "__main__":
    main()
