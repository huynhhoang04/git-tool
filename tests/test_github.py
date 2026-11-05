import httpx
import pytest

from git_tool.github import GitHub, GitHubError


def _client(handler):
    return GitHub("test-token", transport=httpx.MockTransport(handler))


def test_missing_token_raises():
    with pytest.raises(GitHubError) as excinfo:
        GitHub("")
    assert excinfo.value.status == 401


def test_user_and_rate_limit():
    def handler(request):
        if request.url.path == "/user":
            return httpx.Response(200, json={"login": "octocat", "name": "Mona"})
        return httpx.Response(200, json={"resources": {"core": {"limit": 5000, "remaining": 4999, "reset": 1}}})

    client = _client(handler)
    assert client.user() == {"login": "octocat", "name": "Mona"}
    assert client.rate_limit()["remaining"] == 4999
    client.close()


def test_pulls_are_trimmed():
    payload = [{
        "number": 7,
        "title": "Add feature",
        "state": "open",
        "draft": False,
        "body": "body",
        "user": {"login": "octocat"},
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "head": {"ref": "feature"},
        "base": {"ref": "main"},
        "html_url": "https://github.com/owner/repo/pull/7",
        "comments": 3,
        "merged_at": None,
    }]

    def handler(request):
        assert request.url.path == "/repos/owner/repo/pulls"
        return httpx.Response(200, json=payload)

    client = _client(handler)
    pulls = client.pulls("owner", "repo")
    assert pulls[0]["number"] == 7
    assert pulls[0]["head"] == "feature"
    assert pulls[0]["merged"] is False
    client.close()


def test_issues_skip_pull_requests():
    payload = [
        {"number": 1, "title": "real issue", "state": "open", "labels": [{"name": "bug"}]},
        {"number": 2, "title": "a PR", "state": "open", "pull_request": {"url": "x"}},
    ]

    def handler(request):
        return httpx.Response(200, json=payload)

    client = _client(handler)
    issues = client.issues("owner", "repo")
    assert [issue["number"] for issue in issues] == [1]
    assert issues[0]["labels"] == ["bug"]
    client.close()


def test_error_message_is_surfaced():
    def handler(request):
        return httpx.Response(404, json={"message": "Not Found"})

    client = _client(handler)
    with pytest.raises(GitHubError) as excinfo:
        client.pull("owner", "repo", 9)
    assert excinfo.value.status == 404
    assert "Not Found" in str(excinfo.value)
    client.close()


def _repo_json(full_name, **overrides):
    owner, name = full_name.split("/")
    data = {
        "full_name": full_name,
        "name": name,
        "owner": {"login": owner, "type": "User"},
        "private": False,
        "fork": False,
        "archived": False,
        "disabled": False,
        "language": "Python",
        "updated_at": "2026-01-01T00:00:00Z",
        "pushed_at": "2026-01-02T00:00:00Z",
        "default_branch": "main",
        "open_issues_count": 4,
        "html_url": f"https://github.com/{full_name}",
    }
    data.update(overrides)
    return data


def test_repos_by_affiliation_paginates_and_trims():
    def handler(request):
        affiliation = request.url.params.get("affiliation")
        page = int(request.url.params.get("page", "1"))
        if affiliation == "owner":
            if page == 1:
                return httpx.Response(
                    200,
                    json=[_repo_json("me/one")],
                    headers={"link": '<https://api.github.com/user/repos?page=2>; rel="next"'},
                )
            return httpx.Response(200, json=[_repo_json("me/two")])
        if affiliation == "collaborator":
            return httpx.Response(200, json=[_repo_json("other/collab")])
        return httpx.Response(200, json=[_repo_json("org/team")])

    client = _client(handler)
    owner_repos, truncated = client.repos_by_affiliation("owner")
    assert [repo["full_name"] for repo in owner_repos] == ["me/one", "me/two"]
    assert truncated is False
    assert owner_repos[0]["owner"] == "me"
    assert owner_repos[0]["open_issues_count"] == 4

    collab, _ = client.repos_by_affiliation("collaborator")
    assert collab[0]["full_name"] == "other/collab"
    client.close()


def test_repos_pagination_reports_truncation():
    def handler(request):
        return httpx.Response(
            200,
            json=[_repo_json("me/x")],
            headers={"link": '<https://api.github.com/user/repos?page=2>; rel="next"'},
        )

    client = _client(handler)
    repos, truncated = client.repos_by_affiliation("owner")
    assert truncated is True
    assert len(repos) == 5
    client.close()


def test_create_pull_payload():
    captured = {}

    def handler(request):
        captured["body"] = request.read().decode()
        return httpx.Response(201, json={"number": 3, "title": "t", "head": {"ref": "f"}, "base": {"ref": "main"}})

    client = _client(handler)
    pull = client.create_pull("owner", "repo", "t", "f", "main", "body", True)
    assert pull["number"] == 3
    assert '"draft":true' in captured["body"]
    client.close()


def test_discussions_are_trimmed():
    def handler(request):
        assert request.url.path == "/graphql"
        return httpx.Response(200, json={"data": {"repository": {"discussions": {"nodes": [{
            "number": 3,
            "title": "Idea",
            "url": "https://github.com/owner/repo/discussions/3",
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-02T00:00:00Z",
            "author": {"login": "octocat"},
            "category": {"name": "Ideas"},
            "comments": {"totalCount": 4},
        }]}}}})

    client = _client(handler)
    items = client.discussions("owner", "repo")

    assert items == [{
        "number": 3,
        "title": "Idea",
        "url": "https://github.com/owner/repo/discussions/3",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "author": "octocat",
        "category": "Ideas",
        "comments": 4,
    }]
    client.close()


def test_discussions_surface_graphql_errors():
    def handler(request):
        return httpx.Response(200, json={"errors": [{"message": "Resource not accessible by personal access token"}]})

    client = _client(handler)
    with pytest.raises(GitHubError) as excinfo:
        client.discussions("owner", "repo")
    assert "not accessible" in str(excinfo.value)
    client.close()


def test_discussions_missing_repository():
    def handler(request):
        return httpx.Response(200, json={"data": {"repository": None}})

    client = _client(handler)
    with pytest.raises(GitHubError) as excinfo:
        client.discussions("owner", "repo")
    assert excinfo.value.status == 404
    client.close()
