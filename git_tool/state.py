"""Persistent tool state: scan cache, GitHub cache, pins and recent repos."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List


def state_dir() -> Path:
    configured = os.environ.get("KEY_ROUTER_TOOL_DATA")
    if configured:
        return Path(configured)
    return Path.home() / ".key-router" / "data" / "git-tool"


def state_path() -> Path:
    return state_dir() / "state.json"


def empty_state() -> Dict[str, Any]:
    return {
        "scan": {
            "roots": [],
            "depth": 3,
            "scanned_at": "",
            "truncated": False,
            "dirs_visited": 0,
            "repos": [],
        },
        "github": {
            "login": "",
            "fetched_at": "",
            "truncated": False,
            "repos": [],
        },
        "pinned": [],
        "last_opened": {},
    }


def _str_list(value: Any) -> List[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _dict_list(value: Any) -> List[Dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def load_state() -> Dict[str, Any]:
    path = state_path()
    if not path.exists():
        return empty_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_state()
    if not isinstance(raw, dict):
        return empty_state()

    state = empty_state()

    scan = raw.get("scan")
    if isinstance(scan, dict):
        state["scan"]["roots"] = _str_list(scan.get("roots"))
        depth = scan.get("depth")
        state["scan"]["depth"] = depth if isinstance(depth, int) and 1 <= depth <= 4 else 3
        state["scan"]["scanned_at"] = scan.get("scanned_at") if isinstance(scan.get("scanned_at"), str) else ""
        state["scan"]["truncated"] = bool(scan.get("truncated"))
        visited = scan.get("dirs_visited")
        state["scan"]["dirs_visited"] = visited if isinstance(visited, int) and visited >= 0 else 0
        state["scan"]["repos"] = _dict_list(scan.get("repos"))

    github = raw.get("github")
    if isinstance(github, dict):
        state["github"]["login"] = github.get("login") if isinstance(github.get("login"), str) else ""
        state["github"]["fetched_at"] = github.get("fetched_at") if isinstance(github.get("fetched_at"), str) else ""
        state["github"]["truncated"] = bool(github.get("truncated"))
        state["github"]["repos"] = _dict_list(github.get("repos"))

    state["pinned"] = _str_list(raw.get("pinned"))

    opened = raw.get("last_opened")
    if isinstance(opened, dict):
        state["last_opened"] = {
            key: value for key, value in opened.items()
            if isinstance(key, str) and isinstance(value, str)
        }

    return state


def save_state(state: Dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
