# Branch, merge and release workflow

How teams that ship versioned software actually move code: one branch per change, merged into `develop` with a merge commit, and a release branch that carries a version, a changelog entry and a tag into `main`. Read this before phase 4. What this guide sets up stays after the cleanup through the `CLAUDE.md` rule in phase 6.

## 1. Pick the model from how the project ships

| Project ships as | Model | Integration branch |
|---|---|---|
| Versions people install (app, library, CLI), or more than one version in use | git-flow below | `develop` |
| A live site or service deployed from `main`, one version in use | GitHub flow: short branches into `main`, no `develop` | `main` |

The author of git-flow said in 2020 that it suits explicitly versioned software, and that continuously delivered web apps are better served by the simpler GitHub flow. Say which you chose and why in the review.

## 2. Branches

| Branch | Cut from | Merges into | Lives |
|---|---|---|---|
| `main` | | | always; every commit on it is a release, each tagged |
| `develop` | `main` | `main` through `release/*` | always; the next release |
| `feature/<what>` | `develop` | `develop` | until its PR merges, then deleted |
| `fix/<what>`, `docs/<what>`, `chore/<what>`, `refactor/<what>` | `develop` | `develop` | same |
| `release/<x.y.z>` | `develop` | `main`, then back into `develop` | until tagged |
| `hotfix/<x.y.z>` | the tag on `main` | `main`, then `develop` (or the open release branch) | until tagged |

- **One branch per change.** A separate branch for each set of unrelated changes, as GitHub's own guide puts it: focused review, a change can be reverted or built on alone, and a slow one doesn't hold up the rest. Never one long branch that collects everything.
- **Names** are the Conventional Commit type plus a few words in kebab case: `feature/morning-report`, `fix/thread-join-subject`, `docs/readme-banner`. Agent tools' own branch names (`claude/...`, `codex/...`) are renamed to this form before the PR, or the work is moved to a properly named branch.
- **Commits inside a branch** are Conventional Commits, each one isolated, complete change.

## 3. Merging into `develop`

- Open a PR from the branch into `develop`. Title it like a Conventional Commit (`feat(report): replace the briefing with a morning report`), and in the body say what changed, why and how it was tested.
- Merge with a **merge commit** (`git merge --no-ff`, GitHub's "Create a merge commit"), not squash or rebase, in this model. The merge commit keeps the branch visible in the graph as one bubble per feature and lets the whole feature be reverted at once with `git revert -m 1 <merge>`. That's why git-flow insists on `--no-ff`.
- Delete the branch after merging. The PR and its commits stay.
- Under GitHub flow, squash merging into `main` is fine if the team prefers one commit per PR. Then the PR title is the commit message, so it must be a Conventional Commit.

## 4. Releasing

1. `scripts/release.py work --to develop` plans it. It reads the commits since the last `vX.Y.Z` tag, picks the SemVer bump from their types (breaking change: major, `feat`: minor, otherwise patch; a breaking change before 1.0.0 is minor), and drafts the changelog section. With no version tag yet, pass `--current` with the version the manifests hold. If the manifests already claim a version the commits don't support, say so and let the owner choose.
2. Cut `release/<x.y.z>` from `develop`. On it, and nowhere else:
   - Bump every place that states the version: find them with `git grep -n "<current version>"` (package.json, pyproject.toml, Cargo.toml, a config constant, an app bundle's Info.plist).
   - Prepend the section to `CHANGELOG.md` in Keep a Changelog form: an `## [Unreleased]` heading on top, then `## [x.y.z] - YYYY-MM-DD` with Added, Changed, Deprecated, Removed, Fixed and Security, and a compare link per version at the bottom. Edit the draft: merge duplicates and write for users, not committers. Move security fixes to Security.
   - Only fixes for the release go on this branch; new features wait for `develop`.
3. PR `release/<x.y.z>` into `main`, titled `release: v<x.y.z>`, merged with a merge commit.
4. Tag the merge commit, annotated: `git tag -a v<x.y.z> -m "v<x.y.z>" <merge sha>` and `git push origin v<x.y.z>`.
5. Publish a GitHub Release from the tag: `gh release create v<x.y.z> --title v<x.y.z> --notes-file <the changelog section>`, plus build artifacts if the project ships any. `--generate-notes` instead lists the merged PRs, grouped by the labels in `.github/release.yml` (`assets/release.yml`).
6. Merge `main` back into `develop`, so the version bump and any release fixes aren't lost at the next release. Then delete the release branch.

A hotfix follows the same steps from the tag on `main`, with a patch bump, and is merged into `develop` afterwards (or into the open release branch, which carries it to `develop`).

## 5. The data a release lives in

| Where | What it holds | Who reads it |
|---|---|---|
| Annotated tag `vX.Y.Z` | the exact commit released, who tagged it and when | git, CI, package managers, `release.py` |
| `CHANGELOG.md` | what changed for users, per version, newest first | users upgrading |
| GitHub Release | notes, contributors, compare link, downloadable builds | the repo page's Releases panel |
| Version fields in manifests | the version the built product reports | the product itself, package registries |
| PR labels (`enhancement`, `bug`, `documentation`, `breaking-change`) | the change's kind | `.github/release.yml` for generated notes |
| Merge commits on `develop` and `main` | which branch brought which commits | the graph, `git log --first-parent` |

`git log --first-parent main` lists one line per release, and `--first-parent develop` one line per merged feature. That's the structure this workflow builds.

## 6. Repository settings to recommend

The owner decides these; list them in the review and change none without a yes:
- Keep "Allow merge commits" on. Under git-flow, turn squash and rebase merging off so every PR leaves its bubble.
- "Automatically delete head branches" on.
- Branch protection or a ruleset on `main` and `develop`: changes only through PRs, and passing checks when CI exists.
- Labels for the release notes categories, if the owner wants generated notes.

## 7. The cleanup's own changes follow the same rules

Don't put everything the cleanup adds on one branch. Split it by concern, each cut from `develop` and opened as its own PR into `develop`, merged with a merge commit in this order:

| Branch | Holds |
|---|---|
| `chore/git-hygiene` | `.gitignore` additions, untracking junk, `.githooks/commit-msg`, PR template, `.github/release.yml`, `.claude/settings.json` with attribution off, the `CLAUDE.md` git section |
| `docs/readme` | README and `docs/readme/` images |
| `fix/<what>` | any public text that was false, such as a manifest's description |
| `chore/changelog` | a first `CHANGELOG.md`, when the owner wants one, built from the rewritten history |

Then, if the owner approved a release, follow section 4 to put it on `main`.

## 8. Restructuring past history

Vibe-coded history is usually one straight line of commits named "fixed" or "v1.25", with no branches and no tags. `history.py structure` turns it into the shape this guide describes, after the messages are rewritten:

```
before   o--o--o--o--o--o--o   develop     ("fixed", "fixed", "v1.0", ...)

after    o-----M-----M--o-----M   develop
          \   / \   /    \   /
           o-o   o-o      o-o   feature/<x>, fix/<y>: the same commits, now inside merge bubbles
         o--------R1-------R2     main: one merge per released version, tagged v1.0.0, v1.1.0
```

- Each run of commits that built one thing gets a merge commit with the same tree as its last commit, carrying that commit's identity and date. So `git log --first-parent develop` reads one line per feature.
- Versions named in old messages become annotated tags and, for versions `main` held, release merges on `main`. Then `CHANGELOG.md` and GitHub Releases can be built from them (section 4).
- What changes: the parents of commits, so every hash after the first group changes, as it already does after a message rewrite. What doesn't: every commit's files, author, dates and message, and every branch's final content. `verify` checks all of that against the backup bundle.
- Cost: no extra reading. The grouping comes from the diffs already read for the messages, and the rebuild is plain git object writes.

## Sources

- git-flow, with the 2020 note on when not to use it: https://nvie.com/posts/a-successful-git-branching-model/
- GitHub flow: https://docs.github.com/en/get-started/using-github/github-flow
- Generated release notes and `.github/release.yml`: https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes
- Keep a Changelog 1.1.0: https://keepachangelog.com/en/1.1.0/
- Conventional Commits and SemVer: https://www.conventionalcommits.org/en/v1.0.0/ , https://semver.org/
- Plumbing used by the rebuild: https://git-scm.com/docs/git-hash-object , https://git-scm.com/docs/git-update-ref
