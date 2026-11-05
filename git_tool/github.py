"""Minimal GitHub REST client (PAT from the environment)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import httpx

API_URL = "https://api.github.com"
GRAPHQL_URL = "https://api.github.com/graphql"


class GitHubError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _trim_pull(pull: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "number": pull.get("number"),
        "title": pull.get("title", ""),
        "state": pull.get("state", ""),
        "draft": bool(pull.get("draft")),
        "body": pull.get("body") or "",
        "user": (pull.get("user") or {}).get("login", ""),
        "created_at": pull.get("created_at", ""),
        "updated_at": pull.get("updated_at", ""),
        "head": (pull.get("head") or {}).get("ref", ""),
        "base": (pull.get("base") or {}).get("ref", ""),
        "html_url": pull.get("html_url", ""),
        "comments": pull.get("comments", 0),
        "merged": pull.get("merged_at") is not None,
    }


def _trim_repo(repo: Dict[str, Any]) -> Dict[str, Any]:
    owner = repo.get("owner") or {}
    return {
        "full_name": repo.get("full_name", ""),
        "name": repo.get("name", ""),
        "owner": owner.get("login", ""),
        "owner_type": owner.get("type", ""),
        "private": bool(repo.get("private")),
        "fork": bool(repo.get("fork")),
        "archived": bool(repo.get("archived")),
        "disabled": bool(repo.get("disabled")),
        "language": repo.get("language") or "",
        "updated_at": repo.get("updated_at", ""),
        "pushed_at": repo.get("pushed_at", ""),
        "default_branch": repo.get("default_branch", ""),
        "open_issues_count": repo.get("open_issues_count", 0),
        "html_url": repo.get("html_url", ""),
    }


def _trim_issue(issue: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "number": issue.get("number"),
        "title": issue.get("title", ""),
        "state": issue.get("state", ""),
        "body": issue.get("body") or "",
        "user": (issue.get("user") or {}).get("login", ""),
        "created_at": issue.get("created_at", ""),
        "updated_at": issue.get("updated_at", ""),
        "labels": [label.get("name", "") for label in issue.get("labels", []) if isinstance(label, dict)],
        "html_url": issue.get("html_url", ""),
        "comments": issue.get("comments", 0),
    }


class GitHub:
    def __init__(self, token: str, transport: Optional[httpx.BaseTransport] = None):
        if not token:
            raise GitHubError(401, "GitHub token is missing. Add it in this tool's Settings tab.")
        self._client = httpx.Client(
            base_url=API_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "key-router-git-tool",
            },
            timeout=20.0,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _check(self, response: httpx.Response) -> None:
        if response.status_code >= 400:
            try:
                message = response.json().get("message", response.text)
            except Exception:
                message = response.text
            raise GitHubError(response.status_code, message or f"GitHub returned {response.status_code}")

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._client.request(method, path, **kwargs)
        self._check(response)
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    def _paged(self, path: str, params: Dict[str, Any], max_pages: int = 5) -> Tuple[List[Dict[str, Any]], bool]:
        items: List[Dict[str, Any]] = []
        page = 1
        truncated = False
        while True:
            response = self._client.get(
                path,
                params={**params, "per_page": 100, "page": page},
            )
            self._check(response)
            data = response.json()
            if isinstance(data, list):
                items.extend(item for item in data if isinstance(item, dict))
            has_next = 'rel="next"' in (response.headers.get("link") or "")
            if not has_next:
                break
            if page >= max_pages:
                truncated = True
                break
            page += 1
        return items, truncated

    def repos_by_affiliation(self, affiliation: str) -> Tuple[List[Dict[str, Any]], bool]:
        items, truncated = self._paged(
            "/user/repos",
            {"affiliation": affiliation, "sort": "updated", "direction": "desc"},
        )
        return [_trim_repo(item) for item in items], truncated

    def graphql(self, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        response = self._client.post(GRAPHQL_URL, json={"query": query, "variables": variables})
        self._check(response)
        data = response.json()
        if data.get("errors"):
            message = "; ".join(item.get("message", "") for item in data["errors"] if isinstance(item, dict))
            raise GitHubError(400, message or "GraphQL request failed")
        return data.get("data") or {}

    def discussions(self, owner: str, repo: str, limit: int = 30) -> List[Dict[str, Any]]:
        query = """
        query($owner: String!, $name: String!, $limit: Int!) {
          repository(owner: $owner, name: $name) {
            discussions(first: $limit, orderBy: {field: UPDATED_AT, direction: DESC}) {
              nodes {
                number
                title
                url
                createdAt
                updatedAt
                author { login }
                category { name }
                comments { totalCount }
              }
            }
          }
        }
        """
        data = self.graphql(query, {"owner": owner, "name": repo, "limit": limit})
        repository = data.get("repository")
        if repository is None:
            raise GitHubError(404, f"{owner}/{repo} not found or discussions are not accessible")
        nodes = ((repository.get("discussions") or {}).get("nodes") or [])
        return [
            {
                "number": node.get("number"),
                "title": node.get("title", ""),
                "url": node.get("url", ""),
                "created_at": node.get("createdAt", ""),
                "updated_at": node.get("updatedAt", ""),
                "author": (node.get("author") or {}).get("login", ""),
                "category": (node.get("category") or {}).get("name", ""),
                "comments": (node.get("comments") or {}).get("totalCount", 0),
            }
            for node in nodes
            if isinstance(node, dict)
        ]

    def user(self) -> Dict[str, Any]:
        data = self._request("GET", "/user")
        return {"login": data.get("login", ""), "name": data.get("name", "")}

    def rate_limit(self) -> Dict[str, Any]:
        data = self._request("GET", "/rate_limit")
        core = (data.get("resources") or {}).get("core", {})
        return {
            "limit": core.get("limit", 0),
            "remaining": core.get("remaining", 0),
            "reset": core.get("reset", 0),
        }

    def pulls(self, owner: str, repo: str, state: str = "open") -> List[Dict[str, Any]]:
        data = self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params={"state": state, "per_page": 100, "sort": "updated", "direction": "desc"},
        )
        return [_trim_pull(item) for item in data]

    def pull(self, owner: str, repo: str, number: int) -> Dict[str, Any]:
        return _trim_pull(self._request("GET", f"/repos/{owner}/{repo}/pulls/{number}"))

    def create_pull(
        self, owner: str, repo: str, title: str, head: str, base: str, body: str = "", draft: bool = False
    ) -> Dict[str, Any]:
        payload = {"title": title, "head": head, "base": base, "body": body, "draft": draft}
        return _trim_pull(self._request("POST", f"/repos/{owner}/{repo}/pulls", json=payload))

    def comment(self, owner: str, repo: str, number: int, body: str) -> Dict[str, Any]:
        data = self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{number}/comments",
            json={"body": body},
        )
        return {"id": data.get("id"), "html_url": data.get("html_url", "")}

    def comments(self, owner: str, repo: str, number: int) -> List[Dict[str, Any]]:
        data = self._request(
            "GET",
            f"/repos/{owner}/{repo}/issues/{number}/comments",
            params={"per_page": 50},
        )
        return [
            {
                "id": item.get("id"),
                "user": (item.get("user") or {}).get("login", ""),
                "body": item.get("body") or "",
                "created_at": item.get("created_at", ""),
            }
            for item in data
        ]

    def issues(self, owner: str, repo: str, state: str = "open") -> List[Dict[str, Any]]:
        data = self._request(
            "GET",
            f"/repos/{owner}/{repo}/issues",
            params={"state": state, "per_page": 100, "sort": "updated", "direction": "desc"},
        )
        return [_trim_issue(item) for item in data if "pull_request" not in item]

    def issue(self, owner: str, repo: str, number: int) -> Dict[str, Any]:
        return _trim_issue(self._request("GET", f"/repos/{owner}/{repo}/issues/{number}"))

    def create_issue(
        self, owner: str, repo: str, title: str, body: str = "", labels: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        return _trim_issue(self._request("POST", f"/repos/{owner}/{repo}/issues", json=payload))

    def merge_pull(
        self, owner: str, repo: str, number: int, method: str = "merge"
    ) -> Dict[str, Any]:
        data = self._request(
            "PUT",
            f"/repos/{owner}/{repo}/pulls/{number}/merge",
            json={"merge_method": method},
        )
        return {
            "merged": bool(data.get("merged")),
            "message": data.get("message", ""),
            "sha": data.get("sha", ""),
        }

    def update_issue(self, owner: str, repo: str, number: int, state: str) -> Dict[str, Any]:
        return _trim_issue(
            self._request("PATCH", f"/repos/{owner}/{repo}/issues/{number}", json={"state": state})
        )
