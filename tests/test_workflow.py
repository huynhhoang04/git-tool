import subprocess

import pytest
from fastapi.testclient import TestClient

from git_tool import local_git
from git_tool.app import create_app


def git(path, *args):
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(autouse=True)
def tool_env(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("KEY_ROUTER_TOOL_TOKEN", raising=False)
    monkeypatch.setenv("KEY_ROUTER_TOOL_DATA", str(tmp_path / "tool-data"))


@pytest.fixture
def remote(tmp_path):
    """A bare origin plus one clone with main pushed to it."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)

    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-b", "main")
    git(seed, "config", "user.email", "tester@example.com")
    git(seed, "config", "user.name", "Tester")
    (seed / "a.txt").write_text("a", encoding="utf-8")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "init")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-u", "origin", "main")

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(origin), str(clone)], check=True, capture_output=True)
    git(clone, "config", "user.email", "tester@example.com")
    git(clone, "config", "user.name", "Tester")

    return {"origin": origin, "seed": seed, "clone": clone}


@pytest.fixture
def client():
    return TestClient(create_app())


def _advance_main(remote, name="b.txt", message="upstream work"):
    seed = remote["seed"]
    (seed / name).write_text(name, encoding="utf-8")
    git(seed, "add", ".")
    git(seed, "commit", "-m", message)
    git(seed, "push", "origin", "main")


def test_start_creates_branch_from_base(client, remote):
    clone = str(remote["clone"])

    data = client.post("/api/workflow/start", json={
        "path": clone, "base": "main", "branch": "task-1",
    }).json()

    assert data["ok"] is True
    assert [step["name"] for step in data["steps"]] == [
        "checkout main", "pull origin main", "create task-1 from main",
    ]
    assert all(step["ok"] for step in data["steps"])
    assert local_git.repo_info(clone)["branch"] == "task-1"


def test_start_reports_failure_and_stops(client, remote):
    data = client.post("/api/workflow/start", json={
        "path": str(remote["clone"]), "base": "nope", "branch": "task-1",
    }).json()

    assert data["ok"] is False
    assert data["steps"][0]["ok"] is False
    assert len(data["steps"]) == 1


def test_sync_merges_base_into_task_branch(client, remote):
    clone = str(remote["clone"])
    client.post("/api/workflow/start", json={"path": clone, "base": "main", "branch": "task-1"})
    (remote["clone"] / "task.txt").write_text("task", encoding="utf-8")
    git(remote["clone"], "add", ".")
    git(remote["clone"], "commit", "-m", "task work")

    _advance_main(remote)

    data = client.post("/api/workflow/sync", json={
        "path": clone, "base": "main", "branch": "task-1",
    }).json()

    assert data["ok"] is True
    assert [step["name"] for step in data["steps"]] == [
        "checkout main", "pull origin main", "checkout task-1", "merge main",
    ]
    assert local_git.repo_info(clone)["branch"] == "task-1"
    log = git(remote["clone"], "log", "--oneline", "-3").stdout
    assert "upstream work" in log


def test_commit_and_push(client, remote):
    clone = str(remote["clone"])
    client.post("/api/workflow/start", json={"path": clone, "base": "main", "branch": "task-2"})
    (remote["clone"] / "b.txt").write_text("b", encoding="utf-8")

    committed = client.post("/api/commit", json={"path": clone, "message": "add b"}).json()
    assert committed["files"] == ["b.txt"]
    assert committed["sha"]

    pushed = client.post("/api/push", json={"path": clone, "branch": "task-2"})
    assert pushed.status_code == 200
    refs = subprocess.run(
        ["git", "-C", str(remote["origin"]), "show-ref"],
        check=True, capture_output=True, text=True,
    ).stdout
    assert "refs/heads/task-2" in refs


def test_commit_requires_changes(client, remote):
    response = client.post("/api/commit", json={"path": str(remote["clone"]), "message": "empty"})
    assert response.status_code == 400
    assert "nothing to commit" in response.json()["detail"]


def test_push_uses_current_branch(client, remote):
    clone = str(remote["clone"])
    client.post("/api/workflow/start", json={"path": clone, "base": "main", "branch": "task-3"})
    (remote["clone"] / "c.txt").write_text("c", encoding="utf-8")
    client.post("/api/commit", json={"path": clone, "message": "add c"})

    pushed = client.post("/api/push", json={"path": clone}).json()
    assert pushed["branch"] == "task-3"
