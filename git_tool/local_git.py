"""Local git reads and writes through the git CLI."""
from __future__ import annotations

import base64
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


class GitError(Exception):
    pass


def _run(path: str, *args: str, timeout: int = 30, env: Optional[Dict[str, str]] = None) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", path, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, **env} if env else None,
        )
    except FileNotFoundError as exc:
        raise GitError("git is not installed or not in PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError("git command timed out") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise GitError(detail or f"git {' '.join(args)} failed")
    return proc.stdout


def parse_remote(url: str) -> Dict[str, str]:
    """Turn https/ssh GitHub remotes into host/owner/repo."""
    raw = (url or "").strip()
    if not raw:
        return {}

    host = ""
    path = ""
    if raw.startswith("git@") and ":" in raw:
        host, path = raw[4:].split(":", 1)
    elif "://" in raw:
        parsed = urlparse(raw)
        host = parsed.hostname or ""
        path = parsed.path.lstrip("/")
    else:
        return {}

    path = path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2:
        return {}
    return {"host": host, "owner": parts[-2], "repo": parts[-1]}


def is_repo(path: str) -> bool:
    if not path or not os.path.isdir(path):
        return False
    try:
        _run(path, "rev-parse", "--git-dir", timeout=5)
        return True
    except GitError:
        return False


def repo_info(path: str) -> Dict[str, Any]:
    root = _run(path, "rev-parse", "--show-toplevel").strip()
    if not root:
        raise GitError(f"{path} is not a git repository")

    branch = ""
    try:
        branch = _run(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    except GitError:
        branch = "(no commits)"

    status = _run(root, "status", "--porcelain")
    remote_url = ""
    try:
        remote_url = _run(root, "config", "--get", "remote.origin.url").strip()
    except GitError:
        pass

    return {
        "path": root,
        "name": os.path.basename(root),
        "branch": branch,
        "dirty": bool(status.strip()),
        "changed_files": len([line for line in status.splitlines() if line.strip()]),
        "remote_url": remote_url,
        **parse_remote(remote_url),
    }


_TRACK_RE = re.compile(r"ahead (\d+)")
_BEHIND_RE = re.compile(r"behind (\d+)")
# for-each-ref expands `%00`; git log/pretty needs `%x00`.
_FIELD = "%00"
_LOG_FIELD = "%x00"


def _parse_branch_line(line: str, current: str, remote: bool) -> Optional[Dict[str, Any]]:
    parts = line.split("\x00")
    if len(parts) < 9:
        return None
    ref, name, symref, upstream, track, sha, subject, author, date = parts[:9]
    # A remote's HEAD is a symref to one of its branches; git shortens it to the bare
    # remote name, so it has to be filtered on the full refname.
    if symref or (remote and ref.endswith("/HEAD")):
        return None
    ahead = int(match.group(1)) if (match := _TRACK_RE.search(track)) else 0
    behind = int(match.group(1)) if (match := _BEHIND_RE.search(track)) else 0
    return {
        "name": name,
        "current": name == current,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "gone": "gone" in track,
        "last_commit": {
            "sha": sha,
            "subject": subject,
            "author": author,
            "date": date,
        },
    }


def branches(path: str, head: str = "") -> Dict[str, Any]:
    current = ""
    try:
        current = _run(path, "rev-parse", "--abbrev-ref", "HEAD").strip()
    except GitError:
        pass

    fmt = _FIELD.join([
        "%(refname)",
        "%(refname:short)",
        "%(symref)",
        "%(upstream:short)",
        "%(upstream:track)",
        "%(objectname:short)",
        "%(contents:subject)",
        "%(authorname)",
        "%(authordate:iso-strict)",
    ])

    def collect(ref: str, remote: bool) -> List[Dict[str, Any]]:
        output = _run(path, "for-each-ref", f"--format={fmt}", ref)
        rows = []
        for line in output.splitlines():
            parsed = _parse_branch_line(line, current, remote)
            if parsed:
                rows.append(parsed)
        return rows

    local_rows = collect("refs/heads", False)
    remote_rows = collect("refs/remotes", True)

    compare_head = head.strip() or (current if current and current != "(no commits)" else "")
    payload: Dict[str, Any] = {
        "local": local_rows,
        "remote": remote_rows,
        "head": compare_head,
        "default_base": "",
        "divergence": {},
        "default_divergence": {},
    }
    if compare_head:
        _ensure_ref(path, compare_head)
        payload["divergence"] = divergence(path, compare_head, [row["name"] for row in remote_rows])

    default_ref = _default_remote_ref(path, remote_rows)
    payload["default_base"] = default_ref
    if default_ref:
        others = [row["name"] for row in remote_rows if row["name"] != default_ref]
        payload["default_divergence"] = divergence_from(path, default_ref, others)
    return payload


def _default_remote_ref(path: str, remote_rows: List[Dict[str, Any]]) -> str:
    """The remote's default branch, e.g. origin/main."""
    names = [row["name"] for row in remote_rows]
    try:
        target = _run(path, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", timeout=5).strip()
        if target:
            short = _run(path, "for-each-ref", "--format=%(refname:short)", target, timeout=5).strip()
            if short in names:
                return short
    except GitError:
        pass
    for candidate in ("origin/main", "origin/master"):
        if candidate in names:
            return candidate
    for name in names:
        if name.endswith("/main") or name.endswith("/master"):
            return name
    return names[0] if names else ""


def _ensure_ref(path: str, ref: str) -> str:
    value = _check_ref(ref)
    try:
        _run(path, "rev-parse", "--verify", "--quiet", f"{value}^{{commit}}", timeout=10)
    except GitError:
        raise GitError(f"unknown branch: {value}") from None
    return value


def history(path: str, ref: str, limit: int = 60) -> Dict[str, Any]:
    """Commits (including merges) reachable from `ref`, newest first, topo ordered."""
    ref = _ensure_ref(path, ref)
    fmt = _LOG_FIELD.join(["%H", "%h", "%P", "%s", "%an", "%cI", "%D"])
    output = _run(
        path, "log", "--topo-order", f"--format={fmt}", f"--max-count={limit}", ref, timeout=60
    )
    commits: List[Dict[str, Any]] = []
    for line in output.splitlines():
        parts = line.split("\x00")
        if len(parts) < 7:
            continue
        commits.append({
            "sha": parts[0],
            "short": parts[1],
            "parents": parts[2].split() if parts[2] else [],
            "subject": parts[3],
            "author": parts[4],
            "date": parts[5],
            "refs": [item.strip() for item in parts[6].split(",") if item.strip()],
        })
    return {"ref": ref, "commits": commits}


_REF_REJECT = re.compile(r"[\s\x00-\x1f\x7f]")


def _check_ref(ref: str) -> str:
    value = (ref or "").strip()
    if not value or value.startswith("-") or _REF_REJECT.search(value):
        raise GitError("invalid git ref")
    return value


def _ahead_behind(path: str, base: str, head: str) -> Dict[str, int]:
    """Commits `head` has that `base` does not (ahead) and vice versa (behind)."""
    output = _run(path, "rev-list", "--left-right", "--count", f"{base}...{head}", timeout=20).split()
    if len(output) != 2:
        raise GitError("cannot compare these branches")
    behind, ahead = int(output[0]), int(output[1])
    return {"ahead": ahead, "behind": behind}


def _log_range(path: str, rev_range: str, limit: int) -> List[Dict[str, str]]:
    fmt = "%H%x00%h%x00%s%x00%an%x00%cI"
    output = _run(path, "log", f"--format={fmt}", f"--max-count={limit}", rev_range, timeout=30)
    commits: List[Dict[str, str]] = []
    for line in output.splitlines():
        parts = line.split("\x00")
        if len(parts) >= 5:
            commits.append({
                "sha": parts[1],
                "subject": parts[2],
                "author": parts[3],
                "date": parts[4],
            })
    return commits


def _changed_files(path: str, base: str, head: str, limit: int = 300) -> Dict[str, Any]:
    output = _run(path, "diff", "--name-status", f"{base}...{head}", timeout=60)
    files: List[Dict[str, str]] = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        files.append({"status": parts[0][:1], "path": parts[-1]})
    return {
        "files": files[:limit],
        "files_total": len(files),
        "files_truncated": len(files) > limit,
    }


def compare(path: str, base: str, head: str, limit: int = 50) -> Dict[str, Any]:
    base = _check_ref(base)
    head = _check_ref(head)
    counts = _ahead_behind(path, base, head)
    merge_base = ""
    try:
        merge_base = _run(path, "merge-base", base, head, timeout=20).strip()
    except GitError:
        pass
    head_files = _changed_files(path, base, head)
    base_files = _changed_files(path, head, base)
    return {
        "base": base,
        "head": head,
        "ahead": counts["ahead"],
        "behind": counts["behind"],
        "merge_base": merge_base,
        "head_only": _log_range(path, f"{base}..{head}", limit) if counts["ahead"] else [],
        "base_only": _log_range(path, f"{head}..{base}", limit) if counts["behind"] else [],
        "head_files": head_files["files"],
        "head_files_total": head_files["files_total"],
        "head_files_truncated": head_files["files_truncated"],
        "base_files": base_files["files"],
        "base_files_total": base_files["files_total"],
        "base_files_truncated": base_files["files_truncated"],
    }


def _divergence(path: str, refs: List[str], orient) -> Dict[str, Optional[Dict[str, int]]]:
    result: Dict[str, Optional[Dict[str, int]]] = {}
    if not refs:
        return result

    def one(ref: str):
        try:
            base, head = orient(_check_ref(ref))
            return ref, _ahead_behind(path, base, head)
        except GitError:
            return ref, None

    with ThreadPoolExecutor(max_workers=min(8, len(refs))) as pool:
        for ref, counts in pool.map(one, refs):
            result[ref] = counts
    return result


def divergence(path: str, head: str, refs: List[str]) -> Dict[str, Optional[Dict[str, int]]]:
    """Per ref: commits `head` has that `ref` lacks (ahead) and vice versa (behind)."""
    head = _check_ref(head)
    return _divergence(path, refs, lambda ref: (ref, head))


def divergence_from(path: str, base: str, refs: List[str]) -> Dict[str, Optional[Dict[str, int]]]:
    """Per ref: commits `ref` has that `base` lacks (ahead) and vice versa (behind)."""
    base = _check_ref(base)
    return _divergence(path, refs, lambda ref: (base, ref))


def delete_branch(path: str, name: str, force: bool = False) -> Dict[str, Any]:
    _check_ref(name)
    _run(path, "branch", "-D" if force else "-d", "--", name)
    return {"deleted": name, "forced": force}


def create_branch(path: str, name: str, from_ref: str = "", checkout: bool = True) -> Dict[str, str]:
    _run(path, "check-ref-format", "--branch", name, timeout=5)
    args = ["switch", "-c", name] if checkout else ["branch", name]
    if from_ref:
        args.append(from_ref)
    _run(path, *args)
    return {"branch": name, "from": from_ref or "HEAD", "checked_out": "yes" if checkout else "no"}


def switch_branch(path: str, name: str) -> Dict[str, str]:
    _run(path, "switch", name)
    return {"branch": name}


def fetch(path: str, remote: str = "origin") -> Dict[str, str]:
    _run(path, "fetch", remote, "--prune", timeout=120)
    return {"remote": remote}


# --------------------------------------------------------------- workflow

def _tail(text: str, limit: int = 4000) -> str:
    value = (text or "").strip()
    return value[-limit:] if len(value) > limit else value


def _auth_env(token: str) -> Dict[str, str]:
    """Pass the GitHub token to git without putting it on the command line."""
    env = {"GIT_TERMINAL_PROMPT": "0"}
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update({
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
        })
    return env


def pull(path: str, remote: str = "origin", branch: str = "", token: str = "") -> Dict[str, Any]:
    args = ["pull", "--ff-only", remote]
    if branch:
        args.append(_check_ref(branch))
    output = _run(path, *args, timeout=180, env=_auth_env(token))
    return {"remote": remote, "branch": branch, "output": _tail(output)}


def push(
    path: str, branch: str, remote: str = "origin", set_upstream: bool = True, token: str = ""
) -> Dict[str, Any]:
    branch = _check_ref(branch)
    args = ["push"] + (["-u"] if set_upstream else []) + [remote, branch]
    output = _run(path, *args, timeout=180, env=_auth_env(token))
    return {"remote": remote, "branch": branch, "output": _tail(output)}


def merge_branch(path: str, ref: str) -> Dict[str, Any]:
    ref = _check_ref(ref)
    output = _run(path, "merge", "--no-edit", ref, timeout=120)
    return {"merged": ref, "output": _tail(output)}


def stage_all(path: str) -> Dict[str, Any]:
    _run(path, "add", "-A", timeout=60)
    names = _run(path, "diff", "--cached", "--name-only", timeout=30)
    return {"staged": [line for line in names.splitlines() if line.strip()]}


def commit(path: str, message: str) -> Dict[str, Any]:
    text = (message or "").strip()
    if not text:
        raise GitError("commit message is required")
    staged = stage_all(path)["staged"]
    if not staged:
        raise GitError("nothing to commit")
    output = _run(path, "commit", "-m", text, timeout=60)
    sha = _run(path, "rev-parse", "--short", "HEAD", timeout=10).strip()
    return {"sha": sha, "files": staged, "output": _tail(output)}
