# Security model

The skill reads repositories it doesn't trust and can rewrite shared history, so these are the threats it was built against.

| Threat | Control | Test or check |
|---|---|---|
| Repo text steers the agent (prompt injection in files, commits, branch names, web pages) | SKILL.md: repo content is data, only the user's words instruct; such text is reported | Instruction review |
| Repo code runs with the user's credentials (install scripts, tests, hooks) | Not run without the user's say-so; git doesn't run hooks from a clone; `core.hooksPath` is only suggested to the user | Instruction review |
| Rewritten history reaches the remote unapproved | `push` needs `--yes`; SKILL.md allows it only after a yes for that repo | `test_no_push_without_yes` |
| A push skips verify or the scan, or includes commits never checked | `push --yes` requires a passing verify for this commit map, requires each ref to hold exactly the rewritten version of its original commit, refuses any difference between the remote's branches and tags and what was cloned, and runs a fresh scan | `test_push_gates` |
| Old message text is carried into a new one (injected instruction, credential) | Only a fixed list of trailer keys carries over, and only with values shaped like an identity or issue reference, so other trailers are dropped. Attribution lines carry over only in the shapes tools write. A short name can still hold words, and the review's table shows it | `test_injected_trailer_dropped`, `test_trailer_value_with_prose_dropped` |
| A push overwrites someone's new work | Per-ref `--force-with-lease` with the recorded SHA, `--atomic` | `test_moved_branch_rejects_all` |
| A rewrite silently changes code | `verify` compares tree, author, dates and parents per commit against the bundle | `test_identity`, `test_verify_detects_tamper` |
| A token in the remote URL leaks | Stripped before saving or printing; pushes use the credential helper | `test_token_not_stored_or_printed` |
| A new message or README quotes a secret | `scan.py --also` before apply and before review | `test_scan_finds_secret_in_new_file` |
| A secret sits in an old commit message | `scan.py` scans all messages; gitleaks' git mode doesn't | `test_scan_finds_secret_in_message` |
| Secret values reach logs or reports | gitleaks `--redact`; only rule, file, line and commit are kept; emails masked | `test_scan_never_prints_value` |
| The repo switches the scan off (`.gitleaks.toml`, `.gitleaksignore`, allow comments) | Our own config and ignore path, allow comments ignored; AWS example keys reported too | `test_repo_cannot_disable_scan` |
| A commit message hides a secret or writes a file by holding a separator | Messages split on NUL; temp names only from checked SHAs; a scan crash reads as "didn't run" | `test_message_cannot_steer_scan` |
| Old hashes stay reachable through a branch created after the clone | `push` refuses when the remote has unknown branches | `test_push_refuses_new_remote_branch` |
| A skipped scan reads as clean | `scan.py` exits 2 when it can't run, `push` then always refuses, and missing `gh` data is marked unknown | `test_scan_reports_missing_gitleaks` |
| A README vouches for files outside the repo | `check_readme` confines paths to the repo | `test_readme_rejects_outside_paths` |
| Rendered HTML phones home or runs code | Scripts off and network blocked in both browser renderers, IP addresses included; the skill never renders a repo's own files | `test_render_blocks_network`, `test_webrtc_cannot_leave_over_udp` |
| Unrestorable mistake | Git bundle before any change, kept after publishing | `test_restore_from_bundle_all_branches` |
| A product capture shows the owner's real data (the app calls its hardcoded local backend, which may be live) | promotion.md: route every page request to a demo stub and abort other hosts before the first frame; check every frame | Instruction review |
| A generated image passes as proof of the product | promotion.md: generated art is decoration only, never the product's screens, people or other logos; prompts and tool listed in the review | Instruction review |
| Re-attribution changes more than Claude's own commits | `apply --author` maps only a `Claude` name or an `@anthropic.com` address, refuses an identity that is itself Claude's, and `verify` accepts exactly that change | `test_author_replaces_claude_identity_and_verify_passes`, `test_verify_catches_author_changed_beyond_claude`, `test_author_refuses_claude_or_bad_identity` |
| Restructuring changes code or drops a commit | `structure` copies each commit object byte for byte except its parent lines; `verify` checks every commit's tree, identity, dates and message, each merge's tree and identity, every branch's final content, and that no commit was dropped | `test_groups_become_merges_and_main_becomes_releases`, `test_verify_catches_a_merge_with_another_tree`, `test_bad_plans_refused` |
| A merge reports a PR live that was merged at an older head | SKILL.md phase 8: check `headRefOid` and `mergedAt` before claiming it, then a follow-up PR | Instruction review |

Bandit reports `subprocess` use as low severity by design: all calls use argument lists with no shell, and the only dynamic code is filter-repo's callback, built from a fixed string with the table path passed through `repr`.

**Not covered.** Vulnerable dependencies are reported by `osv-scanner` when installed, not fixed. A message-only rewrite removes nothing from history; only a purge does. Forks and GitHub's caches keep old commits. Secrets inside images are found only by looking. The secret scan doesn't read author names, tag or branch names, or objects behind a tag of a blob, and gitleaks' default path list skips paths such as `node_modules/`, images and lockfiles such as `package-lock.json`. Files with NUL bytes are read with the NULs removed, up to the text size limit.
