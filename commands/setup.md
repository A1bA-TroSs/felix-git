---
description: Check and install what felix-git needs (git-filter-repo, gitleaks, GitHub login, attribution off) on this machine
allowed-tools: Bash(python3:*), Bash(brew:*), Bash(gh:*), Bash(git:*), Read, Edit, AskUserQuestion
---

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/felix-git/scripts/doctor.py" --json
```

Show the result as a short list: each missing item, what it is needed for, and its fix command. Then:

1. If `ready` is true and nothing optional is missing, say felix-git is ready and stop.
2. Collect the fix commands of missing items that are package installs (`brew install`, `apt-get install`, `dnf install`, `pip install`, `winget install`). Use `AskUserQuestion` once, with a multi-select of those items (required ones first, marked required) plus `Skip for now`. Run only the commands the user picked, one at a time, and report any that fail. Never run `sudo` yourself: show the user that command to run instead.
3. If Homebrew itself is missing on a Mac, don't install it: give the user the command from https://brew.sh to run in their own terminal, because it asks for their password.
4. Sign-ins need the user's own browser, so never run them yourself. If "GitHub login", "repo scope", "workflow scope" or "git credentials" is missing, tell the user to type these at the prompt, with the leading `!` so they run in this session:
   - `! gh auth login --hostname github.com --git-protocol https --web`
   - `! gh auth setup-git`
   - `! gh auth refresh --hostname github.com --scopes workflow` (only if the scope is missing)
5. If the git identity is missing, ask for the name and the email to use in commits, and suggest GitHub's noreply address so a personal address doesn't enter public history.
6. If "Claude attribution" is missing, ask once whether new commits and PRs should read as the user's own work, without "Co-Authored-By: Claude" or "Generated with Claude Code" lines (recommended). On a yes, merge `"attribution": {"commit": "", "pr": ""}` into the settings file the check names, keeping every other key, and say it applies from the next session.
7. Run the doctor again and show what is still missing.

Image generation needs no setup: during a run, felix-git uses Codex's image tool if this session is linked to Codex, otherwise any connected image tool, otherwise it draws images in HTML.
