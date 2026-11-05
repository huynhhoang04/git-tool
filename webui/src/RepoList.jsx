import { useMemo, useState } from 'react'

const ROLE_LABEL = {
  owner: 'Owner',
  collaborator: 'Collaborator',
  organization_member: 'Org member',
  local: 'Local',
}

function RolePill({ role }) {
  if (!role) return null
  if (role === 'owner') return <span className="role-dot role-owner" title="Owner" aria-label="Owner" />
  return <span className={`pill role-${role}`}>{ROLE_LABEL[role] || role}</span>
}

function Star({ on, onClick }) {
  return (
    <button
      type="button"
      className={`repo-star ${on ? 'on' : ''}`}
      title={on ? 'Unpin repository' : 'Pin repository'}
      aria-label={on ? 'Unpin repository' : 'Pin repository'}
      aria-pressed={on}
      onClick={event => {
        event.stopPropagation()
        onClick()
      }}
    >
      <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M12 3.2l2.7 5.5 6 .9-4.4 4.3 1 6-5.3-2.8-5.3 2.8 1-6L3.3 9.6l6-.9L12 3.2z"
          fill={on ? 'currentColor' : 'none'}
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  )
}

export default function RepoList({
  repos,
  selectedKey,
  loading,
  refreshing,
  onSelect,
  onPin,
  onRefresh,
}) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')

  const counts = useMemo(() => ({
    all: repos.length,
    local: repos.filter(repo => repo.local).length,
    remote: repos.filter(repo => !repo.local).length,
    pinned: repos.filter(repo => repo.pinned).length,
  }), [repos])

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return repos.filter(repo => {
      if (filter === 'local' && !repo.local) return false
      if (filter === 'remote' && repo.local) return false
      if (filter === 'pinned' && !repo.pinned) return false
      if (!needle) return true
      const haystack = [repo.name, repo.full_name, repo.owner, repo.local_path]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return haystack.includes(needle)
    })
  }, [repos, query, filter])

  return (
    <>
      <div className="sidebar-head">
        <h2>Repositories</h2>
        <button className="btn tiny" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? 'Scanning…' : 'Scan'}
        </button>
      </div>

      <div className="repo-search">
        <input
          className="input"
          value={query}
          onChange={event => setQuery(event.target.value)}
          placeholder="Search repo, owner or path…"
        />
      </div>

      <div className="chip-row">
        {[
          ['all', 'All', counts.all],
          ['local', 'Local', counts.local],
          ['remote', 'Remote', counts.remote],
          ['pinned', 'Pinned', counts.pinned],
        ].map(([id, label, count]) => (
          <button
            key={id}
            className={`chip ${filter === id ? 'active' : ''}`}
            onClick={() => setFilter(id)}
          >
            {label} <span className="count">{count}</span>
          </button>
        ))}
      </div>

      <div className="repo-list">
        {loading && <p className="muted small">Discovering repositories…</p>}
        {!loading && visible.length === 0 && (
          <p className="muted small repo-empty">
            {repos.length === 0
              ? 'No repositories found. Set scan roots in Settings, then Scan.'
              : 'No repositories match this filter.'}
          </p>
        )}
        {visible.map(repo => (
          <button
            key={repo.key}
            className={`repo-row ${selectedKey === repo.key ? 'active' : ''}`}
            onClick={() => onSelect(repo)}
            title={repo.local_path || repo.full_name}
          >
            <Star on={repo.pinned} onClick={() => onPin(repo)} />
            <span className="repo-main">
              <span className="repo-title">
                <span className="repo-name">{repo.name}</span>
                <RolePill role={repo.role} />
                {repo.private && <span className="pill">private</span>}
                {repo.fork && <span className="pill">fork</span>}
                {repo.archived && <span className="pill warn">archived</span>}
              </span>
              <span className="repo-sub">
                {repo.local ? (
                  <>
                    <span className="local-ok">{repo.branch || 'local'}</span>
                    <span className="dot-sep">·</span>
                    <span className="repo-path" title={repo.local_path}>{repo.local_path}</span>
                  </>
                ) : (
                  <>
                    <span className="mono repo-path" title={repo.full_name}>{repo.full_name || repo.name}</span>
                    <span className="dot-sep">·</span>
                    <span className="local-missing" title="not found on this machine (or outside allowed roots)">
                      not local
                    </span>
                  </>
                )}
              </span>
            </span>
          </button>
        ))}
      </div>

    </>
  )
}
