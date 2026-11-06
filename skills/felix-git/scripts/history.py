#!/usr/bin/env python3
"""History rewrite: every commit keeps its author, dates and order, and its tree unless a purge the owner
approved says otherwise. Parents change only where structure adds feature and release merges.

  history.py origin <clone>                         print the origin URL with any credential removed
  history.py export <clone> --out commits.json [--scan scan.json]
                                                    commits to rename, with a diffstat of each; messages
                                                    the scan flagged come back withheld
  history.py apply  <clone> --messages messages.json [--author "Name <email>"] [--keep-attribution] [--purge purge.json]
  history.py structure <clone> --plan structure.json | --undo
                                                    after apply: regroup runs of commits into feature-branch
                                                    merges, rebuild main as release merges, tag versions
  history.py verify <clone> --bundle backup.bundle  compare rewritten commits with the originals
  history.py table  <clone> --commits commits.json --out old-to-new.md
  history.py push   <clone> [--yes] [--accept-findings]
                                                    show the push plan; push it only with --yes, after a
                                                    passing verify and a fresh scan of the clone

messages.json maps an old full SHA to its new message. Commits not listed keep their message.
purge.json removes data in the same pass: {"paths": ["dir/", "file"], "blobs": ["<full id>"],
"replace": [{"old": "text", "new": "text"}]}. Replacements are literal and also apply to messages.
Trailers such as Co-authored-by are carried over, except Claude attribution lines, which are dropped unless
--keep-attribution is given. --author re-attributes commits Claude made under its own identity to the user.
structure.json, by original SHAs: {"branch": "develop", "groups": [{"name": "feature/x", "commits": [sha, ...]}],
"releases": [{"commit": sha, "version": "1.2.0"}], "main": "main"}. A group is a run of consecutive single-parent
commits on the branch's first-parent line; it becomes a branch merged back with a merge commit holding the same
tree. With "main", that branch is rebuilt as one merge per release. Trees, authors, dates and messages of all
existing commits stay; only their parents change, as verify checks.
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
VERSION_HINT = re.compile(r"\bv?(\d+\.\d+(?:\.\d+)?)\b")
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
BRANCH_NAME = re.compile(r"^(feature|fix|docs|chore|refactor|perf|test|build|ci|style)/[a-z0-9][a-z0-9.-]{0,60}$")
CONVENTIONAL = re.compile(r"^(feat|fix|refactor|docs|chore|test|perf|build|ci|style|revert)(\([^)]+\))?!?: \S")
# What may carry over: the shapes tools really write, so an injected sentence in one of these keys stays behind.
KEEP_ATTR = re.compile(r"^(Claude-Session: (https?://[^\s@]+|[\w-]+)|🤖? *Generated with \[?Claude Code\]?(\(https?://[^\s@)]+\))?)$", re.I)
ATTR = re.compile(r"^(Co-Authored-By: *Claude.*|Claude-Session: .*|🤖? *Generated with \[?Claude.*)$", re.I)
# Commits Claude Code made under its own identity rather than the user's.
AI_IDENTITY = ("claude", "noreply@anthropic.com")
IDENT = re.compile(r"^([^<>\n]+?) <([^<>\s]+@[^<>\s]+)>$")


def is_ai(name, email):
    return (name.strip().lower(), email.strip().lower()) == AI_IDENTITY


def expected_identity(fields, owner):
    """fields: author name, email, date, committer name, email, date. Claude's identity becomes the owner's."""
    f = list(fields)
    if owner:
        for i in (0, 3):
            if is_ai(f[i], f[i + 1]):
                f[i], f[i + 1] = owner
    return f


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


def origin_destination(repo, expected=None):
    """Bind reads and writes to one reviewed destination, including Git URL rewrites."""
    fetch = lines(git(repo, "remote", "get-url", "--all", "origin", check=False))
    push = lines(git(repo, "remote", "get-url", "--push", "--all", "origin", check=False))
    if not fetch and not push and expected is None:
        return ""
    if (len(fetch) != 1 or len(push) != 1
            or strip_credentials(fetch[0]) != strip_credentials(push[0])
            or (expected is not None and strip_credentials(push[0]) != expected)):
        sys.exit("refused: origin destination differs from the reviewed destination or has multiple URLs. "
                 "Use one matching fetch/push destination and review it before retrying.")
    return strip_credentials(fetch[0])


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
            "parents": parents,
            "date": git(a.repo, "log", "-1", "--format=%as", sha),
            "message": WITHHELD if sha[:10] in flagged else message,
            "stat": git(a.repo, "show", "--stat=120", "--format=", "--no-color", sha),
        })
        if sha[:10] in flagged:
            rows[-1]["message_digest"] = digest(message)
        else:
            hints = VERSION_HINT.findall(message.split("\n", 1)[0])
            if hints:
                rows[-1]["version_hint"] = hints
                # A message's "v1.25" is ambiguous; the manifest at that commit says what was really shipped.
                found = manifest_versions(a.repo, sha)
                if found:
                    rows[-1]["manifest_versions"] = found
    if not rows:
        sys.exit("this repository has no commits, so there is nothing to rewrite")
    Path(a.out).write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(rows)} commits, {sum(r['is_merge'] for r in rows)} merges -> {a.out}")


MANIFESTS = {"package.json": re.compile(r'^\s*"version"\s*:\s*"([^"]+)"', re.M),
             "pyproject.toml": re.compile(r'^version\s*=\s*"([^"]+)"', re.M),
             "Cargo.toml": re.compile(r'^version\s*=\s*"([^"]+)"', re.M)}


def manifest_versions(repo, sha):
    out = {}
    for path, rx in MANIFESTS.items():
        r = subprocess.run(["git", "-C", repo, "show", f"{sha}:{path}"], capture_output=True, text=True, errors="replace")
        m = rx.search(r.stdout) if r.returncode == 0 else None
        if m:
            out[path] = m.group(1)
    return out


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
    origin = origin_destination(a.repo)
    origin_raw = strip_credentials(git(a.repo, "config", "--get", "remote.origin.url", check=False))
    push_raw = strip_credentials(git(a.repo, "config", "--get", "remote.origin.pushurl", check=False))
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
    drop = not a.keep_attribution
    owner = None
    if a.author:
        m = IDENT.match(a.author.strip())
        if not m or is_ai(*m.groups()):
            sys.exit('--author must look like "Name <email>" and name the user, not Claude. Nothing was rewritten.')
        owner = list(m.groups())
    resolved = {s: final_message(originals[s], mapping.get(s, originals[s]), drop)
                if s in mapping or (drop and any(ATTR.match(l) for l in originals[s].splitlines()))
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
    if owner:
        # Claude's own identity on a commit becomes the user's, for author and committer alike.
        callback += (
            f"owner = ({owner[0].encode()!r}, {owner[1].encode()!r})\n"
            "ai = lambda n, e: (n.strip().lower(), e.strip().lower()) == (b'claude', b'noreply@anthropic.com')\n"
            "if ai(commit.author_name, commit.author_email):\n"
            "    commit.author_name, commit.author_email = owner\n"
            "if ai(commit.committer_name, commit.committer_email):\n"
            "    commit.committer_name, commit.committer_email = owner\n"
        )
    # The commit each ref holds, peeled through annotated tags, so push can check it against the map.
    tips = {ref: git(a.repo, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}", check=False) for ref in refs}
    if purge and not all(tips.values()):
        # filter-repo leaves a tag on a blob or tree alone, so it would keep purged data public.
        sys.exit(f"these refs point at no commit, so a purge can't reach them: {', '.join(r for r, t in tips.items() if not t)}. "
                 "Nothing was rewritten.")
    before = {"origin": origin, "origin_raw": origin_raw, "push_raw": push_raw,
              "refs": refs, "tips": tips, "commits": list(originals), "purge": purge,
              "owner": owner}
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


def structure_path(repo):
    return Path(git(repo, "rev-parse", "--absolute-git-dir")) / "felix-git-structure.json"


def load_structure_state(repo):
    p = structure_path(repo)
    return json.loads(p.read_text()) if p.exists() else None


def raw_object(repo, oid):
    return subprocess.run(["git", "-C", repo, "cat-file", "-p", oid], capture_output=True, check=True).stdout


def write_object(repo, kind, data):
    r = subprocess.run(["git", "-C", repo, "hash-object", "-t", kind, "-w", "--stdin"], input=data, capture_output=True, check=True)
    return r.stdout.decode().strip()


def with_parents(raw, parents):
    """The same commit object with other parents, every other byte kept."""
    header, _, body = raw.partition(b"\n\n")
    out = []
    for line in header.split(b"\n"):
        if line.startswith(b"parent "):
            continue
        out.append(line)
        if line.startswith(b"tree "):
            out += [b"parent " + p.encode() for p in parents]
    return b"\n".join(out) + b"\n\n" + body


def header_line(raw, key):
    for line in raw.partition(b"\n\n")[0].split(b"\n"):
        if line.startswith(key + b" "):
            return line[len(key) + 1:]
    return b""


def made_commit(repo, tree, parents, who, message):
    """who: the 'Name <email> time tz' bytes of an existing commit's committer, reused for author and committer."""
    data = (b"tree " + tree.encode() + b"\n" + b"".join(b"parent " + p.encode() + b"\n" for p in parents)
            + b"author " + who + b"\ncommitter " + who + b"\n\n" + message.encode())
    return write_object(repo, "commit", data)


def semver(v):
    m = SEMVER.match(v or "")
    return tuple(int(x) for x in m.groups()) if m else None


def load_plan(path, repo, cmap):
    try:
        plan = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"{path} can't be read as JSON ({e}); nothing changed")
    if not isinstance(plan, dict) or set(plan) - {"branch", "groups", "releases", "main"}:
        sys.exit(f"{path}: only branch, groups, releases and main are allowed; nothing changed")
    branch = plan.get("branch")
    if not isinstance(branch, str) or not git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False):
        sys.exit(f"{path}: branch must name a branch of this clone; nothing changed")
    main = plan.get("main")
    if main is not None and (not isinstance(main, str) or main == branch
                             or not git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{main}", check=False)):
        sys.exit(f"{path}: main must name another branch of this clone; nothing changed")
    chain = git(repo, "rev-list", "--first-parent", "--reverse", f"refs/heads/{branch}").splitlines()
    at = {c: i for i, c in enumerate(chain)}
    mid = lambda sha: cmap.get(sha, sha) if isinstance(sha, str) else None
    groups, used, names = [], set(), set()
    for g in plan.get("groups", []):
        if not isinstance(g, dict) or not isinstance(g.get("commits"), list) or not g["commits"]:
            sys.exit(f"{path}: each group needs a name and a non-empty commits list; nothing changed")
        name = g.get("name")
        if not isinstance(name, str) or not BRANCH_NAME.match(name) or name in names:
            sys.exit(f"{path}: group name {name!r} must be a new <type>/<kebab-words> name, used once; nothing changed")
        names.add(name)
        commits = [mid(c) for c in g["commits"]]
        if any(c not in at for c in commits):
            sys.exit(f"{path}: {name} lists a commit that isn't on {branch}'s first-parent line; nothing changed")
        idx = [at[c] for c in commits]
        if idx != list(range(idx[0], idx[0] + len(idx))) or idx[0] == 0:
            sys.exit(f"{path}: {name} must be consecutive commits on {branch}, oldest first, not starting at the root; nothing changed")
        if any(len(git(repo, "log", "-1", "--format=%P", c).split()) != 1 for c in commits) or used & set(commits):
            sys.exit(f"{path}: {name} holds a merge or a commit another group has; nothing changed")
        used |= set(commits)
        groups.append({"name": name, "commits": commits})
    releases, last = [], None
    for r in plan.get("releases", []):
        c, v = (mid(r.get("commit")), r.get("version")) if isinstance(r, dict) else (None, None)
        if c not in at or not semver(v):
            sys.exit(f"{path}: each release needs a commit on {branch} and a version like 1.2.0; nothing changed")
        if last and (at[c] <= at[last[0]] or semver(v) <= semver(last[1])):
            sys.exit(f"{path}: releases must go oldest first, with rising versions; nothing changed")
        if git(repo, "rev-parse", "--verify", "-q", f"refs/tags/v{v}", check=False):
            sys.exit(f"{path}: tag v{v} already exists; nothing changed")
        releases.append({"commit": c, "version": v})
        last = (c, v)
    if not groups and not releases:
        sys.exit(f"{path}: no groups and no releases, so there is nothing to structure")
    return branch, main, chain, groups, releases


def cmd_structure(a):
    cmap = commit_map(a.repo)
    if not cmap or not state_path(a.repo).exists():
        sys.exit("run apply on this clone first")
    if a.undo:
        sst = load_structure_state(a.repo)
        if not sst:
            sys.exit("nothing to undo: structure hasn't run on this clone")
        for ref in sst["new_tags"]:
            git(a.repo, "update-ref", "-d", ref)
        for ref, oid in sst["before"].items():
            git(a.repo, "update-ref", ref, oid)
        structure_path(a.repo).unlink()
        print("structure undone: branches and tags are back to the message-only rewrite; run verify again")
        return
    if not a.plan:
        sys.exit("give --plan structure.json, or --undo")
    if load_structure_state(a.repo):
        sys.exit("this clone is already structured. Undo it with --undo first.")
    branch, main, chain, groups, releases = load_plan(a.plan, a.repo, cmap)
    before = dict(l.split(" ")[::-1] for l in lines(git(a.repo, "for-each-ref", "--format=%(objectname) %(refname)", "refs/heads", "refs/tags")))
    last_of = {g["commits"][-1]: g for g in groups}
    node, line, merges = {}, {}, []
    for c in git(a.repo, "rev-list", "--reverse", "--topo-order", "--all").splitlines():
        raw = raw_object(a.repo, c)
        parents = git(a.repo, "log", "-1", "--format=%P", c).split()
        n = write_object(a.repo, "commit", with_parents(raw, [line[p] for p in parents]))
        node[c] = line[c] = n
        g = last_of.get(c)
        if g:
            base = git(a.repo, "log", "-1", "--format=%P", g["commits"][0]).split()[0]
            m = made_commit(a.repo, git(a.repo, "rev-parse", f"{n}^{{tree}}"), [line[base], n],
                            header_line(raw, b"committer"), f"Merge branch '{g['name']}' into {branch}\n")
            line[c] = m
            merges.append({"name": g["name"], "base": base, "last": c, "merge": m})
    ref_tips, new_tags, main_line = {}, {}, []
    old_main = git(a.repo, "rev-parse", f"refs/heads/{main}") if main else None
    # Only versions main already held become release merges there; a later one is tagged on the branch alone.
    on_main = [r for r in releases if main and
               subprocess.run(["git", "-C", a.repo, "merge-base", "--is-ancestor", r["commit"], old_main]).returncode == 0]
    tag_at = {r["version"]: line[r["commit"]] for r in releases}
    if main:
        prev = line[chain[0]]
        for r in on_main:
            target = line[r["commit"]]
            if target != prev:
                prev = made_commit(a.repo, git(a.repo, "rev-parse", f"{target}^{{tree}}"), [prev, target],
                                   header_line(raw_object(a.repo, node[r["commit"]]), b"committer"),
                                   f"Merge branch 'release/{r['version']}'\n")
                main_line.append({"version": r["version"], "merge": prev, "release": r["commit"]})
            tag_at[r["version"]] = prev
        if line[old_main] != prev and not (on_main and line[old_main] == line[on_main[-1]["commit"]]):
            prev = made_commit(a.repo, git(a.repo, "rev-parse", f"{line[old_main]}^{{tree}}"), [prev, line[old_main]],
                               header_line(raw_object(a.repo, node[old_main]), b"committer"), f"Merge branch '{branch}' into {main}\n")
            main_line.append({"version": None, "merge": prev, "release": old_main})
    for line_ in lines(git(a.repo, "for-each-ref", "--format=%(refname) %(objectname) %(objecttype)", "refs/heads", "refs/tags")):
        ref, oid, kind = line_.split(" ")
        if kind == "commit":
            new = prev if main and ref == f"refs/heads/{main}" else line.get(oid, oid)
        elif kind == "tag":
            raw = raw_object(a.repo, oid)
            target = header_line(raw, b"object").decode()
            if header_line(raw, b"type") != b"commit" or target not in line:
                continue
            new = write_object(a.repo, "tag", raw.replace(b"object " + target.encode() + b"\n", b"object " + line[target].encode() + b"\n", 1))
        else:
            continue
        if new != oid:
            git(a.repo, "update-ref", ref, new, oid)
        ref_tips[ref] = git(a.repo, "rev-parse", f"{new}^{{commit}}")
    for r in releases:
        target = tag_at[r["version"]]
        who = header_line(raw_object(a.repo, node[r["commit"]]), b"committer")
        tag = write_object(a.repo, "tag", b"object " + target.encode() + b"\ntype commit\ntag v" + r["version"].encode()
                           + b"\ntagger " + who + b"\n\nv" + r["version"].encode() + b"\n")
        git(a.repo, "update-ref", f"refs/tags/v{r['version']}", tag, "")
        new_tags[f"refs/tags/v{r['version']}"] = tag
        ref_tips[f"refs/tags/v{r['version']}"] = target
    structure_path(a.repo).write_text(json.dumps({
        "branch": branch, "main": main, "node": node, "line": line, "merges": merges, "main_line": main_line,
        "old_main": old_main, "releases": releases, "new_tags": new_tags, "ref_tips": ref_tips, "before": before}))
    print(json.dumps({"feature_merges": len(merges), "release_merges_on_main": sum(1 for x in main_line if x["version"]),
                      "tags": sorted(new_tags), "next": "run verify"}, indent=1))


def structure_problems(repo, original, cmap, sst):
    """Checks the structure step on its own terms: same content, same order, only the parents it promised."""
    fail = []
    node, line = sst["node"], sst["line"]
    tree = lambda c: git(repo, "rev-parse", f"{c}^{{tree}}")
    parents = lambda c: git(repo, "log", "-1", "--format=%P", c).split()
    who = lambda c: header_line(raw_object(repo, c), b"committer")
    for m in sst["merges"]:
        if parents(m["merge"]) != [line[m["base"]], node[m["last"]]] or tree(m["merge"]) != tree(node[m["last"]]):
            fail.append({"merge": m["name"], "why": "the feature merge doesn't join its branch with the same tree"})
        if who(m["merge"]) != who(node[m["last"]]):
            fail.append({"merge": m["name"], "why": "the feature merge doesn't carry its last commit's identity and date"})
    prev = None
    for m in sst["main_line"]:
        p = parents(m["merge"])
        target = line[m["release"]]
        if len(p) != 2 or p[1] != target or tree(m["merge"]) != tree(target) or (prev and p[0] != prev):
            fail.append({"merge": m["merge"][:10], "why": "a release merge on main doesn't hold its release's tree"})
        prev = m["merge"]
    for ref, tip in sst["ref_tips"].items():
        now = git(repo, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}", check=False)
        if now != tip:
            fail.append({"ref": ref, "why": "moved after structure"})
    for ref, old in json.loads(state_path(repo).read_text())["tips"].items():
        name = ref.replace("refs/remotes/origin/", "refs/heads/")
        now = git(repo, "rev-parse", "--verify", "-q", f"{name}^{{commit}}", check=False)
        if now and tree(now) != git(original, "rev-parse", f"{old}^{{tree}}"):
            fail.append({"ref": name, "why": "its content differs from before the rewrite"})
    reachable = set(git(repo, "rev-list", "--all").splitlines())
    lost = [c for c in node.values() if c not in reachable]
    if lost:
        fail.append({"why": f"{len(lost)} rewritten commits are no longer on any branch or tag"})
    return fail


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
    extra = structure_path(repo).read_bytes() if structure_path(repo).exists() else b""
    return hashlib.sha256(path.read_bytes() + extra).hexdigest()


def final_map(repo):
    """Original SHA to the commit that holds it now: through filter-repo, then structure if it ran."""
    cmap, sst = commit_map(repo), load_structure_state(repo)
    if not sst:
        return cmap
    return {old: sst["node"].get(mid, mid) for old, mid in cmap.items()}


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
    cmap = final_map(a.repo)
    mids, sst = commit_map(a.repo), load_structure_state(a.repo)
    # With structure, a parent may now be the feature merge that stands for it on the line.
    parent_of = (lambda p: sst["line"].get(mids.get(p, p), mids.get(p, p))) if sst else (lambda p: cmap.get(p, p))
    st = json.loads(state_path(a.repo).read_text()) if state_path(a.repo).exists() else {}
    purge, owner = st.get("purge"), st.get("owner")
    seen, matched = {}, set()
    for old, new in cmap.items():
        checked += 1
        o = git(str(tmp), "log", "-1", f"--format={fmt}", old, check=False)
        n = git(a.repo, "log", "-1", f"--format={fmt}", new, check=False)
        if o and owner:
            parts = o.split("\0")
            o = "\0".join(parts[:1] + expected_identity(parts[1:], owner))
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
        op = [parent_of(p) for p in git(str(tmp), "log", "-1", "--format=%P", old).split()]
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
    if sst:
        fail += structure_problems(a.repo, str(tmp), mids, sst)
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
    cmap = final_map(a.repo)
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
    if not git(a.repo, "remote", "get-url", "origin", check=False):
        git(a.repo, "remote", "add", "origin", st.get("origin_raw", st["origin"]))
        if st.get("push_raw"):
            git(a.repo, "remote", "set-url", "--push", "origin", st["push_raw"])
    origin_destination(a.repo, st["origin"])
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
    sst = load_structure_state(a.repo)
    for ref, obj in (sst or {}).get("new_tags", {}).items():
        if git(a.repo, "rev-parse", "--verify", "-q", ref, check=False) == obj:
            plan.append((ref, "", obj, None))
    print(json.dumps({"remote": st["origin"], "verified": st.get("verified") == map_digest(a.repo),
                      "not_in_this_clone_so_old_history_stays_on_the_remote": kept,
                      "note": "rewritten refs only; --yes also rescans and refuses if unverified. New and deleted branches are separate steps.",
                      "updates": [{"ref": r, "old": o, "new": n} for r, o, n, _ in plan]}, indent=1))
    if kept:
        print(f"warning: old history stays on the remote through: {', '.join(kept)}", file=sys.stderr)
    if not a.yes:
        print("dry run: nothing pushed")
        r = subprocess.run(["git", "-C", a.repo, "ls-remote", "origin", "refs/heads/*", "refs/tags/*"], capture_output=True, text=True)
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
    expected = (lambda r, src: sst["ref_tips"].get(r)) if sst else (lambda r, src: cmap.get(st["tips"][src]))
    moved = [r for r, _, n, src in plan
             if git(a.repo, "rev-parse", "--verify", "-q", f"{n}^{{commit}}", check=False) != expected(r, src)
             or (r.startswith("refs/tags/") and st.get("verified_tags", {}).get(r) != n)]
    if moved:
        sys.exit(f"refused: these refs moved after the rewrite, so a push would publish commits verify never checked or drop later ones: {', '.join(moved)}")
    scan = subprocess.run([sys.executable, str(Path(__file__).with_name("scan.py")), a.repo], capture_output=True, text=True)
    if scan.returncode not in (0, 1):
        sys.exit("refused: the secret scan couldn't run (is gitleaks installed?). Nothing goes public unscanned.")
    if scan.returncode and not a.accept_findings:
        sys.exit("refused: the scan found secrets. Pass --accept-findings only if the owner saw them in the review and still said yes.")
    origin_destination(a.repo, st["origin"])
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
    x.add_argument("--keep-attribution", action="store_true", help="keep Claude attribution trailers (dropped by default)")
    x.add_argument("--drop-attribution", action="store_true", help=argparse.SUPPRESS)  # the default now; kept for old command lines
    x.add_argument("--author", help='"Name <email>" that replaces Claude\'s own identity on commits')
    x.add_argument("--purge"); x.set_defaults(fn=cmd_apply)
    g = sub.add_parser("structure"); g.add_argument("repo"); g.add_argument("--plan"); g.add_argument("--undo", action="store_true")
    g.set_defaults(fn=cmd_structure)
    v = sub.add_parser("verify"); v.add_argument("repo"); v.add_argument("--bundle", required=True); v.set_defaults(fn=cmd_verify)
    t = sub.add_parser("table"); t.add_argument("repo"); t.add_argument("--commits", required=True); t.add_argument("--out", required=True); t.set_defaults(fn=cmd_table)
    u = sub.add_parser("push"); u.add_argument("repo"); u.add_argument("--yes", action="store_true"); u.add_argument("--accept-findings", action="store_true"); u.set_defaults(fn=cmd_push)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
