"""HTTP API for the Git workspace tool."""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import discovery, environment, keyrouter, local_git, state as state_store
from .github import GitHub, GitHubError

router = APIRouter()

# Bumped whenever the API shape changes; the UI refuses to run against an old backend.
API_VERSION = 4


class BranchCreate(BaseModel):
    path: str
    name: str
    from_ref: str = ""
    checkout: bool = True


class FetchRequest(BaseModel):
    path: str
    remote: str = "origin"


class WorkflowStart(BaseModel):
    path: str
    base: str
    branch: str
    pull: bool = True


class WorkflowSync(BaseModel):
    path: str
    base: str
    branch: str


class CommitRequest(BaseModel):
    path: str
    message: str


class PushRequest(BaseModel):
    path: str
    branch: str = ""
    remote: str = "origin"


class MergeRequest(BaseModel):
    repo: str
    method: str = "merge"


class BranchDelete(BaseModel):
    path: str
    name: str
    force: bool = False


class PullCreate(BaseModel):
    repo: str
    title: str
    head: str
    base: str = "main"
    body: str = ""
    draft: bool = False


class CommentCreate(BaseModel):
    repo: str
    body: str


class IssueCreate(BaseModel):
    repo: str
    title: str
    body: str = ""
    labels: List[str] = []


class IssueUpdate(BaseModel):
    repo: str
    state: str


class TokenValue(BaseModel):
    value: str


class ScanSettings(BaseModel):
    roots: List[str] = []
    depth: int = discovery.DEFAULT_DEPTH


class PinRequest(BaseModel):
    key: str
    pinned: bool


class OpenRequest(BaseModel):
    key: str


@contextmanager
def _errors():
    try:
        yield
    except GitHubError as exc:
        status = exc.status if 400 <= exc.status < 600 else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except local_git.GitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _client() -> GitHub:
    return GitHub(keyrouter.get_token())


def _split_repo(repo: str) -> Tuple[str, str]:
    parts = (repo or "").strip().split("/")
    if len(parts) != 2 or not all(parts):
        raise HTTPException(status_code=400, detail="repo must look like owner/name")
    return parts[0], parts[1]


@router.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "api_version": API_VERSION}


@router.get("/api/environment")
def get_environment() -> Dict[str, Any]:
    return environment.checks()


# ---------------------------------------------------------------- discovery

def _effective_roots(state: Dict[str, Any]) -> List[str]:
    roots = state["scan"].get("roots") or keyrouter.allowed_roots()
    return discovery.normalize_roots(roots)


def _scan_settings(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "roots": _effective_roots(state),
        "configured_roots": state["scan"].get("roots", []),
        "allowed_roots": keyrouter.allowed_roots(),
        "depth": state["scan"].get("depth", discovery.DEFAULT_DEPTH),
        "scanned_at": state["scan"].get("scanned_at", ""),
        "truncated": bool(state["scan"].get("truncated")),
        "dirs_visited": state["scan"].get("dirs_visited", 0),
    }


def _settings_payload() -> Dict[str, Any]:
    state = state_store.load_state()
    token = keyrouter.get_token()
    return {
        "api_version": API_VERSION,
        "github_token": {"has_token": bool(token), "preview": keyrouter.mask(token)},
        "managed_by_key_router": keyrouter.managed(),
        "scan": _scan_settings(state),
        "github": {
            "login": state["github"].get("login", ""),
            "fetched_at": state["github"].get("fetched_at", ""),
            "truncated": bool(state["github"].get("truncated")),
        },
    }


def _repos_payload(state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if state is None:
        state = state_store.load_state()
    payload = discovery.combine(state["github"], state["scan"], state)
    payload["scan"] = _scan_settings(state)
    return payload


@router.get("/api/repos")
def list_repos() -> Dict[str, Any]:
    return _repos_payload()


@router.post("/api/repos/refresh")
def refresh_repos(scope: str = "all") -> Dict[str, Any]:
    if scope not in ("all", "github", "local"):
        raise HTTPException(status_code=400, detail="scope must be all, github or local")

    state = state_store.load_state()
    roots = _effective_roots(state)
    depth = state["scan"].get("depth", discovery.DEFAULT_DEPTH)
    github_error = ""

    if scope in ("all", "github"):
        token = keyrouter.get_token()
        if token:
            client = GitHub(token)
            try:
                state["github"] = discovery.fetch_github_repos(client)
            except GitHubError as exc:
                github_error = str(exc)
            finally:
                client.close()

    if scope in ("all", "local"):
        state["scan"] = discovery.scan_local(roots, depth)

    state_store.save_state(state)

    payload = _repos_payload(state)
    payload["github_error"] = github_error
    return payload


@router.put("/api/settings/scan")
def update_scan_settings(payload: ScanSettings) -> Dict[str, Any]:
    if not (discovery.MIN_DEPTH <= payload.depth <= discovery.MAX_DEPTH):
        raise HTTPException(
            status_code=400,
            detail=f"depth must be between {discovery.MIN_DEPTH} and {discovery.MAX_DEPTH}",
        )

    roots: List[str] = []
    for root in payload.roots:
        if not isinstance(root, str) or not root.strip():
            continue
        path = os.path.realpath(os.path.expanduser(root.strip()))
        if not os.path.isdir(path):
            raise HTTPException(status_code=400, detail=f"Folder not found: {root}")
        roots.append(path)

    state = state_store.load_state()
    state["scan"]["roots"] = discovery.normalize_roots(roots)
    state["scan"]["depth"] = payload.depth
    state_store.save_state(state)
    return _settings_payload()


@router.post("/api/repos/pin")
def pin_repo(payload: PinRequest) -> Dict[str, Any]:
    key = (payload.key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="repo key is required")

    state = state_store.load_state()
    pinned = set(state.get("pinned", []))
    if payload.pinned:
        pinned.add(key)
    else:
        pinned.discard(key)
    state["pinned"] = sorted(pinned)
    state_store.save_state(state)
    return _repos_payload(state)


@router.post("/api/repos/open")
def open_repo(payload: OpenRequest) -> Dict[str, Any]:
    key = (payload.key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="repo key is required")

    state = state_store.load_state()
    state["last_opened"][key] = datetime.now().isoformat(timespec="seconds")
    state_store.save_state(state)
    return {"ok": True}


# ---------------------------------------------------------------- credentials

@router.get("/api/settings")
def get_settings() -> Dict[str, Any]:
    return _settings_payload()


@router.get("/api/browse-folder")
def browse_folder() -> Dict[str, Any]:
    if not keyrouter.BASE:
        raise HTTPException(status_code=400, detail="key-router is not reachable")
    try:
        response = httpx.get(f"{keyrouter.BASE}/api/browse-folder", timeout=120.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Folder picker failed: {exc}") from exc
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Folder picker failed ({response.status_code})")
    return response.json()


@router.put("/api/settings/github-token")
def save_github_token(payload: TokenValue) -> Dict[str, Any]:
    if not payload.value.strip():
        raise HTTPException(status_code=400, detail="GitHub token is required")
    try:
        keyrouter.set_token(payload.value)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _settings_payload()


@router.delete("/api/settings/github-token")
def remove_github_token() -> Dict[str, Any]:
    try:
        keyrouter.delete_token()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    state = state_store.load_state()
    state["github"] = state_store.empty_state()["github"]
    state_store.save_state(state)
    return _settings_payload()


@router.get("/api/status")
def status() -> Dict[str, Any]:
    token = keyrouter.get_token()
    result: Dict[str, Any] = {
        "token": bool(token),
        "login": "",
        "name": "",
        "rate_limit": 0,
        "rate_remaining": 0,
        "key_router_url": os.environ.get("KEY_ROUTER_URL", ""),
        "error": "",
    }
    if not token:
        return result
    try:
        client = _client()
        user = client.user()
        rate = client.rate_limit()
        client.close()
        result.update({
            "login": user["login"],
            "name": user["name"],
            "rate_limit": rate["limit"],
            "rate_remaining": rate["remaining"],
        })
    except GitHubError as exc:
        result["error"] = str(exc)
    return result


# ---------------------------------------------------------------- local git

@router.get("/api/repo")
def get_repo(path: str) -> Dict[str, Any]:
    with _errors():
        return local_git.repo_info(path)


@router.get("/api/branches")
def get_branches(path: str, head: str = "") -> Dict[str, Any]:
    with _errors():
        return local_git.branches(path, head)


@router.get("/api/branches/compare")
def compare_branches(path: str, base: str, head: str) -> Dict[str, Any]:
    with _errors():
        return local_git.compare(path, base, head)


@router.get("/api/branches/history")
def branch_history(path: str, ref: str, limit: int = 60) -> Dict[str, Any]:
    with _errors():
        return local_git.history(path, ref, max(1, min(200, limit)))


@router.post("/api/branches")
def create_branch(payload: BranchCreate) -> Dict[str, Any]:
    with _errors():
        return local_git.create_branch(payload.path, payload.name, payload.from_ref, payload.checkout)


@router.post("/api/branches/switch")
def switch_branch(payload: BranchCreate) -> Dict[str, Any]:
    with _errors():
        return local_git.switch_branch(payload.path, payload.name)


@router.post("/api/branches/delete")
def delete_branch(payload: BranchDelete) -> Dict[str, Any]:
    with _errors():
        return local_git.delete_branch(payload.path, payload.name, payload.force)


@router.post("/api/fetch")
def fetch_repo(payload: FetchRequest) -> Dict[str, Any]:
    with _errors():
        return local_git.fetch(payload.path, payload.remote)


# ---------------------------------------------------------------- workflow

def _token() -> str:
    try:
        return keyrouter.get_token()
    except Exception:
        return ""


def _run_step(steps: List[Dict[str, Any]], name: str, action) -> bool:
    try:
        steps.append({"name": name, "ok": True, "detail": action()})
        return True
    except local_git.GitError as exc:
        steps.append({"name": name, "ok": False, "error": str(exc)})
        return False


@router.post("/api/workflow/start")
def workflow_start(payload: WorkflowStart) -> Dict[str, Any]:
    """checkout base -> pull base -> create and checkout the task branch."""
    steps: List[Dict[str, Any]] = []
    token = _token()
    ok = _run_step(steps, f"checkout {payload.base}", lambda: local_git.switch_branch(payload.path, payload.base))
    if ok and payload.pull:
        ok = _run_step(
            steps,
            f"pull origin {payload.base}",
            lambda: local_git.pull(payload.path, "origin", payload.base, token),
        )
    if ok:
        ok = _run_step(
            steps,
            f"create {payload.branch} from {payload.base}",
            lambda: local_git.create_branch(payload.path, payload.branch, payload.base, True),
        )
    return {"ok": ok, "steps": steps}


@router.post("/api/workflow/sync")
def workflow_sync(payload: WorkflowSync) -> Dict[str, Any]:
    """checkout base -> pull base -> checkout my branch -> merge base into it."""
    steps: List[Dict[str, Any]] = []
    token = _token()
    ok = _run_step(steps, f"checkout {payload.base}", lambda: local_git.switch_branch(payload.path, payload.base))
    if ok:
        ok = _run_step(
            steps,
            f"pull origin {payload.base}",
            lambda: local_git.pull(payload.path, "origin", payload.base, token),
        )
    if ok:
        ok = _run_step(steps, f"checkout {payload.branch}", lambda: local_git.switch_branch(payload.path, payload.branch))
    if ok:
        ok = _run_step(steps, f"merge {payload.base}", lambda: local_git.merge_branch(payload.path, payload.base))
    return {"ok": ok, "steps": steps}


@router.post("/api/commit")
def commit_changes(payload: CommitRequest) -> Dict[str, Any]:
    with _errors():
        return local_git.commit(payload.path, payload.message)


@router.post("/api/push")
def push_branch(payload: PushRequest) -> Dict[str, Any]:
    with _errors():
        branch = payload.branch.strip()
        if not branch:
            branch = local_git.repo_info(payload.path)["branch"]
        return local_git.push(payload.path, branch, payload.remote, True, _token())


# ---------------------------------------------------------------- GitHub PRs / issues

@router.get("/api/prs")
def list_pulls(repo: str, state: str = "open") -> Dict[str, Any]:
    owner, name = _split_repo(repo)
    with _errors():
        client = _client()
        try:
            return {"pulls": client.pulls(owner, name, state)}
        finally:
            client.close()


@router.get("/api/prs/{number}")
def get_pull(number: int, repo: str) -> Dict[str, Any]:
    owner, name = _split_repo(repo)
    with _errors():
        client = _client()
        try:
            pull = client.pull(owner, name, number)
            return {"pull": pull, "comments": client.comments(owner, name, number)}
        finally:
            client.close()


@router.post("/api/prs")
def create_pull(payload: PullCreate) -> Dict[str, Any]:
    owner, name = _split_repo(payload.repo)
    with _errors():
        client = _client()
        try:
            return {"pull": client.create_pull(
                owner, name, payload.title, payload.head, payload.base, payload.body, payload.draft
            )}
        finally:
            client.close()


@router.post("/api/prs/{number}/comments")
def comment_pull(number: int, payload: CommentCreate) -> Dict[str, Any]:
    owner, name = _split_repo(payload.repo)
    with _errors():
        client = _client()
        try:
            return {"comment": client.comment(owner, name, number, payload.body)}
        finally:
            client.close()


@router.get("/api/discussions")
def list_discussions(repo: str, limit: int = 30) -> Dict[str, Any]:
    owner, name = _split_repo(repo)
    with _errors():
        client = _client()
        try:
            return {"discussions": client.discussions(owner, name, max(1, min(100, limit)))}
        finally:
            client.close()


@router.get("/api/issues")
def list_issues(repo: str, state: str = "open") -> Dict[str, Any]:
    owner, name = _split_repo(repo)
    with _errors():
        client = _client()
        try:
            return {"issues": client.issues(owner, name, state)}
        finally:
            client.close()


@router.get("/api/issues/{number}")
def get_issue(number: int, repo: str) -> Dict[str, Any]:
    owner, name = _split_repo(repo)
    with _errors():
        client = _client()
        try:
            return {"issue": client.issue(owner, name, number), "comments": client.comments(owner, name, number)}
        finally:
            client.close()


@router.post("/api/issues")
def create_issue(payload: IssueCreate) -> Dict[str, Any]:
    owner, name = _split_repo(payload.repo)
    with _errors():
        client = _client()
        try:
            labels = [label.strip() for label in payload.labels if label.strip()]
            return {"issue": client.create_issue(owner, name, payload.title, payload.body, labels)}
        finally:
            client.close()


@router.post("/api/issues/{number}/comments")
def comment_issue(number: int, payload: CommentCreate) -> Dict[str, Any]:
    owner, name = _split_repo(payload.repo)
    with _errors():
        client = _client()
        try:
            return {"comment": client.comment(owner, name, number, payload.body)}
        finally:
            client.close()


@router.post("/api/prs/{number}/merge")
def merge_pull(number: int, payload: MergeRequest) -> Dict[str, Any]:
    owner, name = _split_repo(payload.repo)
    if payload.method not in ("merge", "squash", "rebase"):
        raise HTTPException(status_code=400, detail="method must be merge, squash or rebase")
    with _errors():
        client = _client()
        try:
            return {"result": client.merge_pull(owner, name, number, payload.method)}
        finally:
            client.close()


@router.patch("/api/issues/{number}")
def update_issue(number: int, payload: IssueUpdate) -> Dict[str, Any]:
    owner, name = _split_repo(payload.repo)
    with _errors():
        client = _client()
        try:
            return {"issue": client.update_issue(owner, name, number, payload.state)}
        finally:
            client.close()
