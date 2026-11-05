import os
import subprocess

import pytest

from git_tool import discovery


def git(path, *args):
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def make_repo(path, remote=None):
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.email", "tester@example.com")
    git(path, "config", "user.name", "Tester")
    (path / "a.txt").write_text("a", encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-m", "init")
    if remote:
        git(path, "remote", "add", "origin", remote)
    return path


def _paths(scan):
    return {os.path.realpath(repo["path"]) for repo in scan["repos"]}


def test_scan_finds_repos_up_to_depth(tmp_path):
    make_repo(tmp_path / "direct")
    make_repo(tmp_path / "team" / "app")
    make_repo(tmp_path / "team" / "deeper" / "app2")

    scan = discovery.scan_local([str(tmp_path)], 3)

    assert _paths(scan) == {
        os.path.realpath(tmp_path / "direct"),
        os.path.realpath(tmp_path / "team" / "app"),
        os.path.realpath(tmp_path / "team" / "deeper" / "app2"),
    }
    assert scan["truncated"] is False
    assert scan["dirs_visited"] >= 3


def test_scan_respects_depth(tmp_path):
    make_repo(tmp_path / "direct")
    make_repo(tmp_path / "team" / "app")

    scan = discovery.scan_local([str(tmp_path)], 1)

    assert _paths(scan) == {os.path.realpath(tmp_path / "direct")}


def test_scan_prunes_heavy_and_hidden_dirs(tmp_path):
    make_repo(tmp_path / "node_modules" / "pkg")
    make_repo(tmp_path / ".hidden" / "pkg")
    make_repo(tmp_path / "visible")

    scan = discovery.scan_local([str(tmp_path)], 3)

    assert _paths(scan) == {os.path.realpath(tmp_path / "visible")}


def test_scan_does_not_descend_into_a_repo(tmp_path):
    outer = make_repo(tmp_path / "outer")
    make_repo(outer / "inner")

    scan = discovery.scan_local([str(tmp_path)], 3)

    assert _paths(scan) == {os.path.realpath(outer)}


def test_scan_detects_worktrees(tmp_path):
    main = make_repo(tmp_path / "main", remote="git@github.com:owner/demo.git")
    worktree = tmp_path / "worktree"
    git(main, "worktree", "add", str(worktree), "-b", "feature")

    scan = discovery.scan_local([str(tmp_path)], 3)

    assert os.path.realpath(worktree) in _paths(scan)
    branch = next(repo["branch"] for repo in scan["repos"] if os.path.realpath(repo["path"]) == os.path.realpath(worktree))
    assert branch == "feature"


def test_scan_includes_root_repo(tmp_path):
    repo = make_repo(tmp_path / "repo")
    scan = discovery.scan_local([str(repo)], 2)
    assert _paths(scan) == {os.path.realpath(repo)}


def _gh(full_name, role="owner", updated="2026-01-01T00:00:00Z"):
    owner, name = full_name.split("/")
    return {
        "full_name": full_name,
        "name": name,
        "owner": owner,
        "role": role,
        "private": False,
        "fork": False,
        "archived": False,
        "language": "Python",
        "updated_at": updated,
        "pushed_at": updated,
        "default_branch": "main",
        "open_issues_count": 0,
        "html_url": f"https://github.com/{full_name}",
    }


def _local(path, full_name="me/demo", branch="main"):
    owner, name = full_name.split("/")
    return {
        "path": str(path),
        "name": name,
        "remote_url": f"https://github.com/{full_name}.git",
        "branch": branch,
        "last_commit": "2026-01-02T00:00:00+00:00",
        "host": "github.com",
        "owner": owner,
        "repo": name,
    }


def test_combine_marks_local_presence_and_roles(tmp_path):
    local = _local(tmp_path / "demo")
    github = {"login": "me", "fetched_at": "2026-01-03T00:00:00", "truncated": False,
              "repos": [_gh("me/demo", "owner"), _gh("other/remote", "collaborator")]}
    scan = {"roots": [str(tmp_path)], "depth": 3, "scanned_at": "2026-01-03T00:00:00",
            "truncated": False, "dirs_visited": 3, "repos": [local]}

    out = discovery.combine(github, scan, {"pinned": [], "last_opened": {}})
    by_key = {item["key"]: item for item in out["repos"]}

    assert by_key["gh:me/demo"]["local"] is True
    assert by_key["gh:me/demo"]["local_status"] == "present"
    assert by_key["gh:me/demo"]["role"] == "owner"
    assert by_key["gh:other/remote"]["local"] is False
    assert by_key["gh:other/remote"]["local_status"] == "not_found_or_outside_roots"
    assert out["meta"]["counts"]["remote"] == 1


def test_combine_token_decides_visibility(tmp_path):
    github = {"login": "me", "fetched_at": "2026-01-03T00:00:00", "truncated": False,
              "repos": [_gh("me/demo")]}
    unreachable = _local(tmp_path / "secret", "me/secret-clone")
    no_remote = {
        "path": str(tmp_path / "scratch"),
        "name": "scratch",
        "remote_url": "",
        "branch": "main",
        "last_commit": "",
        "host": "",
        "owner": "",
        "repo": "",
    }
    scan = {"roots": [str(tmp_path)], "depth": 3, "scanned_at": "", "truncated": False,
            "dirs_visited": 2, "repos": [_local(tmp_path / "demo"), unreachable, no_remote]}

    out = discovery.combine(github, scan, {})

    assert out["meta"]["source"] == "github"
    assert [item["key"] for item in out["repos"]] == ["gh:me/demo"]
    assert out["repos"][0]["local"] is True


def test_combine_local_repo_without_github_access(tmp_path):
    local = _local(tmp_path / "demo", "me/private-demo")
    scan = {"roots": [], "depth": 3, "scanned_at": "", "truncated": False, "dirs_visited": 0, "repos": [local]}

    out = discovery.combine({"repos": [], "login": "", "fetched_at": "", "truncated": False}, scan, {})
    item = out["repos"][0]

    assert out["meta"]["source"] == "local"
    assert item["key"] == "gh:me/private-demo"
    assert item["github"] is False
    assert item["role"] == "local"
    assert item["local"] is True


def test_combine_sorts_pinned_then_opened(tmp_path):
    local_a = _local(tmp_path / "a", "me/a")
    local_b = _local(tmp_path / "b", "me/b")
    github = {"login": "me", "fetched_at": "", "truncated": False,
              "repos": [_gh("me/a"), _gh("me/b"), _gh("me/c")]}
    scan = {"roots": [], "depth": 3, "scanned_at": "", "truncated": False, "dirs_visited": 0,
            "repos": [local_a, local_b]}
    state = {
        "pinned": ["gh:me/b"],
        "last_opened": {"gh:me/c": "2026-06-01T00:00:00"},
    }

    out = discovery.combine(github, scan, state)

    assert [item["key"] for item in out["repos"]] == ["gh:me/b", "gh:me/c", "gh:me/a"]


def test_github_repo_precedence_in_fetch():
    gh = _gh("me/demo", "organization_member")
    assert discovery.ROLE_PRIORITY[gh["role"]] == 2
    assert discovery.ROLE_PRIORITY["owner"] < discovery.ROLE_PRIORITY["collaborator"]
