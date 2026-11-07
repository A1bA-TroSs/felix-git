#!/usr/bin/env python3
"""Find what would embarrass or endanger the owner once the repo is promoted.

  scan.py <clone> [--also PATH ...] [--out report.json]

Covers every commit on every ref: secrets in files and commit messages (gitleaks), email addresses, sensitive file names,
junk and large files, including commit author addresses. Scan a --mirror clone to include
refs/pull/*, which a normal clone skips. Reports locations only and never prints a secret or a
full address. Archives are listed as unread, because their contents can't be searched here. --also adds new files, such as messages.json or the README, to the secret scan.
Exit 0 means no secret was found; 1 means at least one was; 2 means the scan could not run.
"""
import argparse, json, re, shutil, subprocess, sys, tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath

EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b")
EMAIL_OK = re.compile(rb"noreply|no-reply|example\.|@test\.|@localhost|@anthropic\.com|@users\.|\.(png|jpe?g|svg|gif|webp|js|ts|css|min)$", re.I)
SENSITIVE = re.compile(r"(^|/)(\.env(\.[\w-]+)?|id_rsa|id_ed25519|credentials(\.json)?|secrets?\.(json|ya?ml|toml)|service[-_]account.*\.json|\.npmrc|\.netrc|.*\.(pem|p12|pfx|key|keystore|mobileprovision|sqlite|db))$", re.I)
SENSITIVE_OK = re.compile(r"\.env\.(example|sample|template)$", re.I)
JUNK = re.compile(r"(^|/)(\.DS_Store|Thumbs\.db|desktop\.ini|node_modules/|__pycache__/|\.venv/|venv/|dist/|build/|DerivedData/|\.idea/|.*\.(log|tmp|bak|swp|tar|tar\.gz|tgz|zip|dmg|ipa|pyc))", re.I)
FIXTURE = re.compile(r"(^|/)(tests?|__tests__|spec|fixtures?|mocks?|samples?|examples?|demo|testdata)(/|$)|\.(test|spec)\.", re.I)
ARCHIVE = re.compile(r"\.(tar|tar\.gz|tgz|zip|7z|rar|dmg|ipa|jar|sqlite|db)$", re.I)
SHA = re.compile(rb"[0-9a-f]{40,64}")
AWS_KEY = re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")  # gitleaks skips AWS's documentation key; a person should see it
IMAGE = re.compile(r"\.(png|jpe?g|jfif|gif|webp|ico|svg|bmp|tiff?|hei[cf]|avif|mp4|mov|pdf)$", re.I)
# Leading bytes of image formats, for files whose name doesn't say what they are.
IMAGE_MAGIC = re.compile(rb"^(\x89PNG|\xff\xd8\xff|GIF8|RIFF....WEBP|....ftyp(hei[cfsx]|mif1|msf1|avif)|BM|II\*\0|MM\0\*|\0\0\x01\0|%PDF)", re.S)
LARGE = 1024 * 1024
TEXT_LIMIT = 2 * 1024 * 1024


def run(*cmd, **kw):
    return subprocess.run(cmd, capture_output=True, **kw)


def git(repo, *args):
    r = run("git", "-C", repo, *args)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""


def gitleaks(args):
    """Returns (findings, error). Findings carry only rule, file, line and commit.
    Config and ignore files are ours: a repo's own .gitleaks.toml or allow comments could switch the scan off."""
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "r.json"
        config = Path(tmp) / "gitleaks.toml"
        config.write_text("[extend]\nuseDefault = true\n")
        r = run("gitleaks", *args, "--config", str(config), "--gitleaks-ignore-path", tmp, "--ignore-gitleaks-allow", "--redact", "--no-banner", "--report-format", "json", "--report-path", str(report))
        if r.returncode not in (0, 1) or not report.exists():
            return [], "gitleaks failed: " + r.stderr.decode("utf-8", "replace")[-200:]
        rows = json.loads(report.read_text() or "[]")
    return [{"rule": x.get("RuleID"), "file": x.get("File"), "line": x.get("StartLine"),
             "commit": (x.get("Commit") or "")[:10]} for x in rows] + (aws_hits(args[1]) if args[0] == "dir" else []), None


def aws_hits(path):
    """gitleaks skips AWS's documentation key, so look for that shape ourselves."""
    root = Path(path)
    hits = []
    for f in [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file()):
        if f.stat().st_size <= TEXT_LIMIT and AWS_KEY.search(f.read_bytes()):
            hits.append({"rule": "aws-access-key", "file": str(f), "line": None, "commit": ""})
    return hits


def scan_messages(repo):
    """gitleaks reads diffs, not commit messages, so messages get their own pass. NUL is the only
    separator a message can't hold, and file names come from checked SHAs, never from repo text."""
    log = run("git", "-C", repo, "log", "--all", "-z", "--format=%H%n%B").stdout
    texts = {}
    for rec in log.split(b"\0"):
        sha, _, body = rec.lstrip(b"\n").partition(b"\n")
        if SHA.fullmatch(sha):
            texts[sha.decode()] = body
    for line in git(repo, "for-each-ref", "refs/tags", "--format=%(objectname) %(objecttype)").splitlines():
        sha, kind = line.split()
        if kind == "tag" and SHA.fullmatch(sha.encode()):
            texts[sha] = run("git", "-C", repo, "cat-file", "tag", sha).stdout
    with tempfile.TemporaryDirectory() as tmp:
        for sha, body in texts.items():
            (Path(tmp) / f"{sha}.txt").write_bytes(body)
        found, err = gitleaks(["dir", tmp])
    return [{"rule": f["rule"], "commit": Path(f["file"]).stem[:10]} for f in found], err


def scan_nul_files(files):
    """git and gitleaks treat a file with NUL bytes as binary and skip it, which hides UTF-16 text.
    Dropping the NULs turns UTF-16 into readable ASCII; real binaries just produce nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        for oid, (_, data) in files.items():
            (Path(tmp) / f"{oid}.txt").write_bytes(data)
        found, err = gitleaks(["dir", tmp])
    return [{**f, "file": files[Path(f["file"]).stem][0], "commit": None} for f in found], err


def scan_history(repo):
    """A .gitattributes marking a path binary or -diff hides it from `git log -p` in a checkout.
    A bare mirror doesn't read attributes from the tree, so the repo can't switch the scan off that way."""
    if git(repo, "rev-parse", "--is-bare-repository").strip() == "true":
        return gitleaks(["git", repo, "--log-opts=--all"])
    with tempfile.TemporaryDirectory() as tmp:
        mirror = str(Path(tmp) / "m.git")
        r = run("git", "clone", "-q", "--mirror", "--no-hardlinks", str(Path(repo).resolve()), mirror)
        if r.returncode:
            return [], "couldn't mirror the clone for scanning: " + r.stderr.decode("utf-8", "replace")[-200:]
        return gitleaks(["git", mirror, "--log-opts=--all"])


def scan_merges(repo):
    """gitleaks reads `git log -p`, which shows merges no diff. A file that differs from every
    parent is content only the merge introduced; anything else was scanned in its parent."""
    introduced = {}
    for sha in git(repo, "log", "--all", "--merges", "--format=%H").split():
        raw = run("git", "-C", repo, "diff-tree", "-c", "--raw", "-z", "--no-abbrev", "--no-renames", "--no-commit-id", sha).stdout
        fields = [f for f in raw.decode("utf-8", "replace").split("\0") if f]
        for meta, path in zip(fields[::2], fields[1::2]):
            parts = meta.split()
            # "::m1 m2 mresult o1 o2 oresult status": one colon per parent, the merge's own entry last.
            parents = meta.count(":")
            mode, oid = parts[parents], parts[2 * parents + 1]
            if not mode.startswith("160000") and set(oid) != {"0"}:
                introduced.setdefault(oid, (path, sha[:10]))
    if not introduced:
        return [], None
    with tempfile.TemporaryDirectory() as tmp:
        for oid in introduced:
            (Path(tmp) / f"{oid}.txt").write_bytes(run("git", "-C", repo, "cat-file", "blob", oid).stdout)
        found, err = gitleaks(["dir", tmp])
    return [{**f, "file": introduced[Path(f["file"]).stem][0], "commit": introduced[Path(f["file"]).stem][1]} for f in found], err


def scan_extra(path):
    """A messages.json is scanned message by message: as one file, "API." beside the next SHA key reads as a key."""
    if not path.endswith(".json"):
        return gitleaks(["dir", path])
    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError:
        rows = None
    if not isinstance(rows, dict):
        return gitleaks(["dir", path])
    with tempfile.TemporaryDirectory() as tmp:
        keys = list(rows)
        for i, key in enumerate(keys):
            (Path(tmp) / f"{i}.txt").write_text(str(rows[key]), encoding="utf-8")
        found, err = gitleaks(["dir", tmp])
    return [{**f, "file": f"{Path(path).name}:{keys[int(Path(f['file']).stem)][:10]}"} for f in found], err


def mask(addr):
    local, _, domain = addr.decode("utf-8", "replace").partition("@")
    # Length included so a real address and a placeholder such as you@gmail.com stay apart.
    return f"{local[:1]}***[{len(local)}]@{domain}"


def blobs(repo):
    """Yields (path, size, oid) per distinct path and content in history. Identical files under
    different names share one object, so walking objects alone would hide all but one name."""
    raw = run("git", "-C", repo, "log", "--all", "-m", "--raw", "-z", "--no-abbrev", "--no-renames", "--format=").stdout
    fields = [f for f in raw.decode("utf-8", "replace").split("\0") if f]
    pairs = {(path, meta.split()[3]) for meta, path in zip(fields[::2], fields[1::2])
             if meta.startswith(":") and not meta.split()[1].startswith("160000") and set(meta.split()[3]) != {"0"}}
    if not pairs:
        return
    pairs = sorted(pairs)
    feed = "\n".join(oid for _, oid in pairs).encode()
    r = run("git", "-C", repo, "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)", input=feed)
    for (path, oid), line in zip(pairs, r.stdout.decode().splitlines()):
        parts = line.split()
        if len(parts) == 3 and parts[1] == "blob":
            yield path, int(parts[2]), oid


def blob_prefix(repo, oid):
    proc = subprocess.Popen(["git", "-C", repo, "cat-file", "blob", oid],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        data = proc.stdout.read(8000)
        if len(data) < 8000 and proc.wait() != 0:
            raise RuntimeError("couldn't inspect historical blob")
        return data
    finally:
        proc.stdout.close()
        if proc.poll() is None:
            proc.terminate()
        proc.wait()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("repo")
    p.add_argument("--also", nargs="*", default=[])
    p.add_argument("--out")
    a = p.parse_args()
    if not git(a.repo, "rev-parse", "--git-dir"):
        print(f"not a git repository: {a.repo}", file=sys.stderr)
        sys.exit(2)
    tracked_on = defaultdict(list)
    for ref in filter(None, git(a.repo, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes").split("\n")):
        for path in filter(None, git(a.repo, "ls-tree", "-r", "-z", "--name-only", ref).split("\0")):
            tracked_on[path].append(ref.replace("refs/heads/", "").replace("refs/remotes/", ""))
    current = set(tracked_on)
    tip_blobs = set()
    for ref in filter(None, git(a.repo, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes").split("\n")):
        tip_blobs.update(line.split()[2] for line in filter(None, git(a.repo, "ls-tree", "-r", ref).split("\n")))
    image_paths = defaultdict(set)
    report = {"secrets": [], "secret_scan_ran": bool(shutil.which("gitleaks")), "new_file_secrets": [], "message_secrets": [], "also_missing": [],
              "emails": defaultdict(set), "emails_in_fixtures": defaultdict(set), "author_emails": set(),
              "unread_archives": set(), "unscanned_binary_text": set(), "sensitive_files": set(), "junk_files": set(),
              "large_files": {}, "images_to_view": set(), "images_only_in_history": set()}
    if report["secret_scan_ran"]:
        report["secrets"], err = scan_history(a.repo)
        report["message_secrets"], err3 = scan_messages(a.repo)
        err = err or err3
        merged, err4 = scan_merges(a.repo)
        report["secrets"] += merged
        err = err or err4
        for extra in a.also:
            if not Path(extra).exists():
                report["also_missing"].append(extra)
                continue
            found, err2 = scan_extra(extra)
            report["new_file_secrets"] += found
            err = err or err2
        if err:
            report["secret_scan_ran"] = False
            report["error"] = err
    for addr in set(git(a.repo, "log", "--all", "--format=%ae%n%ce").split()):
        if not EMAIL_OK.search(addr.encode()):
            report["author_emails"].add(mask(addr.encode()))
    seen = set()
    nul_files = {}
    for path, size, oid in blobs(a.repo):
        if SENSITIVE.search(path) and not SENSITIVE_OK.search(path):
            report["sensitive_files"].add(path)
        if JUNK.search(path):
            report["junk_files"].add(path)
        if ARCHIVE.search(path):
            report["unread_archives"].add(path)
        if size >= LARGE:
            report["large_files"][path] = max(size, report["large_files"].get(path, 0))
        if IMAGE.search(PurePosixPath(path).name):
            report["images_to_view" if path in current else "images_only_in_history"].add(path)
            image_paths[oid].add(path)
        if size > TEXT_LIMIT:
            prefix = blob_prefix(a.repo, oid)
            if b"\0" in prefix and (not IMAGE.search(PurePosixPath(path).name)
                                      or prefix.startswith((b"\xff\xfe", b"\xfe\xff"))):
                report["unscanned_binary_text"].add(path)
        if (oid, path) not in seen and size <= TEXT_LIMIT:
            seen.add((oid, path))
            data = run("git", "-C", a.repo, "cat-file", "blob", oid).stdout
            if not IMAGE.search(PurePosixPath(path).name) and IMAGE_MAGIC.match(data[:16]):
                image_paths[oid].add(path)
            if b"\0" in data[:8000] and not IMAGE.search(PurePosixPath(path).name):
                nul_files[oid] = (path, data.replace(b"\0", b""))
            if b"\0" not in data[:8000]:
                if AWS_KEY.search(data):
                    report["secrets"].append({"rule": "aws-access-key", "file": path, "line": None, "commit": None})
                for m in set(EMAIL.findall(data)):
                    if not EMAIL_OK.search(m):
                        report["emails_in_fixtures" if FIXTURE.search(path) else "emails"][mask(m)].add(path)
    if report["secret_scan_ran"] and nul_files:
        found, err = scan_nul_files(nul_files)
        report["secrets"] += found
        if err:
            report["secret_scan_ran"] = False
            report["error"] = err
    if report["unscanned_binary_text"]:
        report["secret_scan_ran"] = False
        report["error"] = "NUL-containing historical files exceed the 2 MiB text scan limit; review them separately."
    for key in ("emails", "emails_in_fixtures"):
        report[key] = {k: sorted(v)[:5] for k, v in report[key].items()}
    for key in ("sensitive_files", "junk_files", "images_to_view", "images_only_in_history", "author_emails", "unread_archives", "unscanned_binary_text"):
        report[key] = sorted(report[key])
    # A path says nothing about what it held earlier: each version can show something different.
    report["image_blobs"] = sorted(({"blob": oid, "paths": sorted(paths), "at_a_branch_tip": oid in tip_blobs}
                                    for oid, paths in image_paths.items()),
                                   key=lambda b: (not b["at_a_branch_tip"], b["paths"], b["blob"]))
    report["still_tracked"] = {p: tracked_on[p] for p in sorted((set(report["junk_files"]) | set(report["sensitive_files"])) & current)}
    text = json.dumps(report, indent=1, ensure_ascii=False)
    if a.out:
        Path(a.out).write_text(text)
    print(text)
    if not report["secret_scan_ran"]:
        print("SECRET SCAN DID NOT RUN", file=sys.stderr)
        sys.exit(2)
    sys.exit(1 if report["secrets"] or report["message_secrets"] or report["new_file_secrets"] else 0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # a crash must read as "scan didn't run", never as findings or as clean
        print(f"SECRET SCAN DID NOT RUN: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(2)
