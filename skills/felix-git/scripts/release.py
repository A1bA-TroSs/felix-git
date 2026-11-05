#!/usr/bin/env python3
"""Plan a release from Conventional Commits: the next SemVer and a Keep a Changelog section.

  release.py REPO [--to develop] [--since v1.2.0 | <ref>] [--current 1.2.0] [--date YYYY-MM-DD] [--repo-url URL]

Reads only. Takes the commits on --to that aren't reachable from the last version tag
(or --since), skips merges, and maps each subject to a changelog section:
feat -> Added, fix -> Fixed, perf/refactor -> Changed, revert -> Removed, a breaking
change (`!` or a BREAKING CHANGE footer) -> Changed, marked. docs, test, build, ci, chore
and style go to "other", which the changelog leaves out. A security fix stays under Fixed;
move it to Security by hand. The bump is major for a breaking change (minor
before 1.0.0), minor for feat, patch otherwise. Prints JSON with the plan and the markdown.
"""
import argparse
import datetime
import json
import re
import subprocess
import sys

SUBJECT = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?: (?P<desc>.+)$")
VERSION_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
SECTION = {"feat": "Added", "fix": "Fixed", "perf": "Changed", "refactor": "Changed", "revert": "Removed"}
ORDER = ["Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"]


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def last_version_tag(repo, ref):
    """The highest vX.Y.Z tag reachable from ref, so a tag on another line doesn't count."""
    tags = [t for t in git(repo, "tag", "--merged", ref).split() if VERSION_TAG.match(t)]
    return max(tags, key=lambda t: tuple(int(x) for x in VERSION_TAG.match(t).groups()), default=None)


def bump(current, level):
    major, minor, patch = current
    if level == "major":
        return (major + 1, 0, 0) if major else (0, minor + 1, 0)
    if level == "minor":
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("repo")
    p.add_argument("--to", default="HEAD")
    p.add_argument("--since")
    p.add_argument("--current", help="version to bump from when there is no version tag yet, e.g. 1.2.7")
    p.add_argument("--date", default=datetime.date.today().isoformat())
    p.add_argument("--repo-url", help="https://github.com/owner/name, for the compare link")
    a = p.parse_args()

    since = a.since or last_version_tag(a.repo, a.to)
    m = VERSION_TAG.match(since) if since else None
    if m and not a.current:
        current = tuple(int(x) for x in m.groups())
    elif a.current:
        m = VERSION_TAG.match(a.current)
        if not m:
            sys.exit("--current must look like 1.2.7")
        current = tuple(int(x) for x in m.groups())
    else:
        current = None

    rng = f"{since}..{a.to}" if since else a.to
    log = git(a.repo, "log", "--no-merges", "-z", "--format=%H%x1f%s%x1f%b", rng)
    entries, other, unparsed, level = {}, [], [], None
    for rec in filter(None, log.split("\0")):
        sha, subject, body = (rec.lstrip("\n").split("\x1f") + ["", ""])[:3]
        m = SUBJECT.match(subject.strip())
        if not m:
            unparsed.append({"commit": sha[:10], "subject": subject})
            continue
        breaking = bool(m["bang"]) or bool(re.search(r"^BREAKING[ -]CHANGE: ", body, re.M))
        t = m["type"]
        line = (f"**{m['scope']}:** " if m["scope"] else "") + m["desc"]
        if breaking:
            level = "major"
            entries.setdefault("Changed", []).append("**Breaking:** " + line)
        elif t in SECTION:
            entries.setdefault(SECTION[t], []).append(line)
            if t == "feat" and level != "major":
                level = "minor"
        else:
            other.append({"commit": sha[:10], "subject": subject})
        if level is None and t in SECTION:
            level = "patch"
    if level is None and other:
        level = "patch"
    if level is None and not unparsed:
        print(json.dumps({"since": since, "to": a.to, "nothing_to_release": True}, indent=2))
        return

    nxt = bump(current, level) if current and level else (current if current else (0, 1, 0))
    version = ".".join(map(str, nxt))
    lines = [f"## [{version}] - {a.date}", ""]
    for sec in ORDER:
        if entries.get(sec):
            lines += [f"### {sec}", ""] + [f"- {e}" for e in reversed(entries[sec])] + [""]
    if a.repo_url and since:
        lines.append(f"[{version}]: {a.repo_url.rstrip('/')}/compare/{since}...v{version}")
    print(json.dumps({
        "since": since, "to": a.to, "current": ".".join(map(str, current)) if current else None,
        "bump": level, "next": version, "tag": f"v{version}", "release_branch": f"release/{version}",
        "sections": {k: len(v) for k, v in entries.items()}, "other": other, "unparsed": unparsed,
        "changelog": "\n".join(lines).rstrip() + "\n",
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
