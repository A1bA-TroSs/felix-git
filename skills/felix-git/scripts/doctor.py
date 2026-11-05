#!/usr/bin/env python3
"""Check what felix-git needs on this machine, and print the command that fixes each gap.

  doctor.py [--json]

Installs nothing and changes nothing. Exit 0 when everything required for a full
run (including publishing) is ready, 1 otherwise. Optional tools only add features.
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

GITLEAKS_MIN = (8, 19)  # first release with the git and dir subcommands scan.py uses
CHROMES = ["google-chrome", "chromium", "chromium-browser", "chrome",
           "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
           "/Applications/Chromium.app/Contents/MacOS/Chromium"]


def run(*cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def os_kind():
    s = platform.system()
    if s == "Darwin":
        return "mac"
    if s == "Windows":
        return "windows"
    if shutil.which("apt-get"):
        return "debian"
    if shutil.which("dnf"):
        return "fedora"
    return "linux"


FIX = {
    "git": {"mac": "xcode-select --install", "debian": "sudo apt-get install -y git", "fedora": "sudo dnf install -y git",
            "windows": "winget install --id Git.Git -e"},
    "git-filter-repo": {"mac": "brew install git-filter-repo", "debian": "sudo apt-get install -y git-filter-repo",
                        "fedora": "sudo dnf install -y git-filter-repo", "*": "python3 -m pip install --user git-filter-repo"},
    "gitleaks": {"mac": "brew install gitleaks", "windows": "winget install --id Gitleaks.Gitleaks -e",
                 "*": "download a release (8.19 or later) from https://github.com/gitleaks/gitleaks/releases and put gitleaks on PATH"},
    "gh": {"mac": "brew install gh", "windows": "winget install --id GitHub.cli -e",
           "*": "see https://github.com/cli/cli/blob/trunk/docs/install_linux.md"},
    "ffmpeg": {"mac": "brew install ffmpeg", "debian": "sudo apt-get install -y ffmpeg", "fedora": "sudo dnf install -y ffmpeg",
               "windows": "winget install --id Gyan.FFmpeg -e"},
    "render": {"*": "python3 -m pip install --user playwright && python3 -m playwright install chromium (or install Google Chrome)"},
    "osv-scanner": {"mac": "brew install osv-scanner", "*": "go install github.com/google/osv-scanner/v2/cmd/osv-scanner@latest"},
}


def fix(name, kind):
    table = FIX[name]
    cmd = table.get(kind) or table.get("*") or table.get("debian")
    if cmd.startswith("brew ") and not shutil.which("brew"):
        cmd = "install Homebrew from https://brew.sh, then: " + cmd
    return cmd


def version(text):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    return tuple(int(x) for x in m.groups() if x) if m else None


def checks():
    kind = os_kind()
    out = []

    def add(name, ok, need, detail, how=None):
        out.append({"name": name, "ok": ok, "need": need, "detail": detail, "fix": None if ok else how})

    code, text = run("git", "--version")
    add("git", code == 0, "required", text if code == 0 else "not found", fix("git", kind))

    add("python3", sys.version_info >= (3, 8), "required", platform.python_version(),
        "install Python 3.8 or later from https://www.python.org/downloads/")

    code, text = run("git", "filter-repo", "--version")
    add("git-filter-repo", code == 0, "required", text if code == 0 else "not found", fix("git-filter-repo", kind))

    code, text = run("gitleaks", "version")
    v = version(text) if code == 0 else None
    ok = bool(v) and v[:2] >= GITLEAKS_MIN
    add("gitleaks", ok, "required to publish",
        (text if ok else f"{text} is older than 8.19") if v else "not found", fix("gitleaks", kind))

    code, text = run("git", "config", "--global", "user.email")
    name_code, _ = run("git", "config", "--global", "user.name")
    add("git identity", code == 0 and name_code == 0, "required for new commits",
        "set" if code == 0 and name_code == 0 else "user.name or user.email unset",
        'git config --global user.name "Your Name" && git config --global user.email "<id>+<login>@users.noreply.github.com"')

    # Claude Code adds "Co-Authored-By: Claude" and "Generated with Claude Code" unless this is off.
    settings = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"
    try:
        conf = json.loads(settings.read_text()) if settings.exists() else {}
    except (OSError, ValueError):
        conf = {}
    attr = conf.get("attribution") if isinstance(conf.get("attribution"), dict) else {}
    off = (attr.get("commit") == "" and attr.get("pr") == "") or (not attr and conf.get("includeCoAuthoredBy") is False)
    add("Claude attribution", off, "recommended: commits read as yours",
        "off" if off else "on: new commits and PRs get Claude attribution lines",
        f'set "attribution": {{"commit": "", "pr": ""}} in {settings}')

    has_gh = bool(shutil.which("gh"))
    add("gh", has_gh, "recommended", "found" if has_gh else "not found: no PRs, metadata or GitHub audit", fix("gh", kind))
    if has_gh:
        code, text = run("gh", "auth", "status", "--hostname", "github.com")
        logged = code == 0
        add("GitHub login", logged, "required to publish", "logged in" if logged else "not logged in",
            "gh auth login --hostname github.com --git-protocol https --web")
        if logged:
            scopes = re.search(r"Token scopes:\s*(.+)", text)
            scopes = scopes.group(1) if scopes else ""
            add("repo scope", not scopes or "'repo'" in scopes, "required to publish",
                scopes or "scopes not shown (fine for a fine-grained token with Contents and Pull requests: write)",
                "gh auth refresh --hostname github.com --scopes repo")
            add("workflow scope", "workflow" in scopes, "needed if history touches .github/workflows",
                "granted" if "workflow" in scopes else "missing: GitHub refuses pushes that rewrite workflow files without it",
                "gh auth refresh --hostname github.com --scopes workflow")
    code, text = run("git", "config", "--get-all", "credential.https://github.com.helper")
    helper = code == 0 and bool(text)
    if not helper:
        code, text = run("git", "config", "--get-all", "credential.helper")
        helper = code == 0 and bool(text)
    add("git credentials", helper, "required to publish",
        "a credential helper is set" if helper else "git has no credential helper for github.com",
        "gh auth setup-git" if has_gh else "install gh, then: gh auth login --web && gh auth setup-git")

    render = None
    try:
        import importlib.util
        if importlib.util.find_spec("playwright"):
            render = "Python Playwright"
    except Exception:
        pass
    if not render:
        exe = next((c for c in CHROMES if shutil.which(c) or Path(c).exists()), None)
        render = f"Chrome ({Path(exe).name})" if exe else None
    if not render and shutil.which("rsvg-convert"):
        render = "rsvg-convert (SVG only)"
    add("image rendering", bool(render), "optional: README images", render or "no Playwright, Chrome or rsvg-convert", fix("render", kind))

    has = bool(shutil.which("ffmpeg"))
    add("ffmpeg", has, "optional: animated hero", "found" if has else "not found", fix("ffmpeg", kind))
    has = bool(shutil.which("osv-scanner"))
    add("osv-scanner", has, "optional: dependency check", "found" if has else "not found", fix("osv-scanner", kind))
    return kind, out


def main():
    kind, out = checks()
    ready = all(c["ok"] for c in out if c["need"].startswith("required"))
    if "--json" in sys.argv:
        print(json.dumps({"os": kind, "ready": ready, "checks": out}, indent=2))
    else:
        for c in out:
            print(f"{'ok  ' if c['ok'] else 'MISS'}  {c['name']:<18} {c['need']:<44} {c['detail']}")
            if c["fix"]:
                print(f"      fix: {c['fix']}")
        print("\nready for a full run" if ready else "\nnot ready: fix the required items above")
    sys.exit(0 if ready else 1)


if __name__ == "__main__":
    main()
