#!/usr/bin/env python3
"""Turn captured frames into a looping animated WebP for a README hero.

GitHub shows an animated WebP or GIF inline from the repository, but not an
mp4 committed to it (video plays only after uploading it into an issue).

  animate.py FRAMES_DIR OUT.webp [--width 1200] [--quality 70] [--hold 1500]

FRAMES_DIR holds PNG frames and frames.json, a list of {"f": "<file name>",
"t": <capture time in ms>} in order. Each frame is shown until the next one's
time; the last is held for --hold ms. Needs ffmpeg with libwebp.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("frames")
    p.add_argument("out")
    p.add_argument("--width", type=int, default=1200)
    p.add_argument("--quality", type=int, default=70)
    p.add_argument("--hold", type=int, default=1500)
    a = p.parse_args()
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is missing: brew install ffmpeg")
    d = Path(a.frames).resolve()
    frames = json.loads((d / "frames.json").read_text())
    if not frames:
        sys.exit("frames.json lists no frames")
    lines = []
    for cur, nxt in zip(frames, frames[1:] + [None]):
        name = Path(cur["f"]).name
        if not (d / name).is_file():
            sys.exit(f"missing frame: {name}")
        dur = ((nxt["t"] - cur["t"]) if nxt else a.hold) / 1000
        lines += [f"file '{name}'", f"duration {max(dur, 0.05):.3f}"]
    lines.append(f"file '{Path(frames[-1]['f']).name}'")
    (d / "list.txt").write_text("\n".join(lines) + "\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(d / "list.txt"),
                    "-vf", f"scale={a.width}:-1:flags=lanczos,fps=20", "-c:v", "libwebp_anim", "-lossless", "0",
                    "-q:v", str(a.quality), "-compression_level", "6", "-loop", "0", a.out], check=True)
    size = Path(a.out).stat().st_size
    print(f"{a.out}: {len(frames)} frames, {size / 1e6:.1f} MB")
    if size > 10e6:
        print("over 10 MB: lower --width or --quality, or cut frames", file=sys.stderr)


if __name__ == "__main__":
    main()
