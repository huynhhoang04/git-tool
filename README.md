# Git workspace

A small Git tool for [key-router](https://github.com/momadhuynh04/key-router): branches with
local/remote comparison and a commit graph, pull requests (mine + owner view), issues &
discussions, and a guided collaborator workflow (start task → merge base → commit → push → open PR).

Standalone FastAPI backend + a React/Vite UI served from `static/`.

## Requires

- Python 3.11+ and `git`
- A GitHub token with `repo` scope (read for browsing; write for PRs/issues/push)

The header shows what was detected on the host (`git`, `npm`, `python`); a required tool that is
missing is highlighted in red. `npm` is optional and only needed to rebuild the UI.

## Run

```bash
pip install -r requirements.txt
python -m git_tool --port 9100          # http://127.0.0.1:9100
```

Environment (set by key-router when it runs the tool; all optional standalone):

| Variable | Meaning |
| --- | --- |
| `GITHUB_TOKEN` | token used when running without key-router |
| `KEY_ROUTER_URL` / `KEY_ROUTER_TOOL_TOKEN` | read the token from key-router and validate `/api/*` |
| `KEY_ROUTER_TOOL_DATA` | state directory (default `.key-router/data/git-tool` in this checkout) |

## UI

`static/` holds the built UI, so the tool runs without Node. After changing `webui/src`:

```bash
cd webui && npm install && npm run build
```

## Install from key-router

Tools tab → install `owner/repo` (this repository) or register this folder locally.

## Tests

```bash
python -m pytest tests/
```

CI (`.github/workflows/ci.yml`) runs the suite on Linux and Windows, and builds the UI on Linux.
