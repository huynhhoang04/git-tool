import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from git_tool import discovery, state as state_store
from git_tool.app import create_app
from git_tool.github import GitHubError


def git(path, *args):
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(autouse=True)
def clear_env(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("KEY_ROUTER_TOOL_TOKEN", raising=False)
    monkeypatch.setenv("KEY_ROUTER_TOOL_DATA", str(tmp_path / "tool-data"))


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.email", "tester@example.com")
    git(path, "config", "user.name", "Tester")
    (path / "a.txt").write_text("a", encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-m", "first commit")
    git(path, "remote", "add", "origin", "https://github.com/owner/demo.git")
    return path


@pytest.fixture
def client():
    return TestClient(create_app())


def test_health(client):
    data = client.get("/health").json()
    assert data["ok"] is True
    assert data["api_version"] == 4


def test_settings_exposes_api_version(client):
    assert client.get("/api/settings").json()["api_version"] == 4


def test_status_without_token(client):
    data = client.get("/api/status").json()
    assert data["token"] is False
    assert data["error"] == ""


def test_repo_detail_and_branches(client, repo):
    detail = client.get("/api/repo", params={"path": str(repo)}).json()
    assert detail["owner"] == "owner"
    assert detail["repo"] == "demo"

    branches = client.get("/api/branches", params={"path": str(repo)}).json()
    assert branches["local"][0]["name"] == "main"
    assert branches["local"][0]["current"] is True


def test_repos_cache_starts_empty(client):
    data = client.get("/api/repos").json()
    assert data["repos"] == []
    assert data["meta"]["counts"]["total"] == 0


def test_refresh_local_then_pin_and_open(client, repo, monkeypatch):
    scan = discovery.scan_local([str(repo)], 2)
    monkeypatch.setattr("git_tool.routes.discovery.scan_local", lambda roots, depth: scan)

    data = client.post("/api/repos/refresh?scope=local").json()
    assert len(data["repos"]) == 1
    key = data["repos"][0]["key"]
    assert key == "gh:owner/demo"
    assert data["repos"][0]["local"] is True

    pinned = client.post("/api/repos/pin", json={"key": key, "pinned": True}).json()
    assert pinned["repos"][0]["pinned"] is True

    assert client.post("/api/repos/open", json={"key": key}).json() == {"ok": True}
    state = state_store.load_state()
    assert key in state["pinned"]
    assert key in state["last_opened"]


def test_refresh_reports_github_error(client, repo, monkeypatch):
    class FakeClient:
        def close(self):
            pass

    monkeypatch.setattr("git_tool.routes.keyrouter.get_token", lambda: "token")
    monkeypatch.setattr("git_tool.routes.GitHub", lambda token: FakeClient())

    def boom(client_obj):
        raise GitHubError(401, "Bad credentials")

    monkeypatch.setattr("git_tool.routes.discovery.fetch_github_repos", boom)
    monkeypatch.setattr("git_tool.routes.discovery.scan_local", lambda roots, depth: {
        "roots": [], "depth": 3, "scanned_at": "", "truncated": False, "dirs_visited": 0, "repos": [],
    })

    data = client.post("/api/repos/refresh?scope=all").json()
    assert "Bad credentials" in data["github_error"]


def test_scan_settings_roundtrip(client, repo):
    response = client.put("/api/settings/scan", json={"roots": [str(repo)], "depth": 1})
    assert response.status_code == 200
    scan = response.json()["scan"]
    assert scan["roots"] == [str(repo)]
    assert scan["depth"] == 1


def test_scan_settings_validation(client):
    assert client.put("/api/settings/scan", json={"roots": ["/nope"], "depth": 1}).status_code == 400
    assert client.put("/api/settings/scan", json={"roots": [], "depth": 9}).status_code == 400


def test_create_and_switch_branch(client, repo):
    created = client.post("/api/branches", json={"path": str(repo), "name": "topic"})
    assert created.status_code == 200
    assert client.get("/api/repo", params={"path": str(repo)}).json()["branch"] == "topic"

    switched = client.post("/api/branches/switch", json={"path": str(repo), "name": "main"})
    assert switched.status_code == 200
    assert client.get("/api/repo", params={"path": str(repo)}).json()["branch"] == "main"


def test_branch_divergence_endpoint(client, repo):
    git(repo, "switch", "-c", "feature")
    (repo / "b.txt").write_text("b", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "feat")
    git(repo, "switch", "main")
    git(repo, "update-ref", "refs/remotes/origin/main", "main")

    data = client.get("/api/branches", params={"path": str(repo), "head": "feature"}).json()

    assert data["head"] == "feature"
    assert data["divergence"]["origin/main"] == {"ahead": 1, "behind": 0}


def test_branch_compare_endpoint(client, repo):
    git(repo, "switch", "-c", "feature")
    (repo / "b.txt").write_text("b", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "feat")

    data = client.get(
        "/api/branches/compare",
        params={"path": str(repo), "base": "main", "head": "feature"},
    ).json()

    assert data["ahead"] == 1
    assert data["behind"] == 0
    assert [item["path"] for item in data["head_files"]] == ["b.txt"]
    assert data["base_files"] == []


def test_branch_history_endpoint(client, repo):
    data = client.get("/api/branches/history", params={"path": str(repo), "ref": "main"}).json()
    assert data["ref"] == "main"
    assert data["commits"][0]["subject"] == "first commit"
    assert data["commits"][0]["parents"] == []


def test_branch_delete_endpoint(client, repo):
    git(repo, "branch", "topic")

    deleted = client.post("/api/branches/delete", json={"path": str(repo), "name": "topic"}).json()
    assert deleted == {"deleted": "topic", "forced": False}

    refused = client.post("/api/branches/delete", json={"path": str(repo), "name": "main"})
    assert refused.status_code == 400


def test_git_error_maps_to_400(client, tmp_path):
    response = client.get("/api/repo", params={"path": str(tmp_path)})
    assert response.status_code == 400


class FakeGitHub:
    def __init__(self):
        self.closed = False

    def pulls(self, owner, repo, state="open"):
        return [{"number": 1, "title": "PR one", "state": state}]

    def issues(self, owner, repo, state="open"):
        return [{"number": 2, "title": "Issue two", "state": state}]

    def pull(self, owner, repo, number):
        return {"number": number, "title": "PR one", "body": "hello"}

    def issue(self, owner, repo, number):
        return {"number": number, "title": "Issue two", "body": "hello", "state": "open"}

    def comments(self, owner, repo, number):
        return [{"id": 1, "user": "octocat", "body": "hi", "created_at": "2026-01-01T00:00:00Z"}]

    def create_issue(self, owner, repo, title, body="", labels=None):
        return {"number": 3, "title": title, "labels": labels or []}

    def create_pull(self, owner, repo, title, head, base, body="", draft=False):
        return {"number": 4, "title": title, "head": head, "base": base}

    def comment(self, owner, repo, number, body):
        return {"id": 9}

    def update_issue(self, owner, repo, number, state):
        return {"number": number, "state": state}

    def discussions(self, owner, repo, limit=30):
        return [{"number": 5, "title": "Idea", "url": "https://github.com/owner/demo/discussions/5",
                 "author": "octocat", "category": "Ideas", "comments": 2,
                 "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-02T00:00:00Z"}]

    def merge_pull(self, owner, repo, number, method="merge"):
        return {"merged": True, "message": f"merged with {method}", "sha": "abc123"}

    def close(self):
        self.closed = True


def test_github_endpoints_use_client(client, monkeypatch):
    monkeypatch.setattr("git_tool.routes._client", lambda: FakeGitHub())

    pulls = client.get("/api/prs", params={"repo": "owner/demo"}).json()
    assert pulls["pulls"][0]["number"] == 1

    issues = client.get("/api/issues", params={"repo": "owner/demo"}).json()
    assert issues["issues"][0]["number"] == 2

    detail = client.get("/api/prs/1", params={"repo": "owner/demo"}).json()
    assert detail["comments"][0]["user"] == "octocat"

    created = client.post("/api/issues", json={
        "repo": "owner/demo", "title": "New", "labels": ["bug", " ui "],
    }).json()
    assert created["issue"]["labels"] == ["bug", "ui"]

    opened_pr = client.post("/api/prs", json={
        "repo": "owner/demo", "title": "From workflow", "head": "task-1", "base": "main",
    }).json()
    assert opened_pr["pull"]["number"] == 4

    commented = client.post("/api/prs/1/comments", json={"repo": "owner/demo", "body": "nice"}).json()
    assert commented["comment"]["id"] == 9

    closed = client.patch("/api/issues/2", json={"repo": "owner/demo", "state": "closed"}).json()
    assert closed["issue"]["state"] == "closed"


def test_discussions_endpoint(client, monkeypatch):
    monkeypatch.setattr("git_tool.routes._client", lambda: FakeGitHub())

    data = client.get("/api/discussions", params={"repo": "owner/demo"}).json()
    assert data["discussions"][0]["number"] == 5
    assert data["discussions"][0]["category"] == "Ideas"

    assert client.get("/api/discussions", params={"repo": "nope"}).status_code == 400


def test_merge_pull_endpoint(client, monkeypatch):
    monkeypatch.setattr("git_tool.routes._client", lambda: FakeGitHub())

    merged = client.post("/api/prs/1/merge", json={"repo": "owner/demo", "method": "squash"}).json()
    assert merged["result"]["merged"] is True
    assert "squash" in merged["result"]["message"]

    bad = client.post("/api/prs/1/merge", json={"repo": "owner/demo", "method": "fast"})
    assert bad.status_code == 400


def test_settings_and_token_roundtrip(client, monkeypatch):
    state = {"token": ""}
    monkeypatch.setattr("git_tool.routes.keyrouter.get_token", lambda: state["token"])
    monkeypatch.setattr("git_tool.routes.keyrouter.managed", lambda: True)
    monkeypatch.setattr("git_tool.routes.keyrouter.set_token", lambda value: state.update(token=value.strip()))
    monkeypatch.setattr("git_tool.routes.keyrouter.delete_token", lambda: state.update(token=""))

    initial = client.get("/api/settings").json()
    assert initial["github_token"]["has_token"] is False
    assert initial["managed_by_key_router"] is True

    saved = client.put("/api/settings/github-token", json={"value": " ghp_supersecret123 "}).json()
    assert saved["github_token"]["has_token"] is True
    assert saved["github_token"]["preview"].startswith("ghp_")
    assert "ghp_supersecret123" not in json.dumps(saved)

    removed = client.delete("/api/settings/github-token").json()
    assert removed["github_token"]["has_token"] is False


def test_token_value_is_required(client, monkeypatch):
    monkeypatch.setattr("git_tool.routes.keyrouter.managed", lambda: True)
    assert client.put("/api/settings/github-token", json={"value": "   "}).status_code == 400


def test_standalone_mode_cannot_save_token(client, monkeypatch):
    monkeypatch.setattr("git_tool.routes.keyrouter.managed", lambda: False)
    response = client.put("/api/settings/github-token", json={"value": "ghp_x"})
    assert response.status_code == 400


def test_repo_format_is_validated(client, monkeypatch):
    monkeypatch.setattr("git_tool.routes._client", lambda: FakeGitHub())
    assert client.get("/api/prs", params={"repo": "not-a-repo"}).status_code == 400


def test_token_middleware(monkeypatch):
    monkeypatch.setenv("KEY_ROUTER_TOOL_TOKEN", "secret")
    client = TestClient(create_app())

    assert client.get("/health").status_code == 200
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers={"X-Tool-Token": "secret"}).status_code == 200
    assert client.get("/api/status?token=secret").status_code == 200
