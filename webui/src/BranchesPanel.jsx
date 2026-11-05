import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api'

function ago(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const seconds = Math.max(1, Math.floor((Date.now() - date.getTime()) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

const STATUS_LABEL = {
  A: 'added',
  M: 'modified',
  D: 'deleted',
  R: 'renamed',
  C: 'copied',
  T: 'type changed',
  U: 'conflict',
}

const LANE_W = 18
const ROW_H = 34
const MAX_LANES = 8

// Two colours with meaning instead of a palette per lane:
// the line of the ref being viewed vs. every merged-in line.
const MAIN_COLOR = '#38bdf8'
const SIDE_COLOR = '#7b8494'

const laneColor = lane => (lane === 0 ? MAIN_COLOR : SIDE_COLOR)
const laneX = lane => Math.min(lane, MAX_LANES - 1) * LANE_W + LANE_W / 2

function buildGraph(commits) {
  const lanes = []
  const rows = []

  for (const commit of commits) {
    const before = lanes.slice()
    let lane = before.indexOf(commit.sha)
    const started = lane !== -1
    if (!started) {
      const free = before.indexOf(null)
      lane = free === -1 ? before.length : free
      while (before.length <= lane) before.push(null)
    }

    const merges = []
    const through = []
    for (let index = 0; index < before.length; index += 1) {
      const sha = before[index]
      if (index === lane || sha === null) continue
      if (commit.parents.includes(sha)) {
        merges.push(index)
        before[index] = null
      } else {
        through.push(index)
      }
    }

    const next = before.slice()
    while (next.length <= lane) next.push(null)
    next[lane] = commit.parents[0] || null

    const forks = []
    commit.parents.slice(1).forEach(parent => {
      if (next.includes(parent)) return
      let slot = next.indexOf(null)
      if (slot === -1) {
        slot = next.length
        next.push(null)
      }
      next[slot] = parent
      forks.push(slot)
    })

    lanes.length = 0
    next.forEach(value => lanes.push(value))
    while (lanes.length > 1 && lanes[lanes.length - 1] === null) lanes.pop()

    const width = Math.min(MAX_LANES, Math.max(lane, ...merges, ...through, ...forks, 0) + 1)
    rows.push({ lane, merges, through, forks, started, width })
  }

  return rows
}

function FileList({ files, truncated, total }) {
  if (files.length === 0) {
    return <p className="compare-empty">No file changes — the difference is commits only (merge-only or identical trees).</p>
  }
  return (
    <div className="file-list">
      {files.map(file => (
        <div className="file-row" key={file.path} title={STATUS_LABEL[file.status] || file.status}>
          <span className={`file-status s-${file.status}`}>{file.status}</span>
          <span className="mono">{file.path}</span>
        </div>
      ))}
      {truncated && <p className="compare-empty">Showing the first {files.length} of {total} files.</p>}
    </div>
  )
}

function CommitList({ commits, empty }) {
  if (commits.length === 0) return <p className="compare-empty">{empty}</p>
  return (
    <div className="commit-list">
      {commits.map(commit => (
        <div className="commit-row" key={commit.sha} title={commit.subject}>
          <span className="commit-subject">{commit.subject}</span>
          <span className="commit-meta">
            <span className="sha">{commit.sha}</span>
            <span>{commit.author}</span>
            <span>{ago(commit.date)}</span>
          </span>
        </div>
      ))}
    </div>
  )
}

function ComparePanel({ compare, onClose }) {
  return (
    <section className="detail-block compare-panel">
      <header className="detail-head">
        <h3 className="detail-title">
          <span className="ref">{compare.head}</span>
          <span className="vs">vs</span>
          <span className="ref">{compare.base}</span>
        </h3>
        <div className="detail-actions">
          <button className="btn tiny" onClick={onClose}>Close</button>
        </div>
      </header>

      <div className="stat-row">
        <span className={`stat ${compare.ahead ? 'ahead' : 'neutral'}`}>{`↑ ${compare.ahead} ahead`}</span>
        <span className={`stat ${compare.behind ? 'behind' : 'neutral'}`}>{`↓ ${compare.behind} behind`}</span>
        <span className="merge-base">merge-base {(compare.merge_base || '').slice(0, 10) || '—'}</span>
      </div>

      <div className="compare-grid">
        <div className="compare-col">
          <h4>
            Only in
            <span className="ref">{compare.head}</span>
          </h4>
          <CommitList
            commits={compare.head_only}
            empty="No commits the other side lacks."
          />
          <h4>
            Files changed
            <span className="ref">{compare.head_files_total}</span>
          </h4>
          <FileList files={compare.head_files} truncated={compare.head_files_truncated} total={compare.head_files_total} />
        </div>

        <div className="compare-col">
          <h4>
            Only in
            <span className="ref">{compare.base}</span>
          </h4>
          <CommitList
            commits={compare.base_only}
            empty="No commits this side lacks."
          />
          <h4>
            Files changed
            <span className="ref">{compare.base_files_total}</span>
          </h4>
          <FileList files={compare.base_files} truncated={compare.base_files_truncated} total={compare.base_files_total} />
        </div>
      </div>
    </section>
  )
}

function CommitGraph({ history, limit, onLimit, loading, onClose }) {
  const commits = history.commits || []
  const rows = useMemo(() => buildGraph(commits), [commits])
  const width = useMemo(() => rows.reduce((max, row) => Math.max(max, row.width), 1) * LANE_W, [rows])

  return (
    <section className="detail-block graph-panel">
      <header className="detail-head">
        <h3 className="detail-title">
          <span className="ref">{history.ref}</span>
          <span className="vs">history</span>
          <span className="count">{commits.length}</span>
        </h3>
        <div className="detail-actions">
          <select className="input head-select" value={limit} onChange={event => onLimit(Number(event.target.value))}>
            {[30, 60, 120, 200].map(value => <option key={value} value={value}>{value} commits</option>)}
          </select>
          <button className="btn tiny" onClick={onClose}>Close</button>
        </div>
      </header>

      {loading && <p className="muted small">Loading history…</p>}
      {!loading && commits.length === 0 && <p className="muted small">No commits.</p>}

      <div className="graph-legend">
        <span><i className="lg-dot" />commit</span>
        <span><i className="lg-merge" />merge commit</span>
        <span><i className="lg-lane" />{history.ref}</span>
        <span><i className="lg-lane side" />merged-in line</span>
        <span><i className="lg-curve" />split / join</span>
      </div>

      <div className="graph">
        {rows.map((row, index) => {
          const commit = commits[index]
          return (
            <div className="graph-row" key={commit.sha}>
              <svg className="graph-svg" width={width} height={ROW_H}>
                {row.through.map(lane => (
                  <line
                    key={`t${lane}`}
                    x1={laneX(lane)} y1={0} x2={laneX(lane)} y2={ROW_H}
                    stroke={laneColor(lane)} strokeWidth="1.5"
                  />
                ))}
                {row.merges.map(lane => (
                  <path
                    key={`m${lane}`}
                    d={`M ${laneX(lane)} 0 C ${laneX(lane)} ${ROW_H * 0.55} ${laneX(row.lane)} ${ROW_H * 0.45} ${laneX(row.lane)} ${ROW_H / 2}`}
                    stroke={laneColor(lane)} strokeWidth="1.5" fill="none"
                  />
                ))}
                {row.started && (
                  <line
                    x1={laneX(row.lane)} y1={0} x2={laneX(row.lane)} y2={ROW_H / 2}
                    stroke={laneColor(row.lane)} strokeWidth="1.5"
                  />
                )}
                {row.forks.map(lane => (
                  <path
                    key={`f${lane}`}
                    d={`M ${laneX(row.lane)} ${ROW_H / 2} C ${laneX(row.lane)} ${ROW_H * 0.75} ${laneX(lane)} ${ROW_H * 0.25} ${laneX(lane)} ${ROW_H}`}
                    stroke={laneColor(lane)} strokeWidth="1.5" fill="none"
                  />
                ))}
                <circle
                  cx={laneX(row.lane)}
                  cy={ROW_H / 2}
                  r={commit.parents.length > 1 ? 4.5 : 3.4}
                  fill={laneColor(row.lane)}
                  stroke="var(--surface-950)"
                  strokeWidth={commit.parents.length > 1 ? 2 : 0}
                />
              </svg>

              <div className="graph-info">
                <span className="graph-subject" title={commit.subject}>{commit.subject}</span>
                <span className="graph-meta" title={commit.refs.join(' · ')}>
                  <span className="sha">{commit.short}</span>
                  <span>{commit.author}</span>
                  <span>{ago(commit.date)}</span>
                  {commit.parents.length > 1 && <span className="pill">merge</span>}
                  {commit.refs.slice(0, 2).map(ref => <span className="pill ok" key={ref}>{ref}</span>)}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

export default function BranchesPanel({ localPath, refreshKey = 0, onChanged, onCount }) {
  const [local, setLocal] = useState([])
  const [remote, setRemote] = useState([])
  const [head, setHead] = useState('')
  const [defaultBase, setDefaultBase] = useState('')
  const [divergence, setDivergence] = useState({})
  const [defaultDivergence, setDefaultDivergence] = useState({})
  const [remoteBase, setRemoteBase] = useState('')
  const [compare, setCompare] = useState(null)
  const [history, setHistory] = useState(null)
  const [historyLimit, setHistoryLimit] = useState(60)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async (compareHead) => {
    if (!localPath) return
    setBusy('load')
    setError('')
    setRemoteBase('')
    try {
      const params = new URLSearchParams({ path: localPath })
      if (compareHead) params.set('head', compareHead)
      const data = await api(`/api/branches?${params}`)
      setLocal(data.local || [])
      setRemote(data.remote || [])
      setHead(data.head || '')
      setDefaultBase(data.default_base || '')
      setDivergence(data.divergence || {})
      setDefaultDivergence(data.default_divergence || {})
      onCount((data.local || []).length)
    } catch (e) {
      setError(e.message || String(e))
    } finally {
      setBusy('')
      setLoading(false)
    }
  }, [localPath, onCount, refreshKey])

  useEffect(() => {
    setCompare(null)
    setHistory(null)
    load()
  }, [load])

  const openCompare = async (base, target) => {
    if (!localPath || !base || !target) return
    setBusy('compare')
    setError('')
    try {
      const params = new URLSearchParams({ path: localPath, base, head: target })
      setCompare(await api(`/api/branches/compare?${params}`))
    } catch (e) {
      setError(e.message || String(e))
    } finally {
      setBusy('')
    }
  }

  const openHistory = async (ref, limit = historyLimit) => {
    if (!localPath) return
    setHistoryLimit(limit)
    setHistory({ ref, commits: [] })
    setHistoryLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ path: localPath, ref, limit: String(limit) })
      setHistory(await api(`/api/branches/history?${params}`))
    } catch (e) {
      setError(e.message || String(e))
      setHistory(null)
    } finally {
      setHistoryLoading(false)
    }
  }

  const switchBranch = async (name) => {
    setBusy(`switch:${name}`)
    setError('')
    try {
      await api('/api/branches/switch', { method: 'POST', body: { path: localPath, name } })
      await load(name)
      setCompare(null)
      onChanged()
    } catch (e) {
      setError(e.message || String(e))
    } finally {
      setBusy('')
    }
  }

  const trackedBy = useMemo(() => {
    const map = new Map()
    local.forEach(branch => {
      if (branch.upstream) map.set(branch.upstream, branch.name)
    })
    return map
  }, [local])

  const baseRef = remoteBase || defaultBase || head
  const baseCounts = baseRef && baseRef === defaultBase ? defaultDivergence : divergence
  const baseOptions = []
  if (defaultBase) baseOptions.push({ value: defaultBase, label: `${defaultBase} · default` })
  if (head && head !== defaultBase) baseOptions.push({ value: head, label: `${head} · local` })

  const compareRemote = (name) => {
    if (!name || busy !== '' || !baseRef) return
    openCompare(baseRef, name)
  }

  if (loading) {
    return <p className="muted small">Loading branches…</p>
  }

  const hasDetail = Boolean(compare || history)

  return (
    <div className="branches">
      {error && <div className="banner error"><span>{error}</span></div>}

      {!hasDetail && (
        <p className="branch-hint">
          Click a remote branch to see its full diff against <span className="mono">{baseRef || 'the selected base'}</span>,
          or press <strong>History</strong> to see its commits and merges.
        </p>
      )}

      <div className={`branch-layout ${hasDetail ? 'with-detail' : ''}`}>
        <div className="branch-left">
          <section className="section">
            <div className="branch-col-head">
              <h3 className="section-title">Local <span className="count">{local.length}</span></h3>
            </div>

            <ul className="branch-list">
              {local.map(branch => (
                <li className={`branch-item ${branch.current ? 'is-current' : ''}`} key={branch.name}>
                  <div className="branch-main">
                    <div className="branch-title">
                      <span className="branch-name">{branch.name}</span>
                      {branch.current && <span className="pill ok">current</span>}
                      <span className="branch-upstream">
                        {branch.upstream ? `→ ${branch.upstream}` : 'no upstream'}
                      </span>
                      {branch.gone && <span className="pill warn">upstream gone</span>}
                    </div>
                    <div className="branch-meta">
                      <span className="sha">{branch.last_commit.sha}</span>
                      <span className="subject">{branch.last_commit.subject}</span>
                      <span className="when">{branch.last_commit.author} · {ago(branch.last_commit.date)}</span>
                    </div>
                  </div>

                  <div className="branch-side">
                    <div className="delta">
                      {branch.ahead > 0 && (
                        <span className="delta-ahead" title="commits not on the upstream">{`↑${branch.ahead}`}</span>
                      )}
                      {branch.behind > 0 && (
                        <span className="delta-behind" title="commits on the upstream not here">{`↓${branch.behind}`}</span>
                      )}
                    </div>
                    <div className="branch-actions">
                      {branch.upstream && (
                        <button
                          className="btn tiny"
                          onClick={() => openCompare(branch.upstream, branch.name)}
                          disabled={busy !== ''}
                          title={`Compare ${branch.name} with ${branch.upstream}`}
                        >
                          Compare
                        </button>
                      )}
                      <button className="btn tiny" onClick={() => openHistory(branch.name)} disabled={busy !== ''}>
                        History
                      </button>
                      {!branch.current && (
                        <button className="btn tiny" onClick={() => switchBranch(branch.name)} disabled={busy !== ''}>
                          {busy === `switch:${branch.name}` ? '…' : 'Switch'}
                        </button>
                      )}
                    </div>
                  </div>
                </li>
              ))}
              {local.length === 0 && <li className="muted small">No local branches.</li>}
            </ul>
          </section>

          <section className="section">
            <div className="branch-col-head">
              <h3 className="section-title">Remote <span className="count">{remote.length}</span></h3>
              {baseOptions.length > 1 && (
                <label className="check small">
                  compare with
                  <select
                    className="input head-select"
                    value={baseRef}
                    onChange={event => { setRemoteBase(event.target.value); setCompare(null) }}
                  >
                    {baseOptions.map(option => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </label>
              )}
            </div>

            <p className="branch-legend">
              <span className="mono">↑</span> commits only on that branch ·
              {' '}<span className="mono">↓</span> commits only on <span className="mono">{baseRef || '—'}</span>
            </p>

            <ul className="branch-list">
              {remote.map(branch => {
                const counts = baseCounts[branch.name]
                const tracked = trackedBy.get(branch.name)
                const isBase = branch.name === baseRef
                return (
                  <li className={`branch-item ${isBase ? 'is-current' : ''}`} key={branch.name}>
                    <div className="branch-main">
                      <div className="branch-title">
                        <span className="branch-name">{branch.name}</span>
                        {branch.name === defaultBase && <span className="pill">default</span>}
                        {isBase && <span className="pill ok">base</span>}
                        {tracked && <span className="branch-upstream">→ {tracked}</span>}
                      </div>
                      <div className="branch-meta">
                        <span className="sha">{branch.last_commit.sha}</span>
                        <span className="subject">{branch.last_commit.subject}</span>
                        <span className="when">{branch.last_commit.author} · {ago(branch.last_commit.date)}</span>
                      </div>
                    </div>

                    <div className="branch-side">
                      <div className="delta">
                        {counts && counts.ahead > 0 && (
                          <span className="delta-ahead" title={`${branch.name} has ${counts.ahead} commits not on ${baseRef}`}>
                            {`↑${counts.ahead}`}
                          </span>
                        )}
                        {counts && counts.behind > 0 && (
                          <span className="delta-behind" title={`${baseRef} has ${counts.behind} commits not on ${branch.name}`}>
                            {`↓${counts.behind}`}
                          </span>
                        )}
                        {counts && counts.ahead === 0 && counts.behind === 0 && <span className="pill ok">synced</span>}
                      </div>
                      <div className="branch-actions">
                        {!isBase && (
                          <button
                            className="btn tiny"
                            onClick={() => compareRemote(branch.name)}
                            disabled={busy !== '' || !baseRef}
                            title={`Compare ${baseRef} with ${branch.name}`}
                          >
                            Compare
                          </button>
                        )}
                        <button className="btn tiny" onClick={() => openHistory(branch.name)} disabled={busy !== ''}>
                          History
                        </button>
                      </div>
                    </div>
                  </li>
                )
              })}
              {remote.length === 0 && <li className="muted small">No remote branches. Fetch to update them.</li>}
            </ul>
          </section>
        </div>

        {hasDetail && (
          <aside className="detail-col">
            {compare && <ComparePanel compare={compare} onClose={() => setCompare(null)} />}
            {history && (
              <CommitGraph
                history={history}
                limit={historyLimit}
                loading={historyLoading}
                onLimit={value => openHistory(history.ref, value)}
                onClose={() => setHistory(null)}
              />
            )}
          </aside>
        )}
      </div>
    </div>
  )
}
