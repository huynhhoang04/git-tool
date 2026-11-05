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

function StatePill({ pull }) {
  if (pull.merged) return <span className="pill ok">merged</span>
  if (pull.state === 'closed') return <span className="pill danger">closed</span>
  if (pull.draft) return <span className="pill warn">draft</span>
  return <span className="pill">open</span>
}

export default function PullsPanel({ repo, login, mineOnly = false, canMerge = false, refreshKey = 0, onCount }) {
  const [pulls, setPulls] = useState([])
  const [stateFilter, setStateFilter] = useState('open')
  const [detail, setDetail] = useState(null)
  const [comment, setComment] = useState('')
  const [mergeMethod, setMergeMethod] = useState('merge')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    if (!repo) return
    setLoading(true)
    try {
      // Always fetch every state, then filter here: the tab badge stays stable and a
      // merged PR is still visible while the "open" chip is selected.
      const params = new URLSearchParams({ repo, state: 'all' })
      const data = await api(`/api/prs?${params}`)
      const list = (data.pulls || []).filter(pull => !mineOnly || pull.user === login)
      setPulls(list)
      onCount?.(list.filter(pull => pull.state === 'open').length)
      setDetail(null)
      setError('')
    } catch (e) {
      setError(e.message || String(e))
    } finally {
      setLoading(false)
    }
  }, [repo, mineOnly, login, onCount, refreshKey])

  useEffect(() => { load() }, [load])

  const openDetail = async (number) => {
    setBusy('detail')
    try {
      setDetail(await api(`/api/prs/${number}?repo=${encodeURIComponent(repo)}`))
    } catch (e) {
      setError(e.message || String(e))
    } finally {
      setBusy('')
    }
  }

  const sendComment = async () => {
    if (!detail || !comment.trim()) return
    setBusy('comment')
    try {
      await api(`/api/prs/${detail.pull.number}/comments`, {
        method: 'POST',
        body: { repo, body: comment.trim() },
      })
      setComment('')
      await openDetail(detail.pull.number)
    } catch (e) {
      setError(e.message || String(e))
    } finally {
      setBusy('')
    }
  }

  const merge = async () => {
    if (!detail) return
    setBusy('merge')
    try {
      await api(`/api/prs/${detail.pull.number}/merge`, {
        method: 'POST',
        body: { repo, method: mergeMethod },
      })
      await load()
      await openDetail(detail.pull.number)
    } catch (e) {
      setError(e.message || String(e))
    } finally {
      setBusy('')
    }
  }

  const title = mineOnly ? 'My pull requests' : 'Pull requests'
  const canMergeThis = canMerge
    && detail
    && detail.pull.state === 'open'
    && !detail.pull.merged

  const visible = useMemo(() => pulls.filter(pull => {
    if (stateFilter === 'all') return true
    if (stateFilter === 'open') return pull.state === 'open'
    return pull.state === 'closed'
  }), [pulls, stateFilter])

  return (
    <section className="section">
      {error && <div className="banner error"><span>{error}</span></div>}

      <div className="section-head">
        <h3 className="section-title">{title}</h3>
        <div className="state-row">
          {['open', 'closed', 'all'].map(state => (
            <button
              key={state}
              className={stateFilter === state ? 'chip active' : 'chip'}
              onClick={() => setStateFilter(state)}
            >
              {state}
            </button>
          ))}
        </div>
      </div>

      {loading && <p className="muted small">Loading pull requests…</p>}
      {!loading && visible.length === 0 && (
        <p className="muted small">
          {mineOnly ? 'You have no pull requests in this state.' : 'No pull requests in this state.'}
        </p>
      )}

      <div className="list">
        {visible.map(pull => (
          <div className={`pr-item ${detail?.pull.number === pull.number ? 'is-active' : ''}`} key={pull.number}>
            <button className="pr-main" onClick={() => openDetail(pull.number)}>
              <span className="pr-title">
                <span className="mono pr-number">#{pull.number}</span>
                <span className="pr-name">{pull.title}</span>
                <StatePill pull={pull} />
              </span>
              <span className="pr-meta">
                <span>{pull.user} · {ago(pull.updated_at)}</span>
                <span className="mono">{pull.head} → {pull.base}</span>
                <span>{pull.comments} comments</span>
              </span>
            </button>
            {pull.html_url && (
              <a
                className="pr-link"
                href={pull.html_url}
                target="_blank"
                rel="noopener noreferrer"
                title="Open on GitHub"
              >
                Open ↗
              </a>
            )}
          </div>
        ))}
      </div>

      {detail && (
        <div className="detail">
          <div className="detail-head">
            <h3>#{detail.pull.number} {detail.pull.title}</h3>
            <div className="detail-actions">
              {canMergeThis && (
                <>
                  <select
                    className="input head-select"
                    value={mergeMethod}
                    onChange={event => setMergeMethod(event.target.value)}
                    title="Merge method"
                  >
                    <option value="merge">merge commit</option>
                    <option value="squash">squash</option>
                    <option value="rebase">rebase</option>
                  </select>
                  <button className="btn tiny primary" onClick={merge} disabled={busy !== ''}>
                    {busy === 'merge' ? 'Merging…' : 'Merge PR'}
                  </button>
                </>
              )}
              {detail.pull.html_url && (
                <a className="btn tiny" href={detail.pull.html_url} target="_blank" rel="noopener noreferrer">
                  Open on GitHub ↗
                </a>
              )}
            </div>
          </div>

          <p className="muted small mono">
            {detail.pull.head} → {detail.pull.base} · {detail.pull.user} · {detail.pull.state}
          </p>
          <pre className="body-text">{detail.pull.body || '(no description)'}</pre>

          <h4 className="subhead">Comments</h4>
          {detail.comments.length === 0 && <p className="muted small">No comments yet.</p>}
          {detail.comments.map(item => (
            <div className="comment" key={item.id}>
              <p className="muted small"><strong>{item.user}</strong> · {ago(item.created_at)}</p>
              <pre className="body-text">{item.body}</pre>
            </div>
          ))}
          <div className="form-row">
            <textarea
              className="input area"
              value={comment}
              onChange={event => setComment(event.target.value)}
              rows={2}
              placeholder="Write a comment…"
            />
            <button className="btn primary" onClick={sendComment} disabled={busy !== '' || !comment.trim()}>
              Comment
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
