# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- An evidence-first portfolio/README path with explicit feature status, real product captures and a claim ledger, without implicitly rewriting history.
- Regression tests for changed push destinations, multiple push URLs, URL rewrite round-trips, ambiguous human identities and oversized UTF-16 files.

### Fixed

- History publication now binds the effective fetch and push destinations to the repository recorded before rewriting.
- Re-attribution matches the known Claude bot name/email pair instead of a person's name or an entire email domain.
- NUL-containing historical files above the fallback text limit now make the scan incomplete instead of silently passing as clean.
- That check skips formats that are binary by design (archives, databases, fonts, compiled code, audio and video, design files), and `push` names the blocking files instead of asking whether gitleaks is installed.

## [1.4.0] - 2026-11-05

### Added

- `render.py --transparent`, for banners that sit on GitHub's own background.

### Changed

- The README guide now covers banner edges (floating, matched or framed) and requires each banner to come from the project's own logo, colours and captures, so cleaned repos don't share one look.
- felix-git's own banner is transparent, in light and dark variants.

## [1.3.0] - 2026-11-05

### Added

- `history.py structure --undo`, and a review that shows the history before and after so the owner can keep the structure or choose messages only.

## [1.2.0] - 2026-11-05

### Added

- `history.py structure`, on by default: runs of commits that built one feature go behind merge commits on the integration branch, `main` becomes one merge per released version, and versions named only in old messages become annotated tags. `verify` checks that every commit keeps its files, identity, dates and message, and that every branch keeps its content.
- `export` lists each commit's parents, version hints in its message and the versions its manifests held.
- The MIT license.

## [1.1.0] - 2026-11-05

### Changed

- Claude attribution is off by default: `apply` drops Claude's co-author, session and "Generated with" lines unless `--keep-attribution` is given.

### Added

- `apply --author` re-attributes commits Claude Code made under its own identity to the user, and `verify` accepts exactly that change.
- `doctor.py` checks Claude Code's attribution setting, `/felix-git:setup` offers to turn it off, and a cleanup writes `.claude/settings.json` and a `CLAUDE.md` rule so later sessions add none.

## [1.0.0] - 2026-11-05

### Added

- The felix-git skill: rewrites commit messages into Conventional Commits from each diff, purges personal data from history on request, scans every ref and image version, sets up branches and writes a README with a banner, real captures and a social card.
- `/felix-git:setup` and `doctor.py`: check git-filter-repo, gitleaks, the GitHub sign-in and its scopes, and optional tools, and offer to install what is missing.
- A branch and release workflow: one branch per change merged into `develop` with a merge commit, and releases through `release/x.y.z` with a changelog entry, an annotated tag and a GitHub Release.
- `release.py`: the SemVer bump and a changelog section from the commits since the last tag.
- `animate.py`: an animated WebP hero from captured frames.

[Unreleased]: https://github.com/A1bA-TroSs/felix-git/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/A1bA-TroSs/felix-git/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/A1bA-TroSs/felix-git/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/A1bA-TroSs/felix-git/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/A1bA-TroSs/felix-git/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/A1bA-TroSs/felix-git/releases/tag/v1.0.0
