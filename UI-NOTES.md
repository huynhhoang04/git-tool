# UI notes — Git workspace

Working notes for the UI. Status after the second redesign pass.

## 1. Design language — follow key-router, not "dashboard cards"

The tool is embedded in the key-router dashboard iframe, so it uses the same tokens
(`webui/tailwind.config.js`):

| Token | Value |
| --- | --- |
| `surface-950` (page) | `#0a0a0b` |
| `surface-900` (sidebar) | `#141415` |
| `surface-850` (rows/buttons) | `#1a1a1d` |
| `surface-800` (hover/active) | `#232326` |
| `border` | `#262629` · strong `#3a3a3f` |
| text | primary `#fafafa` · secondary `#a1a1aa` · muted `#71717a` |
| brand | `#38bdf8` (sky) · `brand-bg` 10% · `brand-border` 30% |
| accent / success / danger | `#f59e0b` / `#22c55e` / `#ef4444` |

Rules learned from the dashboard:

- **Structure carries meaning**: things you pick from go to the left **sidebar**; global context
  (brand, account, status) goes to the top **header**; everything else lives in a flat
  **content** area.
- **No card-in-card**: sections are separated by 1px borders and spacing, not by rounded boxes.
  Rows are transparent until hover. Only the detail column gets a border (left).
- Buttons/chips are `rounded-full`; inputs/rows are 8px. Primary uses brand sky with dark ink.
- Typography: Inter/system sans for UI, system mono for refs, SHAs and paths.

## 2. Shell

```
.sidebar (268px, full height, border-right)     .workspace
  Repositories header + Scan                      .topbar    brand · @user · API rate
  search                                          .repo-bar  selected repo + actions
  All/Local/Remote/Pinned chips                   .tabs      underline, one per view
  repo list (scrolls)                             .content   scrollable
  Symbols legend (bottom)
```

- `Repositories` is a sidebar column, not a box.
- Brand, account and rate limit are a header row, not floating pills in a card.
- The selected repo (name, role, language, path, branch, Refresh/Fetch/GitHub) is the second
  header row, which replaces the old card.

## 3. Compare buttons

| Where | Effect |
| --- | --- |
| Local row → **Compare** | `compare(base = upstream, head = local branch)` |
| Remote row → **Compare** | `compare(base = selected base, head = that branch)` |
| Base row (`origin/main` when it is the base) | no Compare button, only `History` + `base` badge |

The base row duplication is gone. Next time, always label both refs on a compare control.

## 4. Branches page layout

- One column when nothing is open (hint line at the top), two columns
  (`1fr | 380–500px`) when Compare/History is open; the detail column is separated by
  `border-left` and stretches to the content height.
- Branch rows: `name` → meta line (sha · subject · author · time) → right side
  (`↑n ↓n` deltas + actions). Actions are at 70% opacity until hover/focus.
- Graph rows are a fixed 34px so lane geometry stays aligned; meta is `nowrap` and clipped;
  max 2 ref badges per commit.

## 5. Symbols legend

The bottom of the sidebar has a collapsible **Symbols** block: current-branch dot, `↑n` / `↓n`,
merge node, `A M D R` file statuses, pinned star. Keep it in sync whenever a new glyph is
introduced.

## 5b. History graph semantics (kept deliberately simple)

Lane index is **not** a branch identity, so the graph does not paint a rainbow. It uses two
colours plus shape:

- **blue line** = the history of the ref you opened (`origin/main` in the header);
- **gray line** = a line that came in from a merge;
- **dot** = commit, **ring** = merge commit (two parents);
- **vertical segment** = that line continues to the next row;
- **curve** = a line splitting off (fork) or joining back (merge).

The legend is rendered inline at the top of the graph panel, not only in the sidebar, because
that is where the question "what is this dot/curve?" comes up. If branch-specific colouring is
wanted later, colour by ref **decorations** (a real identity) and label each lane with its ref,
never by lane index.

## 6. Still open

- Keyboard navigation between branch rows (`↑/↓`, `Enter` to compare).
- Deep link: persist repo / tab / open compare in the URL.
- Compare: swap control to flip head/base.
- Graph: click a commit to scroll to it; optional ref filter.
- Middle-ellipsis for long branch names so the suffix stays visible.

## 7. Workflow tab

Three sections, same flat language as the rest (no cards):

1. **Start a task** — `checkout <base> → pull origin <base> → checkout -b <branch>`.
2. **Update my branch with the base** — `checkout <base> → pull → checkout <branch> → merge <base>`;
   the Run button is disabled while base === branch and a hint explains why.
3. **Commit & push** — `add -A → commit -m "<message>" → push -u origin <current>`.

Each run renders a step log (`✓`/`✗`, git output, committed files). Logs are kept per section.

Defaults come from `/api/branches`: base = the local branch tracking the remote default, sync branch
= current branch if it differs from the base, otherwise the first other local branch.

Pull requests: the detail pane merges open, unmerged PRs with a method selector (merge/squash/rebase);
a `mine` chip filters the list to the signed-in login.

## 8. Pull requests and roles

- Creation only happens at the end of **Workflow → Open pull request** (title prefilled with the
  branch, draft option, returns the GitHub link). No standalone creation form.
- **My pull requests** (everyone): PRs authored by the signed-in login, state chips, merged/closed
  pills, `Open ↗` link per row; detail shows body, comments and a comment box (no merge).
- **Pull requests** (owners only, `repo.role === 'owner'`): same list for the whole repo plus the
  merge control (merge commit / squash / rebase) in the detail.
- Both pages request `state=all` and filter client-side, so the tab badge counts open PRs and the
  `open` chip still shows merged history when you switch states.

## 9. Issues, discussions and refresh

- **Issues & discussions** is one page: a segmented control switches the list. Issues keep state
  chips, label pills, detail (body, comments, comment box, open/close) and a collapsible
  "New issue" form. Discussions are read-only rows (title, category, author, comment count) that
  link out; a GraphQL/permission failure shows a warning banner, never a blank page.
- **Sync** in the repo header replaces Refresh + Fetch: `git fetch --prune`, refresh the repo
  header, bump `dataVersion`. Panels take `refreshKey` and reload in place, so no tab switching is
  needed to see new remote state.
- Tab counts are fetched eagerly on repo selection (and again when the token arrives), so badges
  are correct before the panel is ever opened.
