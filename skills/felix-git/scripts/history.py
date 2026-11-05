#!/usr/bin/env python3
"""History rewrite: every commit keeps its parents' shape, author and dates, and its tree unless a purge
the owner approved says otherwise.

  history.py origin <clone>                         print the origin URL with any credential removed
  history.py export <clone> --out commits.json [--scan scan.json]
                                                    commits to rename, with a diffstat of each; messages
                                                    the scan flagged come back withheld
  history.py apply  <clone> --messages messages.json [--drop-attribution] [--purge purge.json]
  history.py verify <clone> --bundle backup.bundle  compare rewritten commits with the originals
  history.py table  <clone> --commits commits.json --out old-to-new.md
  history.py push   <clone> [--yes] [--accept-findings]
                                                    show the push plan; push it only with --yes, after a
                                                    passing verify and a fresh scan of the clone

messages.json maps an old full SHA to its new message. Commits not listed keep their message.
purge.json removes data in the same pass: {"paths": ["dir/", "file"], "blobs": ["<full id>"],
"replace": [{"old": "text", "new": "text"}]}. Replacements are literal and also apply to messages.
Trailers such as Co-authored-by are carried over unless --drop-attribution is given.
Work in a fresh clone: filter-repo removes origin, so apply records it in .git/felix-git.json,
with any credential stripped from the URL. Pushing then uses the normal git credential helper.
"""
import argparse, hashlib, json, re, shutil, subprocess, sys
from pathlib import Path

# Only known keys: any other "Word: text" line is old prose, possibly an injected instruction or a credential.
# Keys and value shapes both: a free-form value would carry injected prose into the new message.
ISSUE = r"(?:#\d+|[\w.-]+/[\w.-]+#\d+|[A-Z][A-Z0-9]+-\d+|https?://[^\s@]+/\d+|[0-9a-f]{7,40})"
TRAILER = re.compile(r"^(?:(?:Co-authored-by|Signed-off-by|Reviewed-by|Acked-by|Tested-by|Reported-by|Suggested-by|Helped-by): [^<>:\s]+(?: [^<>:\s]+){0,3} <[^<>\s]+@[^<>\s]+>"
                     rf"|Change-Id: I[0-9a-f]+|(?:Fixes|Closes|Refs): {ISSUE}(?:,\s*{ISSUE})*)$", re.I)
CONVENTIONAL = re.compile(r"^(feat|fix|refactor|docs|chore|test|perf|build|ci|style|revert)(\([^)]+\))?!?: \S")
# What may carry over: the shapes tools really write, so an injected sentence in one of these keys stays behind.
KEEP_ATTR = re.compile(r"^(Claude-Session: (https?://[^\s@]+|[\w-]+)|🤖? *Generated with \[?Claude Code\]?(\(https?://[^\s@)]+\))?)$", re.I)
ATTR = re.compile(r"^(Co-Authored-By: *Claude.*|Claude-Session: .*|🤖? *Generated with \[?Claude.*)$", re.I)


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, errors="replace")
    if check and r.returncode:
        sys.exit(f"git {args[0]} failed: {strip_credentials(r.stderr.strip())}")
    return r.stdout.strip()


# Ref names may hold characters str.splitlines and str.split treat as breaks, such as U+2028 and U+00A0.
def lines(text):
    return [l for l in text.split("\n") if l]


def strip_credentials(url):
    def clean(m):
        # ssh://git@host names a user, not a secret; anything else before the @ goes.
        if m[1].lower().startswith("ssh") and ":" not in m[2]:
            return m[0]
        return m[1]
    # Greedy to the last @ in the authority, as a password can hold an unencoded @.
    text = re.sub(r"([a-z][a-z0-9+.-]*://)([^/\s]*)@", clean, url or "", flags=re.I)
    text = re.sub(r"(://[^\s?#;]*)[?#;]\S*", r"\1", text)
    # scp-style remotes have no scheme: user:token@host:path
    text = re.sub(r"(?<![\w/:.@-])[\w.-]+:[^/\s@]+@(?=[\w.-]+:)", "", text)
    # In user@host:path only git@ is a plain login; any other user may be a token.
    return re.sub(r"(?<![\w/:.@-])(?!git@)[\w.-]+@(?=[\w.-]+:)", "", text)


def state_path(repo):
    return Path(git(repo, "rev-parse", "--absolute-git-dir")) / "felix-git.json"


def trailers(message):
    lines = message.rstrip().splitlines()
    out = []
    for line in reversed(lines):
        if not line.strip():
            break
        if TRAILER.match(line) or KEEP_ATTR.match(line):
            out.insert(0, line)
    return out if len(lines) > len(out) else []


def final_message(old, new, drop):
    carried = trailers(old)
    new = new.rstrip()
    if drop:
        new = "\n".join(l for l in new.splitlines() if not ATTR.match(l)).rstrip()
        carried = [t for t in carried if not ATTR.match(t)]
    extra = [t for t in carried if t not in new]
    return new + ("\n\n" + "\n".join(extra) if extra else "") + "\n"


WITHHELD = "(withheld: the scan flagged a secret in this message)"


def digest(text):
    return hashlib.sha256(text.strip().encode("utf-8", "surrogateescape")).hexdigest()


def flagged_commits(path):
    if not path:
        return set()
    try:
        return {f["commit"] for f in json.loads(Path(path).read_text(encoding="utf-8"))["message_secrets"]}
    except (OSError, ValueError, KeyError, TypeError) as e:
        sys.exit(f"can't read the scan report {path}: {e}")


def cmd_origin(a):
    print(strip_credentials(git(a.repo, "remote", "get-url", "origin")))


def cmd_export(a):
    flagged = flagged_commits(a.scan)
    rows = []
    for sha in git(a.repo, "rev-list", "--all", "--reverse", "--topo-order").splitlines():
        parents = git(a.repo, "log", "-1", "--format=%P", sha).split()
        message = git(a.repo, "log", "-1", "--format=%B", sha)
        rows.append({
            "sha": sha,
            "is_merge": len(parents) > 1,
            "date": git(a.repo, "log", "-1", "--format=%as", sha),
            "message": WITHHELD if sha[:10] in flagged else message,
            "stat": git(a.repo, "show", "--stat=120", "--format=", "--no-color", sha),
        })
        if sha[:10] in flagged:
            rows[-1]["message_digest"] = digest(message)
    if not rows:
        sys.exit("this repository has no commits, so there is nothing to rewrite")
    Path(a.out).write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(rows)} commits, {sum(r['is_merge'] for r in rows)} merges -> {a.out}")


def check_messages(mapping):
    """Bad messages are cheap to fix now; after apply the clone can't be rewritten again."""
    problems = []
    for sha, message in mapping.items():
        if not isinstance(message, str):
            problems.append(f"{sha[:10]}: message must be text")
            continue
        if re.search(r"[\x00-\x08\x0b-\x1f\x7f]", message.replace("\r\n", "\n")):
            problems.append(f"{sha[:10]}: message holds control characters")
            continue
        subject = message.splitlines()[0] if message.strip() else ""
        if not CONVENTIONAL.match(subject):
            problems.append(f"{sha[:10]}: subject is not Conventional Commits: {subject[:80]!r}")
        elif len(subject) > 72:
            problems.append(f"{sha[:10]}: subject is {len(subject)} characters, limit 72")
    return problems


def load_purge(path):
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"can't read {path}: {e}")
    if not isinstance(spec, dict) or set(spec) - {"paths", "blobs", "replace"}:
        sys.exit(f"{path} may only hold paths, blobs and replace")
    spec = {"paths": spec.get("paths", []), "blobs": spec.get("blobs", []), "replace": spec.get("replace", [])}
    # A string here would be read one character at a time and purge the wrong files.
    if not all(isinstance(v, list) for v in spec.values()):
        sys.exit(f"{path}: paths, blobs and replace must each be a list, nothing was rewritten")
    bad = [p for p in spec["paths"] if not isinstance(p, str) or not p.strip("/") or p.startswith("/") or ".." in p.split("/")]
    bad += [b for b in spec["blobs"] if not isinstance(b, str) or not re.fullmatch(r"[0-9a-f]{40}", b)]
    for rule in spec["replace"]:
        old, new = (rule.get("old"), rule.get("new")) if isinstance(rule, dict) else (None, None)
        # filter-repo reads these as lines of "old==>new", so either would change what the rule means.
        if not (isinstance(old, str) and isinstance(new, str)) or not old or old in new \
                or any(x in old + new for x in ("==>", "\n", "\r")):
            bad.append("a replace rule")
    if bad or not any(spec.values()):
        sys.exit(f"{path} is not a usable purge, nothing was rewritten: {len(bad)} bad entries")
    return spec


def purge_args(repo, spec):
    gitdir = Path(git(repo, "rev-parse", "--absolute-git-dir"))
    args = ["--prune-empty", "never", "--prune-degenerate", "never"]
    if spec["paths"]:
        args += ["--invert-paths"]
        for path in spec["paths"]:
            args += ["--path", path.rstrip("/") + ("/" if path.endswith("/") else "")]
    if spec["blobs"]:
        (gitdir / "felix-git-blobs").write_text("\n".join(spec["blobs"]) + "\n")
        args += ["--strip-blobs-with-ids", str(gitdir / "felix-git-blobs")]
    if spec["replace"]:
        rules = "".join(f"literal:{r['old']}==>{r['new']}\n" for r in spec["replace"])
        (gitdir / "felix-git-replace").write_text(rules, encoding="utf-8")
        args += ["--replace-text", str(gitdir / "felix-git-replace"), "--replace-message", str(gitdir / "felix-git-replace")]
    return args


def is_purged(path, oid, spec):
    return oid in spec["blobs"] or any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/") for p in spec["paths"])


def blob_bytes(repo, oid):
    return subprocess.run(["git", "-C", repo, "cat-file", "blob", oid], capture_output=True).stdout


def tree_entries(repo, commit):
    raw = subprocess.run(["git", "-C", repo, "ls-tree", "-r", "-z", commit], capture_output=True).stdout
    entries = {}
    for item in filter(None, raw.split(b"\0")):
        meta, path = item.split(b"\t", 1)
        mode, _, oid = meta.decode().split()
        entries[path.decode("utf-8", "surrogateescape")] = (mode, oid)
    return entries


EMPTY_BLOB = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


def encodings(literal):
    """The forms a literal can take in a file filter-repo treats as binary and so never rewrites."""
    forms = {literal.encode(), literal.encode("utf-16-le"), literal.encode("utf-16-be")}
    try:
        forms.add(literal.encode("latin-1"))
    except UnicodeEncodeError:
        pass
    return forms


def purge_problems(original, repo, old, new, spec, seen, matched):
    """What differs between two commits beyond the purge. Filter-repo leaves binary files alone, so this does too.
    Records in matched which purge entries met something, so an entry that matched nothing can fail verify."""
    rules = [(r["old"].encode(), r["new"].encode()) for r in spec["replace"]]
    before, after = tree_entries(original, old), tree_entries(repo, new)
    problems = [f"{p}: not in the original commit" for p in after.keys() - before.keys()]
    for path, (mode, oid) in before.items():
        if ("orig", oid) not in seen:
            data = blob_bytes(original, oid)
            seen[("orig", oid)] = {r["old"] for r in spec["replace"] if any(f in data for f in encodings(r["old"]))}
        matched.update(("replace", lit) for lit in seen[("orig", oid)])
        matched.update(("paths", p) for p in spec["paths"] if path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/"))
        if oid in spec["blobs"]:
            matched.add(("blobs", oid))
        if is_purged(path, oid, spec):
            if oid not in spec["blobs"] and oid != EMPTY_BLOB:
                seen.setdefault("removed", set()).add(oid)
            if path in after:
                problems.append(f"{path}: should have been purged")
            continue
        if path not in after:
            problems.append(f"{path}: missing and not in the purge")
        elif after[path][0] != mode:
            problems.append(f"{path}: mode changed")
        elif after[path][1] != oid:
            pair = (oid, after[path][1])
            if pair not in seen:
                data = blob_bytes(original, oid)
                if b"\0" not in data[:8192]:
                    for literal, replacement in rules:
                        data = data.replace(literal, replacement)
                seen[pair] = data == blob_bytes(repo, after[path][1])
            if not seen[pair]:
                problems.append(f"{path}: changed beyond the replace rules")
    for path, (_, oid) in after.items():
        seen.setdefault("kept", {}).setdefault(oid, path)
        if oid not in seen:
            data = blob_bytes(repo, oid)
            seen[oid] = any(f in data for r in spec["replace"] for f in encodings(r["old"]))
        if seen[oid]:
            problems.append(f"{path}: still holds replaced text")
    return problems


def cmd_apply(a):
    if state_path(a.repo).exists() or (Path(git(a.repo, "rev-parse", "--absolute-git-dir")) / "filter-repo").exists():
        sys.exit("apply already ran on this clone. Fix messages.json, clone the remote again, "
                 "and apply there. The remote has not been touched.")
    if not shutil.which("git-filter-repo"):
        sys.exit("git-filter-repo is not installed (brew install git-filter-repo, or pip install git-filter-repo)")
    if not git(a.repo, "rev-list", "--all", "--max-count=1", check=False):
        sys.exit("this repository has no commits, so there is nothing to rewrite")
    if git(a.repo, "status", "--porcelain"):
        hint = " Files differing only by case do this on a case-insensitive disk; clone onto a case-sensitive volume." \
            if git(a.repo, "config", "core.ignorecase", check=False) == "true" else ""
        sys.exit("working tree is not clean." + hint)
    try:
        mapping = json.loads(Path(a.messages).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"can't read {a.messages}: {e}")
    if not isinstance(mapping, dict):
        sys.exit(f"{a.messages} must map old SHAs to new messages")
    problems = check_messages(mapping)
    if problems:
        sys.exit("fix these messages, nothing was rewritten:\n" + "\n".join(problems))
    purge = load_purge(a.purge) if a.purge else None
    origin = git(a.repo, "remote", "get-url", "origin", check=False)
    refs = {}
    for line in lines(git(a.repo, "for-each-ref", "--format=%(objectname) %(refname)", "refs/remotes/origin", "refs/heads", "refs/tags")):
        sha, ref = line.split(" ", 1)
        if ref != "refs/remotes/origin/HEAD":
            refs[ref] = sha
    # A fresh clone has only one local branch; every remote branch must be rewritten too.
    for ref in refs:
        if ref.startswith("refs/remotes/origin/"):
            name = ref[len("refs/remotes/origin/"):]
            if not git(a.repo, "rev-parse", "--verify", "-q", f"refs/heads/{name}", check=False):
                if name.startswith("-"):
                    sys.exit(f"remote branch {name!r} can't be checked out by git. Rename it on the remote and clone again. Nothing changed.")
                git(a.repo, "branch", "--no-track", name, ref)
    originals = {}
    for sha in git(a.repo, "rev-list", "--all").splitlines():
        # surrogateescape keeps non-UTF-8 bytes intact through the JSON table.
        originals[sha] = subprocess.run(["git", "-C", a.repo, "log", "-1", "--format=%B", sha],
                                        capture_output=True).stdout.decode("utf-8", "surrogateescape").rstrip("\n")
    unknown = sorted(set(mapping) - set(originals))
    if unknown:
        sys.exit(f"messages.json names unknown commits: {unknown[:5]}")
    # filter-repo updates hashes quoted in messages it keeps, but not in ones swapped in here, so they would dangle.
    quoting = sorted(s for s, m in mapping.items() if isinstance(m, str)
                     and any(o.startswith(h) for h in re.findall(r"\b[0-9a-f]{7,40}\b", m) for o in originals))
    if quoting:
        sys.exit(f"these new messages quote a commit hash, which the rewrite changes; say it in words: {quoting[:5]}")
    resolved = {s: final_message(originals[s], mapping.get(s, originals[s]), a.drop_attribution)
                if s in mapping or (a.drop_attribution and any(ATTR.match(l) for l in originals[s].splitlines()))
                else None for s in originals}
    if purge:
        # filter-repo replaces text in messages before the callback swaps in these, so they need it here too.
        for s_ in resolved:
            for rule in purge["replace"] if resolved[s_] is not None else []:
                resolved[s_] = resolved[s_].replace(rule["old"], rule["new"])
    table = Path(git(a.repo, "rev-parse", "--absolute-git-dir")) / "felix-git-messages.json"
    table.write_text(json.dumps({k: v for k, v in resolved.items() if v}), encoding="utf-8")
    callback = (
        "import json\n"
        f"table = globals().setdefault('_t', json.load(open({str(table)!r}, encoding='utf-8')))\n"
        "m = table.get(commit.original_id.decode())\n"
        "if m is not None:\n"
        "    commit.message = m.encode('utf-8', 'surrogateescape')\n"
    )
    # The commit each ref holds, peeled through annotated tags, so push can check it against the map.
    tips = {ref: git(a.repo, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}", check=False) for ref in refs}
    if purge and not all(tips.values()):
        # filter-repo leaves a tag on a blob or tree alone, so it would keep purged data public.
        sys.exit(f"these refs point at no commit, so a purge can't reach them: {', '.join(r for r, t in tips.items() if not t)}. "
                 "Nothing was rewritten.")
    before = {"origin": strip_credentials(origin), "refs": refs, "tips": tips, "commits": list(originals), "purge": purge}
    state_path(a.repo).write_text(json.dumps(before))
    r = subprocess.run(["git", "filter-repo", "--commit-callback", callback, *(purge_args(a.repo, purge) if purge else [])],
                       cwd=a.repo, capture_output=True, text=True, errors="replace")
    for name in ("felix-git-replace", "felix-git-blobs"):
        (Path(git(a.repo, "rev-parse", "--absolute-git-dir")) / name).unlink(missing_ok=True)
    if r.returncode:
        state_path(a.repo).unlink(missing_ok=True)
        if "--no-local" in r.stderr + r.stdout:
            sys.exit("filter-repo refused this clone and nothing changed. If it came from a local path, clone with: "
                     f"git clone --no-local <path> work\nIts reason: {strip_credentials(r.stderr.strip() or r.stdout.strip())}")
        sys.exit("rewrite failed, the remote is untouched. Clone the remote again and retry.\n"
                 + strip_credentials(r.stderr.strip() or r.stdout.strip()))
    print(f"rewrote {sum(1 for v in resolved.values() if v)} messages; run verify next")


def commit_map(repo):
    path = Path(git(repo, "rev-parse", "--absolute-git-dir")) / "filter-repo" / "commit-map"
    rows = {}
    if not path.exists():
        return rows
    for line in path.read_text().splitlines()[1:]:
        old, new = line.split()
        rows[old] = new
    return rows


def map_digest(repo):
    path = Path(git(repo, "rev-parse", "--absolute-git-dir")) / "filter-repo" / "commit-map"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cmd_verify(a):
    """Compares against the bundle made before the rewrite, which still holds the old objects."""
    bundle = Path(a.bundle).resolve()
    if not bundle.is_file():
        sys.exit(f"no backup bundle at {bundle}")
    if not commit_map(a.repo):
        sys.exit("nothing to verify: apply has not run on this clone")
    # A verify that stops early must not leave an earlier pass standing.
    if state_path(a.repo).exists():
        st = json.loads(state_path(a.repo).read_text())
        st["verified"] = None
        state_path(a.repo).write_text(json.dumps(st))
    tmp = Path(git(a.repo, "rev-parse", "--absolute-git-dir")) / "felix-git-original"
    if tmp.exists():
        shutil.rmtree(tmp)
    r = subprocess.run(["git", "clone", "-q", "--mirror", str(bundle), str(tmp)], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"can't read the backup bundle {bundle}: {r.stderr.strip()[:200]}")
    fmt = "%T%x00%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI"
    fail, checked, renamed = [], 0, 0
    cmap = commit_map(a.repo)
    purge = json.loads(state_path(a.repo).read_text()).get("purge") if state_path(a.repo).exists() else None
    seen, matched = {}, set()
    for old, new in cmap.items():
        checked += 1
        o = git(str(tmp), "log", "-1", f"--format={fmt}", old, check=False)
        n = git(a.repo, "log", "-1", f"--format={fmt}", new, check=False)
        if purge and o and n:
            if o.split("\0")[1:] != n.split("\0")[1:]:
                fail.append({"old": old, "new": new, "why": "author or date differs"})
            fail += [{"old": old, "new": new, "why": why} for why in purge_problems(str(tmp), a.repo, old, new, purge, seen, matched)]
            original = git(str(tmp), "log", "-1", "--format=%B%n%an%n%ae%n%cn%n%ce", old)
            matched.update(("replace", r["old"]) for r in purge["replace"] if r["old"] in original)
            message = git(a.repo, "log", "-1", "--format=%B", new)
            if any(r["old"] in message for r in purge["replace"]):
                fail.append({"old": old, "new": new, "why": "message still holds replaced text"})
            # A purge rewrites file text and messages, never who made the commit.
            if any(r["old"] in n for r in purge["replace"]):
                fail.append({"old": old, "new": new, "why": "author or committer holds replaced text; a purge can't change it"})
        elif not o or o != n:
            same_tree = o.split("\0")[0] == n.split("\0")[0] if o and n else False
            fail.append({"old": old, "new": new, "why": "author or date differs" if same_tree else
                         "tree differs. If this commit has an old 100664 file mode, the rewrite normalises it, so this repo can't be rewritten message-only"})
        if not o:
            fail.append({"old": old, "new": new, "why": "this commit isn't in the bundle; is it the right one?"})
            continue
        op = [cmap.get(p, p) for p in git(str(tmp), "log", "-1", "--format=%P", old).split()]
        if op != git(a.repo, "log", "-1", "--format=%P", new).split():
            fail.append({"old": old, "new": new, "why": "parents differ"})
        renamed += git(str(tmp), "log", "-1", "--format=%B", old) != git(a.repo, "log", "-1", "--format=%B", new)
    if purge:
        kept = seen.get("kept", {})
        fail += [{"purge": kept[oid], "why": "holds the same content as a purged path; add it to the purge"}
                 for oid in sorted(seen.get("removed", set()) & kept.keys())]
        for kind in ("paths", "blobs"):
            fail += [{"purge": f"{kind}: {e}", "why": "matched nothing in history; check its spelling and case"}
                     for e in purge[kind] if (kind, e) not in matched]
        fail += [{"purge": "a replace rule", "why": "its text appears nowhere in history; check it"}
                 for r in purge["replace"] if ("replace", r["old"]) not in matched]
        for line in lines(git(a.repo, "for-each-ref", "--format=%(refname) %(taggername) %(taggeremail)", "refs/tags")):
            if any(r["old"] in line for r in purge["replace"]):
                fail.append({"purge": line.split()[0], "why": "the tagger holds replaced text; a purge can't change it"})
    shutil.rmtree(tmp)
    print(json.dumps({"checked": checked, "messages_changed": renamed, "failures": fail}, indent=1))
    if state_path(a.repo).exists():
        st = json.loads(state_path(a.repo).read_text())
        st["verified"] = map_digest(a.repo) if checked and not fail else None
        # A replaced annotated tag holds the same commit but a new message, so record the tag objects too.
        st["verified_tags"] = dict(reversed(l.split(" ", 1)) for l in lines(git(a.repo, "for-each-ref", "--format=%(objectname) %(refname)", "refs/tags")))
        state_path(a.repo).write_text(json.dumps(st))
    sys.exit(1 if fail or not checked else 0)


def cmd_table(a):
    if not commit_map(a.repo):
        sys.exit("no table yet: apply has not run on this clone")
    rows = json.loads(Path(a.commits).read_text(encoding="utf-8"))
    cmap = commit_map(a.repo)
    out = ["| old | new | old message | new message |", "|---|---|---|---|"]
    cell = lambda t: t.strip().replace("|", "\\|").replace("\n", "<br>")
    for r in rows:
        new = cmap.get(r["sha"], r["sha"])
        text = git(a.repo, "log", "-1", "--format=%B", new)
        # A flagged message nobody replaced must not reach the table through the new column.
        if digest(text) == r.get("message_digest"):
            text = WITHHELD
        out.append(f"| {r['sha'][:8]} | {new[:8]} | {cell(r['message']) or '(empty)'} | {cell(text)} |")
    Path(a.out).write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{len(rows)} rows in {a.out}")


def remote_refs(text):
    return dict(reversed(l.split("\t")) for l in lines(text) if not l.endswith("^{}"))


def remote_changes(st, remote):
    # Every branch and tag, not just the planned ones: an unplanned ref that moved can keep old history alive.
    expected = {r.replace("refs/remotes/origin/", "refs/heads/"): o for r, o in st["refs"].items()
                if r.startswith(("refs/remotes/origin/", "refs/tags/"))}
    return sorted(r for r in expected.keys() | remote.keys() if expected.get(r) != remote.get(r))


def cmd_push(a):
    if not state_path(a.repo).exists():
        sys.exit("nothing to push: apply has not run on this clone")
    if not commit_map(a.repo):
        sys.exit("apply didn't finish on this clone. The remote is untouched. Clone it again and redo the run.")
    st = json.loads(state_path(a.repo).read_text())
    if not st["origin"]:
        sys.exit("no origin recorded")
    if Path(st["origin"]).exists():
        sys.exit("origin is a folder on this machine, not a hosted remote, so there's nothing to publish to. Skip phase 8.")
    plan, kept = [], []
    for ref, old in st["refs"].items():
        if ref.startswith("refs/remotes/origin/"):
            name = ref[len("refs/remotes/origin/"):]
            target = f"refs/heads/{name}"
        elif ref.startswith("refs/tags/"):
            name, target = ref, ref
        else:
            continue
        new = git(a.repo, "rev-parse", "--verify", "-q", target, check=False)
        if new and new != old:
            plan.append((target, old, new, ref))
        elif not new:
            kept.append(target)
    print(json.dumps({"remote": st["origin"], "verified": st.get("verified") == map_digest(a.repo),
                      "not_in_this_clone_so_old_history_stays_on_the_remote": kept,
                      "note": "rewritten refs only; --yes also rescans and refuses if unverified. New and deleted branches are separate steps.",
                      "updates": [{"ref": r, "old": o, "new": n} for r, o, n, _ in plan]}, indent=1))
    if kept:
        print(f"warning: old history stays on the remote through: {', '.join(kept)}", file=sys.stderr)
    if not a.yes:
        print("dry run: nothing pushed")
        r = subprocess.run(["git", "-C", a.repo, "ls-remote", st["origin"], "refs/heads/*", "refs/tags/*"], capture_output=True, text=True)
        if r.returncode:
            print("warning: couldn't check whether the remote moved after the clone", file=sys.stderr)
            return
        remote = remote_refs(r.stdout)
        changed = remote_changes(st, remote)
        if changed and not (plan and all(remote.get(t) == n for t, _, n, _ in plan) and set(changed) == {t for t, *_ in plan}):
            sys.exit(f"the remote changed after the clone: {', '.join(changed)}. This run can't be published. Clone again and redo it once those refs stop moving.")
        return
    if st.get("verified") != map_digest(a.repo):
        sys.exit("refused: run verify on this clone first, and get it to pass")
    restored = [(r[len("refs/remotes/origin/"):] if r.startswith("refs/remotes/origin/") else r)
                for r, tip in st["tips"].items() if not r.startswith("refs/heads/") and commit_map(a.repo).get(tip, tip) != tip
                and git(a.repo, "rev-parse", "--verify", "-q", f"{r.replace('refs/remotes/origin/', 'refs/heads/')}^{{commit}}", check=False) == tip]
    if restored:
        sys.exit(f"refused: these refs were put back on their old commits, so a push would leave them unrewritten: {', '.join(restored)}")
    cmap = commit_map(a.repo)
    moved = [r for r, _, n, src in plan
             if git(a.repo, "rev-parse", "--verify", "-q", f"{n}^{{commit}}", check=False) != cmap.get(st["tips"][src])
             or (r.startswith("refs/tags/") and st.get("verified_tags", {}).get(r) != n)]
    if moved:
        sys.exit(f"refused: these refs moved after the rewrite, so a push would publish commits verify never checked or drop later ones: {', '.join(moved)}")
    scan = subprocess.run([sys.executable, str(Path(__file__).with_name("scan.py")), a.repo], capture_output=True, text=True)
    if scan.returncode not in (0, 1):
        sys.exit("refused: the secret scan couldn't run (is gitleaks installed?). Nothing goes public unscanned.")
    if scan.returncode and not a.accept_findings:
        sys.exit("refused: the scan found secrets. Pass --accept-findings only if the owner saw them in the review and still said yes.")
    if not git(a.repo, "remote", "get-url", "origin", check=False):
        git(a.repo, "remote", "add", "origin", st["origin"])
    remote = remote_refs(git(a.repo, "ls-remote", "origin", "refs/heads/*", "refs/tags/*"))
    changed = remote_changes(st, remote)
    if plan and all(remote.get(r) == n for r, _, n, _ in plan) and set(changed) == {r for r, *_ in plan}:
        print("the remote already holds this push; nothing to do")
        return
    if changed:
        sys.exit(f"refused: the remote changed after the clone: {', '.join(changed)}. Pushing now could lose that work or keep old history. Clone again and redo the run.")
    if not plan:
        print("no commit changed, so nothing to push; origin is restored for the other branches")
        return
    args = ["push", "--atomic", "origin"]
    # An explicit lease fails the push if anyone moved a branch after the audit.
    args[1:1] = [f"--force-with-lease={r}:{o}" for r, o, _, _ in plan]
    args += [f"{n}:{r}" for r, _, n, _ in plan]
    r = subprocess.run(["git", "-C", a.repo, *args], capture_output=True, text=True)
    print(strip_credentials(r.stdout + r.stderr))
    if r.returncode:
        print("push rejected and nothing changed: a branch moved or a rule refused it. Clone the remote again and redo the run.", file=sys.stderr)
    sys.exit(r.returncode)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("origin"); o.add_argument("repo"); o.set_defaults(fn=cmd_origin)
    e = sub.add_parser("export"); e.add_argument("repo"); e.add_argument("--out", required=True); e.add_argument("--scan"); e.set_defaults(fn=cmd_export)
    x = sub.add_parser("apply"); x.add_argument("repo"); x.add_argument("--messages", required=True)
    x.add_argument("--drop-attribution", action="store_true"); x.add_argument("--purge"); x.set_defaults(fn=cmd_apply)
    v = sub.add_parser("verify"); v.add_argument("repo"); v.add_argument("--bundle", required=True); v.set_defaults(fn=cmd_verify)
    t = sub.add_parser("table"); t.add_argument("repo"); t.add_argument("--commits", required=True); t.add_argument("--out", required=True); t.set_defaults(fn=cmd_table)
    u = sub.add_parser("push"); u.add_argument("repo"); u.add_argument("--yes", action="store_true"); u.add_argument("--accept-findings", action="store_true"); u.set_defaults(fn=cmd_push)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
