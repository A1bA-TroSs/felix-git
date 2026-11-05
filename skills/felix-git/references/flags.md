# Audit and scan flags

What each field means for the owner. Anything that applies goes in the review.

## Audit report

- Open PRs: rewriting breaks their diffs, so offer merging or closing them first.
- Forks: they keep the old commits and hashes.
- Signed commits: the rewrite removes their signatures, including GitHub's own signed merge commits.
- Open PRs marked `unknown`: treat them as possibly present.
- `default_branch_stale`: the real product is on `develop` while `main` lags. See phase 4.
- Anything in `other_remote_refs`, such as `refs/notes/*`: a rewrite leaves these on the old hashes, so tell the owner. A `broken` README is a symlink to nothing; treat it as no README.
- Anything in `push_workflows`: publishing force-pushes every branch and tag, so these run again, and one with `tags` true can release again. A moved tag also breaks anyone pinning it, such as Go modules. Put this in the review, and offer disabling them first or leaving tags out.
- A nonzero `signed_tags`: rewriting strips their signatures too.
- A nonzero `hidden_pull_refs`: the host keeps those old commits reachable after a rewrite. Without `--github` they are also the only hint of open PRs.

## Scan report

- `author_emails` stays in history as the record of who wrote the code, so only flag a personal one the owner may want to know about.
- `emails` needs judging, since `emails_in_fixtures` are probably test data and the rest may be real people.
- Open what's in `unread_archives` if it's small enough, because the scan can't read inside.
- Exit 2 means the secret scan didn't run: say so plainly, never report it as clean.
- Never print a secret value or full personal address, in chat or in any file.
- For each secret hit, look at the file and variable name and classify it: a live credential, a public client key meant to ship in a page, a documentation example, or a false positive.
