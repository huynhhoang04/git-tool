import subprocess

import pytest

from git_tool import local_git


def git(path, *args):
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    )


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
    git(path, "remote", "add", "origin", "git@github.com:owner/demo.git")
    return path


def test_repo_info(repo):
    info = local_git.repo_info(str(repo))
    assert info["owner"] == "owner"
    assert info["repo"] == "demo"
    assert info["host"] == "github.com"
    assert info["branch"] == "main"
    assert info["dirty"] is False
    assert info["changed_files"] == 0


def test_repo_info_dirty(repo):
    (repo / "b.txt").write_text("b", encoding="utf-8")
    info = local_git.repo_info(str(repo))
    assert info["dirty"] is True
    assert info["changed_files"] == 1


def test_branches_lists_current_and_last_commit(repo):
    git(repo, "switch", "-c", "feature")
    data = local_git.branches(str(repo))
    names = {branch["name"] for branch in data["local"]}
    assert {"main", "feature"} <= names
    current = next(branch for branch in data["local"] if branch["current"])
    assert current["name"] == "feature"
    assert current["last_commit"]["subject"] == "first commit"
    assert current["last_commit"]["author"] == "Tester"


def test_create_and_switch_branch(repo):
    local_git.create_branch(str(repo), "topic")
    assert local_git.repo_info(str(repo))["branch"] == "topic"
    local_git.switch_branch(str(repo), "main")
    assert local_git.repo_info(str(repo))["branch"] == "main"


def test_bad_branch_name(repo):
    with pytest.raises(local_git.GitError):
        local_git.create_branch(str(repo), "bad..name")


def _commit(path, name, message):
    (path / name).write_text(name, encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-m", message)


def test_compare_reports_ahead_behind_commits_and_files(repo):
    git(repo, "switch", "-c", "feature")
    _commit(repo, "b.txt", "feat b")
    _commit(repo, "c.txt", "feat c")
    git(repo, "switch", "main")
    _commit(repo, "d.txt", "main d")
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    git(repo, "switch", "feature")

    data = local_git.compare(str(repo), "origin/main", "feature")

    assert (data["ahead"], data["behind"]) == (2, 1)
    assert [commit["subject"] for commit in data["head_only"]] == ["feat c", "feat b"]
    assert [commit["subject"] for commit in data["base_only"]] == ["main d"]
    assert {item["path"] for item in data["head_files"]} == {"b.txt", "c.txt"}
    assert [item["path"] for item in data["base_files"]] == ["d.txt"]
    assert data["merge_base"]


def test_branches_reports_divergence_against_remotes(repo):
    git(repo, "switch", "-c", "feature")
    _commit(repo, "b.txt", "feat")
    git(repo, "switch", "main")
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    git(repo, "update-ref", "refs/remotes/origin/feature", "feature")
    git(repo, "switch", "feature")

    data = local_git.branches(str(repo), "feature")

    assert data["head"] == "feature"
    assert data["divergence"]["origin/main"] == {"ahead": 1, "behind": 0}
    assert data["divergence"]["origin/feature"] == {"ahead": 0, "behind": 0}


def test_branches_reports_default_and_default_divergence(repo):
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    git(repo, "switch", "-c", "feature")
    _commit(repo, "b.txt", "feat")
    git(repo, "update-ref", "refs/remotes/origin/feature", "feature")
    git(repo, "switch", "main")

    data = local_git.branches(str(repo))

    assert data["default_base"] == "origin/main"
    assert data["default_divergence"]["origin/feature"] == {"ahead": 1, "behind": 0}


def test_history_includes_merges(repo):
    git(repo, "switch", "-c", "feature")
    _commit(repo, "b.txt", "feat")
    git(repo, "switch", "main")
    _commit(repo, "c.txt", "main work")
    git(repo, "merge", "--no-ff", "-m", "merge feature", "feature")

    data = local_git.history(str(repo), "main", limit=10)

    assert data["ref"] == "main"
    assert data["commits"][0]["subject"] == "merge feature"
    assert len(data["commits"][0]["parents"]) == 2
    assert {commit["subject"] for commit in data["commits"]} >= {"feat", "main work", "merge feature"}
    assert all(len(commit["short"]) >= 7 for commit in data["commits"])


def test_history_rejects_unknown_ref(repo):
    with pytest.raises(local_git.GitError):
        local_git.history(str(repo), "nope")


def test_branches_skips_remote_head_symref(repo):
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

    data = local_git.branches(str(repo))

    assert [branch["name"] for branch in data["remote"]] == ["origin/main"]
    assert "origin" not in data["divergence"]


def test_branches_defaults_head_to_current(repo):
    git(repo, "update-ref", "refs/remotes/origin/main", "main")

    data = local_git.branches(str(repo))

    assert data["head"] == "main"
    assert data["divergence"]["origin/main"] == {"ahead": 0, "behind": 0}


def test_branches_rejects_unknown_head(repo):
    with pytest.raises(local_git.GitError):
        local_git.branches(str(repo), "nope")


def test_compare_rejects_option_like_ref(repo):
    with pytest.raises(local_git.GitError):
        local_git.compare(str(repo), "--output=/tmp/leak", "main")


def test_delete_branch(repo):
    git(repo, "branch", "topic")

    assert local_git.delete_branch(str(repo), "topic") == {"deleted": "topic", "forced": False}
    assert "topic" not in {branch["name"] for branch in local_git.branches(str(repo))["local"]}

    with pytest.raises(local_git.GitError):
        local_git.delete_branch(str(repo), "main")


def test_not_a_repo(tmp_path):
    assert local_git.is_repo(str(tmp_path)) is False
    with pytest.raises(local_git.GitError):
        local_git.repo_info(str(tmp_path))


@pytest.mark.parametrize("remote,expected", [
    ("https://github.com/owner/repo.git", ("github.com", "owner", "repo")),
    ("https://user@github.com/owner/repo", ("github.com", "owner", "repo")),
    ("git@github.com:owner/repo.git", ("github.com", "owner", "repo")),
    ("ssh://git@github.com/owner/repo.git", ("github.com", "owner", "repo")),
])
def test_parse_remote(remote, expected):
    parsed = local_git.parse_remote(remote)
    assert (parsed["host"], parsed["owner"], parsed["repo"]) == expected


def test_parse_remote_invalid():
    assert local_git.parse_remote("") == {}
    assert local_git.parse_remote("/local/path") == {}
