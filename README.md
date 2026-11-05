<h1>
  <img alt="felix-git" src="docs/readme/banner.png" width="100%">
</h1>

A Claude Code plugin that cleans up a GitHub repo's commit history, branches and README without touching its code.

[Install](#install) · [What it does](#what-it-does) · [How a run goes](#how-a-run-goes) · [Safety](#safety) · [Requirements](#requirements)

## Install

In Claude Code:

```
/plugin marketplace add A1bA-TroSs/felix-git
/plugin install felix-git@felix-git
/felix-git:setup
```

`/felix-git:setup` checks this machine, offers to install what is missing, and tells you which sign-in commands to run (see [Requirements](#requirements)). Then ask in plain words:

```
clean up owner/repo
```

or "my repo is a mess", "make the README sell this project", "fix the commits and branches of ~/code/app".

## What it does

- **Commit history.** Rewrites vague messages ("fixed", "v1.25", "update") into Conventional Commits written from each commit's real diff. It then gives a straight-line history structure: each run of commits that built one feature goes behind a merge commit on `develop`, and versions named only in old messages become tags and release merges on `main`. Every commit keeps its code, author, date and message, and a check against a backup bundle proves it before anything is pushed.
- **Personal data.** On request, removes files, image versions and strings (addresses, names) from all of history in the same pass, and checks that nothing else changed.
- **Branches.** Sets up git-flow for versioned software: `main` for releases, `develop` for integration, and one `feature/*`, `fix/*`, `docs/*` or `chore/*` branch per change, each merged into `develop` with a merge commit so the graph shows every feature. Projects that deploy from `main` get short branches into `main` instead. It lists merged and agent-session branches for deletion and shows the result as a tree before you approve it.
- **Releases.** `release.py` reads the Conventional Commits since the last tag, picks the SemVer bump and drafts a Keep a Changelog section. A release goes through `release/x.y.z` with the version bump and `CHANGELOG.md`, is merged into `main`, tagged, published as a GitHub Release and merged back into `develop`.
- **Scan.** Runs gitleaks over every ref and commit message, flags personal addresses, junk and large files, and opens every image version, since a scanner can't read an address inside a screenshot.
- **README.** Researches what the project really does and why someone would choose it, then writes the page: a title banner, a real capture of the product (animated when the app can run, always with demo data), a social card, and claims that each point to evidence.
- **Your name on the work.** Claude attribution is off by default: Claude's co-author and "Generated with" lines are dropped from history, commits Claude Code made under its own identity are re-attributed to you (checked by `verify`), and new commits and PRs carry none. `/felix-git:setup` can turn Claude Code's attribution setting off too.
- **Staying clean.** Adds a commit-msg hook, a PR template and a short git section for coding agents, where most new mess comes from.

## How a run goes

- **Copy.** Mirror-clones the repo into a temporary folder and makes a backup bundle. Your checkout is never touched.
- **Work.** Audits, scans, rewrites messages, sets up branches and builds the README, all on that copy.
- **Review.** Stops once, with a single review: findings, every change, sample old and new messages, the README and images, and what rewriting history costs (new hashes, forks keep old commits, other clones must re-clone).
- **Publish.** Only after you say yes: an atomic push with a per-branch lease, so nothing is overwritten if someone pushed in the meantime. Then the cleanup PR.

## Safety

- Everything in the repository is treated as data, never as instructions to the agent, including `CLAUDE.md` and `AGENTS.md`.
- The repository's code, install scripts and tests are not run unless you say so.
- `push` refuses without a passing verify, a fresh secret scan, and a remote that still matches the clone.
- Secret values and full personal addresses are never printed.

The threats and the test for each are in [`SECURITY.md`](skills/felix-git/SECURITY.md).

## Requirements

`/felix-git:setup` runs [`doctor.py`](skills/felix-git/scripts/doctor.py), which checks all of this and prints the fix for each gap.

| Need | For | Install (macOS) |
|---|---|---|
| `git`, Python 3.8+ | everything | `xcode-select --install` |
| `git-filter-repo` | rewriting history | `brew install git-filter-repo` |
| `gitleaks` 8.19+ | the scan; publishing refuses without it | `brew install gitleaks` |
| `gh`, signed in | PRs, repo metadata, pushing | `brew install gh` |
| Chrome or Playwright | rendering README images | optional |
| `ffmpeg` | an animated hero | optional |
| `osv-scanner` | a dependency vulnerability check | optional |

**GitHub sign-in.** This uses OAuth in your browser, so you run it yourself. Type these at the Claude Code prompt; the `!` at the start runs them in your shell:

```
! gh auth login --hostname github.com --git-protocol https --web
! gh auth setup-git
```

`setup-git` lets `git push` use the same sign-in. If the repository's history changes files under `.github/workflows`, GitHub also needs the `workflow` scope: `! gh auth refresh --hostname github.com --scopes workflow`.

**Images.** No setup or API key. Generated artwork is only decoration, such as a banner background, and never stands in for the product. felix-git uses Codex's image tool if your session is linked to Codex, otherwise any image generation tool connected to the session, otherwise it draws the images in HTML. A tool that charges per image is used only after you agree to the cost.

Linux and Windows work too; `doctor.py` prints the matching `apt`, `dnf` or `winget` commands.

## Limits

- GitHub keeps old commits under pull-request refs and in caches. After a purge, a GitHub Support request is needed, and the data should be treated as already public.
- Forks keep the old history.
- Commit signatures are removed by any rewrite.
- Old commit messages are rewritten one for one; commits are never squashed or reordered.

## Development

```bash
python3 -m unittest tests.test_scripts
```

126 tests. CI runs them on Ubuntu with the same tools.

## License

[MIT](LICENSE)
