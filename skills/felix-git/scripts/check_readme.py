#!/usr/bin/env python3
"""Fail a README that a reader cannot trust. Usage: check_readme.py <repo> --claims claims.json

claims.json: [{"claim": "...", "evidence": ["path/in/repo", "https://...", "cmd: ..."]}]
"""
import argparse, json, re, sys
from pathlib import Path

HYPE = re.compile(r"\b(revolutionary|revolutioniz\w*|game[- ]chang\w*|cutting[- ]edge|next[- ]gen\w*|world[- ]class|best[- ]in[- ]class|blazing\w*|seamless\w*|supercharge\w*|unleash\w*|effortless\w*|magic(al)?|groundbreaking|state[- ]of[- ]the[- ]art|ultimate)\b", re.I)
NUMBER = re.compile(r"(?<![\w.#/-])[$€£]\d[\d,.]*[kmb]?\+?|(?<![\w.#/-])\d[\d,.]*[kmb]?\+?\s?([a-z]{3,}s\b|%|x\b|×|ms\b|s\b|sec\w*|min\w*|hours?\b|GB\b|MB\b|KB\b|times\b|users?\b|stars?\b|tests?\b|models?\b|languages?\b)", re.I)
SUPERLATIVE = re.compile(r"\b(fastest|best|leading|most powerful|trusted by|trusted worldwide|most advanced|lightning[- ]fast|enterprise[- ]grade|used by|loved by|relied on by|adopted by|zero bugs|twice as|\w+ times (?:faster|quicker|better)|by half|most popular|rated #?1|ranked #?1|number one|faster than|better than|beats|unmatched)\b", re.I)
MAGNITUDE = re.compile(r"\b(?:\d[\d,.]*|one|two|three|four|five|six|seven|eight|nine|ten|twenty|fifty|hundred|a)\s?(?:thousand|million|billion)\b|\b(?:hundreds|thousands|millions|billions) of\b", re.I)
IMG = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)|<img\b[^>]*>|<source\b[^>]*srcset=\"([^\"]+)\"", re.I)


# Structural only: this can't tell whether evidence supports a claim. The agent checks that in review.
def inside(repo, rel):
    """True if rel names an existing file within the repo; a README can't vouch for outside files."""
    target = (repo / rel).resolve()
    return target.is_relative_to(repo.resolve()) and target.exists()


def strip_code(text):
    return re.sub(r"```.*?```", "", text, flags=re.S)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("repo")
    p.add_argument("--claims", required=True)
    a = p.parse_args()
    repo = Path(a.repo).resolve()
    if not repo.is_dir():
        sys.exit(f"no such directory: {a.repo}")
    readme = next((f for f in repo.iterdir() if re.fullmatch(r"readme(\.md)?", f.name, re.I) and f.is_file()), None)
    if not readme:
        sys.exit("no README, or it's a directory or a symlink to nothing")
    if not readme.resolve().is_relative_to(repo):
        sys.exit(f"{readme.name} is a symlink out of the repository; a reader can't see that file")
    try:
        text = readme.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        sys.exit(f"{readme.name} isn't UTF-8; GitHub would show it garbled, so convert it first")
    lines = text.splitlines()
    prose = strip_code(text)
    fails, warns = [], []

    try:
        claims = json.loads(Path(a.claims).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"can't read {a.claims}: {e}")
    if not isinstance(claims, list) or not all(isinstance(c, dict) and isinstance(c.get("claim", ""), str) for c in claims):
        sys.exit(f"{a.claims} must be a list of claim objects")
    if not all(isinstance(c.get("evidence") or [], list) and all(isinstance(e, str) for e in c.get("evidence") or []) for c in claims):
        sys.exit(f"{a.claims}: each claim's evidence must be a list of strings")
    known = " ".join(c.get("claim", "") for c in claims)
    if not claims:
        fails.append("claims.json is empty: every checkable line in the README needs an entry")
    for c in claims:
        ev = c.get("evidence") or []
        if not c.get("how"):
            fails.append(f"claim doesn't say how its evidence shows it: {c.get('claim')}")
        if not ev:
            fails.append(f"claim has no evidence: {c.get('claim')}")
        for e in ev:
            if re.match(r"(\./)?readme(\.md)?\b", e, re.I):
                fails.append(f"the README can't be its own evidence: {c.get('claim')}")
            if not re.match(r"https?://|cmd: ", e) and not (not re.match(r"(\./)*\.git(/|$)", e) and inside(repo, e.split(":")[0].split("#")[0]) and (repo / e.split(":")[0].split("#")[0]).is_file()):
                fails.append(f"evidence path missing: {e}")

    for m in HYPE.finditer(prose):
        fails.append(f"hype word without meaning: {m.group(0)}")
    for m in SUPERLATIVE.finditer(prose):
        if m.group(0).lower() not in known.lower():
            fails.append(f"comparison not in claims.json: {m.group(0)}")
    visible = re.sub(r"<[^>]+>|\]\([^)]*\)|!\[[^\]]*\]", " ", prose)
    for m in NUMBER.finditer(visible):
        if m.group(0).strip() not in known:
            fails.append(f"number not in claims.json: {m.group(0).strip()}")

    for m in MAGNITUDE.finditer(visible):
        if m.group(0).lower() not in known.lower():
            fails.append(f"number not in claims.json: {m.group(0)}")

    imgs = list(IMG.finditer(text))
    first = text[:imgs[0].start()].count("\n") + 1 if imgs else None
    if first is None:
        warns.append("no image")
    elif first > 25:
        warns.append(f"first image is at line {first}; readers see it late")
    for m in imgs:
        tag = m.group(0)
        src = m.group(2) or m.group(3) or (re.search(r"""src=["']([^"']+)""", tag) or [None, None])[1]
        if tag.lower().startswith("<img") and not re.search(r"""alt=["'][^"']+""", tag):
            fails.append(f"image without alt text: {src}")
        if tag.startswith("![") and not m.group(1).strip():
            fails.append(f"image without alt text: {src}")
        if src and not re.match(r"https?://|data:", src) and not inside(repo, src):
            fails.append(f"image file missing: {src}")
    for href in re.findall(r"\]\((?!https?://|#|mailto:)([^)\s]+)", text):
        if not inside(repo, href.split("#")[0]):
            fails.append(f"broken relative link: {href}")

    para = next((l for l in lines if l.strip() and not re.match(r"\s*(#|<|!\[|\[!|---)", l)), "")
    if 120 < len(para) <= 200:
        warns.append(f"first line is {len(para)} characters; it should fit a GitHub description, under 120")
    if len(para) > 200:
        warns.append(f"first sentence block is {len(para)} characters; say what it is, for whom, sooner")
    if any(e.startswith("cmd: ") for c in claims for e in c.get("evidence") or []):
        warns.append("cmd: evidence is not run by this check; every one must be a command you really ran, and hashes in it change with the rewrite")

    heads = [l for l in lines if re.match(r"#{1,3} ", l)]
    if not heads:
        fails.append("no headings")
    if not any(re.search(r"install|get(ting)? started|quick ?start|download|setup|usage", h, re.I) for h in heads):
        fails.append("no way to start: add Install, Quick start or Usage")
    if not any(re.search(r"licen[cs]e", h, re.I) for h in heads):
        warns.append("no License section; the owner must choose a license")
    if not any(re.search(r"limit|status|roadmap|not yet|known issues|when not", h, re.I) for h in heads):
        warns.append("no Status or Limits section; stating limits is what makes the rest believable")

    print(json.dumps({"fails": sorted(set(fails)), "warnings": warns, "first_image_line": first,
                      "lines": len(lines), "claims": len(claims)}, indent=1, ensure_ascii=False))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
