"""Repository discovery: GitHub repos (token) joined with local clones."""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional

from . import local_git
from .github import GitHub

PRUNE_DIRS = {
    ".git", ".hg", ".svn",
    "node_modules", "bower_components",
    "venv", ".venv", "env", "site-packages",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    "dist", "build", "target", "out", "bin", "obj",
    ".next", ".nuxt", ".cache", ".parcel-cache", ".turbo",
    "vendor", "coverage", "htmlcov",
    ".idea", ".vscode", ".gradle", ".terraform",
    "Pods", "DerivedData",
}

MAX_DIRS = 20000
MAX_SECONDS = 20.0
DEFAULT_DEPTH = 3
MIN_DEPTH = 1
MAX_DEPTH = 4

AFFILIATIONS = (
    ("owner", "owner"),
    ("collaborator", "collaborator"),
    ("organization_member", "organization_member"),
)
ROLE_PRIORITY = {"owner": 0, "collaborator": 1, "organization_member": 2, "local": 3}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clamp_depth(depth: Any) -> int:
    try:
        value = int(depth)
    except (TypeError, ValueError):
        return DEFAULT_DEPTH
    return max(MIN_DEPTH, min(MAX_DEPTH, value))


def normalize_roots(roots: List[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for root in roots:
        if not isinstance(root, str) or not root.strip():
            continue
        path = os.path.realpath(os.path.expanduser(root.strip()))
        if path in seen or not os.path.isdir(path):
            continue
        seen.add(path)
        result.append(path)
    return result


def _is_repo_dir(path: str) -> bool:
    marker = os.path.join(path, ".git")
    return os.path.isdir(marker) or os.path.isfile(marker)


def _repo_root(path: str) -> str:
    if os.path.isdir(os.path.join(path, ".git")):
        return os.path.realpath(path)
    try:
        root = local_git._run(path, "rev-parse", "--show-toplevel", timeout=5).strip()
        return os.path.realpath(root) if root else os.path.realpath(path)
    except local_git.GitError:
        return os.path.realpath(path)


def _quick_meta(path: str) -> Dict[str, Any]:
    remote = ""
    branch = ""
    last_commit = ""
    try:
        remote = local_git._run(path, "config", "--get", "remote.origin.url", timeout=10).strip()
    except local_git.GitError:
        pass
    try:
        branch = local_git._run(path, "rev-parse", "--abbrev-ref", "HEAD", timeout=10).strip()
    except local_git.GitError:
        pass
    try:
        last_commit = local_git._run(path, "log", "-1", "--format=%cI", timeout=10).strip()
    except local_git.GitError:
        pass
    parsed = local_git.parse_remote(remote)
    return {
        "path": path,
        "name": os.path.basename(path),
        "remote_url": remote,
        "branch": branch,
        "last_commit": last_commit,
        "host": parsed.get("host", ""),
        "owner": parsed.get("owner", ""),
        "repo": parsed.get("repo", ""),
    }


def _local_metadata(paths: List[str]) -> List[Dict[str, Any]]:
    if not paths:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(paths))) as pool:
        repos = list(pool.map(_quick_meta, paths))
    repos.sort(key=lambda repo: (repo["name"].lower(), repo["path"]))
    return repos


def scan_local(roots: List[str], depth: int = DEFAULT_DEPTH) -> Dict[str, Any]:
    roots = normalize_roots(roots)
    depth = _clamp_depth(depth)
    started = time.monotonic()
    visited = 0
    truncated = False
    found: Dict[str, str] = {}
    queue: List[tuple] = [(root, 0) for root in roots]

    while queue:
        path, level = queue.pop(0)
        if time.monotonic() - started > MAX_SECONDS or visited >= MAX_DIRS:
            truncated = True
            break
        if _is_repo_dir(path):
            found.setdefault(_repo_root(path), path)
            continue
        try:
            entries = list(os.scandir(path))
        except OSError:
            continue
        visited += 1

        for entry in entries:
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            name = entry.name
            if name.startswith(".") or name.lower() in PRUNE_DIRS:
                continue
            child = entry.path
            if _is_repo_dir(child):
                found.setdefault(_repo_root(child), child)
                continue
            if level + 1 < depth:
                queue.append((child, level + 1))
            if time.monotonic() - started > MAX_SECONDS or visited >= MAX_DIRS:
                truncated = True
                break
        if truncated:
            break

    return {
        "roots": roots,
        "depth": depth,
        "scanned_at": _now(),
        "truncated": truncated,
        "dirs_visited": visited,
        "repos": _local_metadata(sorted(found.values())),
    }


def fetch_github_repos(client: GitHub) -> Dict[str, Any]:
    login = client.user().get("login", "")
    merged: Dict[str, Dict[str, Any]] = {}
    truncated = False

    for affiliation, role in AFFILIATIONS:
        repos, cut = client.repos_by_affiliation(affiliation)
        truncated = truncated or cut
        for repo in repos:
            full_name = (repo.get("full_name") or "").lower()
            if not full_name:
                continue
            existing = merged.get(full_name)
            if existing is None or ROLE_PRIORITY[role] < ROLE_PRIORITY[existing["role"]]:
                item = dict(repo)
                item["role"] = role
                merged[full_name] = item

    return {
        "login": login,
        "fetched_at": _now(),
        "truncated": truncated,
        "repos": list(merged.values()),
    }


def _opened_rank(value: str) -> float:
    if not value:
        return float("inf")
    try:
        return -datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return float("inf")


def _recent_rank(value: str) -> float:
    return _opened_rank(value)


def _pick_local(
    candidates: List[Dict[str, Any]],
    pinned: set,
    opened: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None

    def rank(repo: Dict[str, Any]):
        path = repo["path"]
        local_key = f"local:{os.path.realpath(path)}"
        return (
            0 if local_key in pinned else 1,
            _opened_rank(opened.get(local_key, "")),
            len(path),
            path,
        )

    return min(candidates, key=rank)


def _github_item(
    repo: Dict[str, Any],
    key: str,
    local: Optional[Dict[str, Any]],
    pinned: set,
    opened: Dict[str, str],
) -> Dict[str, Any]:
    return {
        "key": key,
        "github": True,
        "full_name": repo.get("full_name", ""),
        "name": repo.get("name", ""),
        "owner": repo.get("owner", ""),
        "host": "github.com",
        "role": repo.get("role", ""),
        "private": bool(repo.get("private")),
        "fork": bool(repo.get("fork")),
        "archived": bool(repo.get("archived")),
        "language": repo.get("language", ""),
        "updated_at": repo.get("updated_at", ""),
        "pushed_at": repo.get("pushed_at", ""),
        "default_branch": repo.get("default_branch", ""),
        "open_issues_count": repo.get("open_issues_count", 0),
        "html_url": repo.get("html_url", ""),
        "pinned": key in pinned,
        "last_opened": opened.get(key, ""),
        "local": local is not None,
        "local_path": local["path"] if local else "",
        "branch": local.get("branch", "") if local else "",
        "last_commit": local.get("last_commit", "") if local else "",
        "local_status": "present" if local else "not_found_or_outside_roots",
    }


def _local_item(
    repo: Dict[str, Any],
    key: str,
    pinned: set,
    opened: Dict[str, str],
) -> Dict[str, Any]:
    owner = repo.get("owner", "")
    name = repo.get("repo", "") or repo.get("name", "")
    return {
        "key": key,
        "github": False,
        "full_name": f"{owner}/{name}" if owner and name else repo.get("name", ""),
        "name": repo.get("name", ""),
        "owner": owner,
        "host": repo.get("host", ""),
        "role": "local",
        "private": False,
        "fork": False,
        "archived": False,
        "language": "",
        "updated_at": "",
        "pushed_at": "",
        "default_branch": "",
        "open_issues_count": 0,
        "html_url": "",
        "pinned": key in pinned,
        "last_opened": opened.get(key, ""),
        "local": True,
        "local_path": repo["path"],
        "branch": repo.get("branch", ""),
        "last_commit": repo.get("last_commit", ""),
        "local_status": "present",
    }


def _sort_key(item: Dict[str, Any]):
    recent = item.get("pushed_at") or item.get("updated_at") or item.get("last_commit") or ""
    return (
        0 if item.get("pinned") else 1,
        _opened_rank(item.get("last_opened", "")),
        _recent_rank(recent),
        item.get("name", "").lower(),
    )


def combine(
    github_cache: Dict[str, Any],
    scan_cache: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    github_repos = [repo for repo in github_cache.get("repos", []) if isinstance(repo, dict)]
    local_repos = [repo for repo in scan_cache.get("repos", []) if isinstance(repo, dict)]
    pinned = set(state.get("pinned", []))
    opened = state.get("last_opened", {})

    local_by_full: Dict[str, List[Dict[str, Any]]] = {}
    local_only: Dict[str, Dict[str, Any]] = {}
    for repo in local_repos:
        path = repo.get("path")
        if not isinstance(path, str) or not path:
            continue
        owner = (repo.get("owner") or "").strip()
        name = (repo.get("repo") or "").strip()
        if owner and name and repo.get("host", "") in ("", "github.com"):
            local_by_full.setdefault(f"{owner}/{name}".lower(), []).append(repo)
        else:
            local_only[f"local:{os.path.realpath(path)}"] = repo

    items: List[Dict[str, Any]] = []
    matched_paths = set()

    # The token decides what is visible: only repos it can reach are listed, and the local
    # scan merely marks which of them have a clone. Without a token (or when it returns
    # nothing) the list falls back to whatever is on disk under the scan roots.
    source = "github" if github_repos else "local"

    for repo in github_repos:
        full_name = repo.get("full_name", "")
        key = f"gh:{full_name.lower()}"
        chosen = _pick_local(local_by_full.get(full_name.lower(), []), pinned, opened)
        if chosen:
            matched_paths.add(os.path.realpath(chosen["path"]))
        items.append(_github_item(repo, key, chosen, pinned, opened))

    if source == "local":
        for full_name, candidates in local_by_full.items():
            chosen = _pick_local(candidates, pinned, opened)
            if not chosen or os.path.realpath(chosen["path"]) in matched_paths:
                continue
            items.append(_local_item(chosen, f"gh:{full_name}", pinned, opened))

        for key, repo in local_only.items():
            if os.path.realpath(repo["path"]) in matched_paths:
                continue
            items.append(_local_item(repo, key, pinned, opened))

    items.sort(key=_sort_key)
    return {
        "repos": items,
        "meta": {
            "source": source,
            "github": {
                "login": github_cache.get("login", ""),
                "fetched_at": github_cache.get("fetched_at", ""),
                "truncated": bool(github_cache.get("truncated")),
            },
            "scan": {
                "roots": scan_cache.get("roots", []),
                "depth": scan_cache.get("depth", DEFAULT_DEPTH),
                "scanned_at": scan_cache.get("scanned_at", ""),
                "truncated": bool(scan_cache.get("truncated")),
                "dirs_visited": scan_cache.get("dirs_visited", 0),
            },
            "counts": {
                "total": len(items),
                "local": sum(1 for item in items if item["local"]),
                "remote": sum(1 for item in items if not item["local"]),
                "pinned": sum(1 for item in items if item["pinned"]),
            },
        },
    }
