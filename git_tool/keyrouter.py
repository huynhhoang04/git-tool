"""Bridge to key-router for tool-managed credentials.

The token lives in key-router's `secrets.json`; the tool only ever sees it
through key-router's tool-token-protected credential endpoint (or the
`GITHUB_TOKEN` env when running standalone).
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import httpx

BASE = (os.environ.get("KEY_ROUTER_URL") or "").rstrip("/")
TOOL_ID = os.environ.get("KEY_ROUTER_TOOL_ID") or "git-tool"
TOOL_TOKEN = os.environ.get("KEY_ROUTER_TOOL_TOKEN") or ""
ENV_FALLBACK = os.environ.get("GITHUB_TOKEN") or ""

_cache: Dict[str, Optional[str]] = {"token": None}
_roots_cache: Dict[str, Any] = {"at": 0.0, "roots": []}


def managed() -> bool:
    return bool(BASE and TOOL_TOKEN)


def _headers() -> Dict[str, str]:
    return {"X-Tool-Token": TOOL_TOKEN}


def _url(name: str) -> str:
    return f"{BASE}/api/tools/{TOOL_ID}/credentials/{name}"


def _error(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail", "")) or f"key-router returned {response.status_code}"
    except Exception:
        return f"key-router returned {response.status_code}"


def get_token() -> str:
    if _cache["token"] is not None:
        return _cache["token"]
    if managed():
        try:
            response = httpx.get(_url("github"), headers=_headers(), timeout=3.0)
            if response.status_code == 200:
                _cache["token"] = response.json().get("value", "") or ""
                return _cache["token"]
            if response.status_code == 404:
                _cache["token"] = ""
                return ""
        except Exception:
            pass
    _cache["token"] = ENV_FALLBACK
    return _cache["token"]


def set_token(value: str) -> None:
    if not managed():
        raise RuntimeError("Standalone mode reads GITHUB_TOKEN from the environment; start the tool from key-router to save a token.")
    response = httpx.put(_url("github"), headers=_headers(), json={"value": value}, timeout=5.0)
    if response.status_code >= 400:
        raise RuntimeError(_error(response))
    _cache["token"] = value.strip()


def delete_token() -> None:
    if not managed():
        raise RuntimeError("Standalone mode reads GITHUB_TOKEN from the environment.")
    response = httpx.delete(_url("github"), headers=_headers(), timeout=5.0)
    if response.status_code not in (200, 404):
        raise RuntimeError(_error(response))
    _cache["token"] = ""


def mask(value: str) -> str:
    if not value:
        return ""
    return "****" if len(value) <= 8 else f"{value[:4]}****{value[-4:]}"


def allowed_roots() -> List[str]:
    """Scan roots configured for agents in key-router, cached briefly."""
    if not BASE:
        return []
    now = time.time()
    if now - float(_roots_cache["at"]) < 60:
        return list(_roots_cache["roots"])

    try:
        response = httpx.get(f"{BASE}/api/agents", timeout=3.0)
        if response.status_code == 200:
            settings = response.json().get("settings", {})
            roots = [
                root for root in settings.get("allowed_roots", [])
                if isinstance(root, str) and root
            ]
            _roots_cache.update({"at": now, "roots": roots})
            return list(roots)
    except Exception:
        pass
    return list(_roots_cache["roots"])
