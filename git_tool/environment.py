"""Host requirements the tool needs at runtime."""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from typing import Any, Dict, List

_cache: Dict[str, Any] = {}


def _version(binary: str, *args: str) -> str:
    try:
        proc = subprocess.run([binary, *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    output = (proc.stdout or proc.stderr or "").strip().splitlines()
    return output[0].strip() if output else ""


def _clean(value: str, prefix: str) -> str:
    if value.lower().startswith(prefix):
        return value[len(prefix):].strip()
    return value


def checks() -> Dict[str, Any]:
    """Cached once: binaries do not appear while the process is running."""
    if _cache:
        return _cache

    tools: List[Dict[str, Any]] = []

    git_path = shutil.which("git")
    tools.append({
        "name": "git",
        "required": True,
        "found": bool(git_path),
        "version": _clean(_version("git", "--version"), "git version") if git_path else "",
        "path": git_path or "",
    })

    npm_path = shutil.which("npm")
    tools.append({
        "name": "npm",
        "required": False,
        "found": bool(npm_path),
        "version": _version("npm", "--version") if npm_path else "",
        "path": npm_path or "",
    })

    tools.append({
        "name": "python",
        "required": True,
        "found": True,
        "version": platform.python_version(),
        "path": sys.executable,
    })

    _cache.update({
        "ok": all(tool["found"] for tool in tools if tool["required"]),
        "platform": platform.system(),
        "tools": tools,
    })
    return _cache
