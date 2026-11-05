# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-11-05

### Added

- The felix-git skill: rewrites commit messages into Conventional Commits from each diff, purges personal data from history on request, scans every ref and image version, sets up branches and writes a README with a banner, real captures and a social card.
- `/felix-git:setup` and `doctor.py`: check git-filter-repo, gitleaks, the GitHub sign-in and its scopes, and optional tools, and offer to install what is missing.
- A branch and release workflow: one branch per change merged into `develop` with a merge commit, and releases through `release/x.y.z` with a changelog entry, an annotated tag and a GitHub Release.
- `release.py`: the SemVer bump and a changelog section from the commits since the last tag.
- `animate.py`: an animated WebP hero from captured frames.

[Unreleased]: https://github.com/A1bA-TroSs/felix-git/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/A1bA-TroSs/felix-git/releases/tag/v1.0.0
