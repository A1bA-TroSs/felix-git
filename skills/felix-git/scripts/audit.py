#!/usr/bin/env python3
"""Read-only repo audit. Usage: audit.py <local-clone> [--github owner/name]. Prints JSON."""
import argparse, json, re, subprocess, sys
from pathlib import Path

CONV = re.compile(r"^(feat|fix|refactor|docs|chore|test|perf|build|ci|style|revert)(\([^)]+\))?!?: \S")
ATTR = re.compile(r"Co-Authored-By: *Claude|Generated with \[?Claude", re.I)
AGENT_FILES = re.compile(r"(^|/)(CLAUDE|AGENTS|GEMINI)\.md$|HANDOFF|BLUEPRINT|(^|/)\.claude/|(^|/)\.cursor/|(^|/)(claude|codex|agent)[ _-]?(outputs?|notes?|logs?)/", re.I)


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, errors="replace")
    return r.stdout.strip() if r.returncode == 0 else ""


def gh(*args):
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=40)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def gh_pages(name):
    """Returns the Pages record, {} when GitHub says there is none, None when we couldn't find out."""
    try:
        r = subprocess.run(["gh", "api", f"repos/{name}/pages"], capture_output=True, text=True, timeout=40)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode:
        return {} if "404" in r.stdout + r.stderr else None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


# Ref names may hold characters str.splitlines and str.split treat as breaks, such as U+2028 and U+00A0.
def lines(text):
    return [l for l in text.split("\n") if l]


def push_workflows(repo, files):
    """A rewrite force-pushes every branch and tag, so anything triggered by a push runs again."""
    found = []
    for f in files:
        if not re.match(r"\.github/workflows/.+\.ya?ml$", f):
            continue
        path = Path(repo) / f
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        if re.search(r"^\s*[\"']?push\b|^[\"']?on[\"']?:\s*\[?[^\n]*\bpush\b", text, re.M):
            found.append({"file": f, "tags": bool(re.search(r"^\s*tags\s*:", text, re.M))})
    return found


def readme_info(repo, readme):
    if not readme:
        return {"path": None, "bytes": 0}
    path = Path(repo) / readme
    if not path.exists():
        return {"path": readme, "bytes": 0, "broken": "a symlink to nothing"}
    return {"path": readme, "bytes": path.stat().st_size}


def other_refs(repo):
    """Notes and similar refs stay on the remote, still pointing at the old hashes, after a rewrite."""
    rows = lines(git(repo, "ls-remote", "origin"))
    names = (l.split("\t")[1] for l in rows if "\t" in l)
    return sorted(n for n in names if n != "HEAD" and not n.startswith(("refs/heads/", "refs/tags/", "refs/pull/")))


def pull_ref_count(repo):
    """Pull refs aren't cloned, yet they keep old commits reachable on the host after a rewrite."""
    refs = lines(git(repo, "ls-remote", "origin", "refs/pull/*"))
    return len(refs)


def has_commits(repo):
    return bool(git(repo, "rev-list", "--all", "--max-count=1"))


def default_branch(repo):
    head = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if head:
        return head.split("/", 1)[1]
    for b in ("main", "master"):
        if git(repo, "rev-parse", "--verify", "-q", f"refs/remotes/origin/{b}") or git(repo, "rev-parse", "--verify", "-q", b):
            return b
    return git(repo, "branch", "--show-current")


def branches(repo, base):
    refs = lines(git(repo, "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"))
    names = sorted({r.split("/", 1)[1] for r in refs if "/" in r and not r.endswith("/HEAD")})
    if not names:
        names = lines(git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads"))
    out = []
    for n in names:
        ref = f"origin/{n}" if git(repo, "rev-parse", "--verify", "-q", f"origin/{n}") else n
        base_ref = f"origin/{base}" if git(repo, "rev-parse", "--verify", "-q", f"origin/{base}") else base
        ahead = git(repo, "rev-list", "--count", f"{base_ref}..{ref}")
        out.append({"name": n, "ahead_of_default": int(ahead or 0), "merged": ahead == "0",
                    "last_commit": git(repo, "log", "-1", "--format=%cs", ref)})
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("repo")
    p.add_argument("--github", help="owner/name, adds settings GitHub holds")
    a = p.parse_args()
    if not (Path(a.repo) / ".git").exists() and not git(a.repo, "rev-parse", "--git-dir"):
        sys.exit(f"not a git repository: {a.repo}")
    if not has_commits(a.repo):
        print(json.dumps({"empty": True, "note": "no commits yet, nothing to clean"}))
        return
    base = default_branch(a.repo)
    log = git(a.repo, "log", "--all", "--format=%H%x00%P%x00%B%x01").split("\x01")
    total = merges = conv = attr = 0
    for rec in log:
        parts = rec.strip().split("\x00")
        if len(parts) < 3:
            continue
        total += 1
        msg = parts[2]
        if len(parts[1].split()) > 1:
            merges += 1
        elif CONV.match(msg):
            conv += 1
        attr += bool(ATTR.search(msg))
    files = [f for f in git(a.repo, "ls-files", "-z").split("\0") if f]
    readme = next((f for f in files if re.fullmatch(r"readme(\.\w+)?", f, re.I)), None)
    report = {
        "default_branch": base,
        "branches": branches(a.repo, base),
        "commits": {"total": total, "merges": merges, "non_merge": total - merges,
                    "conventional": conv, "with_claude_attribution": attr,
                    "signed": sum(1 for s in git(a.repo, "log", "--all", "--format=%G?").split() if s != "N")},
        "tags": lines(git(a.repo, "tag")),
        "readme": readme_info(a.repo, readme),
        "license_file": next((f for f in files if re.match(r"(licen[cs]e|copying)", f, re.I)), None),
        "agent_or_planning_files": [f for f in files if AGENT_FILES.search(f)],
        "has_gitignore": ".gitignore" in files,
        "dependency_manifests": [f for f in files if Path(f).name in {
            "package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod", "Package.swift", "pubspec.yaml", "Gemfile"}],
    }
    develop = next((b for b in report["branches"] if b["name"] == "develop"), None)
    report["default_branch_stale"] = bool(develop and develop["ahead_of_default"])
    report["hidden_pull_refs"] = pull_ref_count(a.repo)
    report["other_remote_refs"] = other_refs(a.repo)
    report["push_workflows"] = push_workflows(a.repo, files)
    report["signed_tags"] = sum("-----BEGIN" in git(a.repo, "cat-file", "tag", t) for t in lines(git(a.repo, "for-each-ref", "--format=%(objectname)", "refs/tags")) if git(a.repo, "cat-file", "-t", t).strip() == "tag")
    report["github"] = {"unknown": True, "why": "no --github given, so Pages, open PRs and forks are unknown"}
    if a.github:
        meta = gh("api", f"repos/{a.github}") or {}
        pages = gh_pages(a.github)
        prs = gh("pr", "list", "--repo", a.github, "--state", "open", "--json", "number,headRefName,baseRefName")
        report["github"] = {k: meta.get(k) for k in ("visibility", "description", "homepage", "topics", "stargazers_count", "forks_count", "default_branch")}
        report["github"]["license"] = (meta.get("license") or {}).get("spdx_id")
        report["github"]["pages_source"] = (pages.get("source") or {}).get("branch") if pages else ("unknown" if pages is None else None)
        report["github"]["pages_build_type"] = (pages or {}).get("build_type")
        report["github"]["open_prs"] = "unknown" if prs is None else prs
        access = gh("repo", "view", a.github, "--json", "viewerPermission") or {}
        report["github"]["viewer_permission"] = access.get("viewerPermission")
        if not meta:
            # Empty fields here would read as "no Pages, no PRs", which is how a live site gets frozen.
            report["github"] = {"unknown": True, "why": "gh is missing or not signed in, so Pages, open PRs and forks are unknown"}
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
