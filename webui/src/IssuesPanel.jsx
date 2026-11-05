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

export default function IssuesPanel({ repo, refreshKey, onCount }) {
  const [mode, setMode] = useState('issues')
  const [issues, setIssues] = useState([])
  const [discussions, setDiscussions] = useState([])
  const [stateFilter, setStateFilter] = useState('open')
  const [detail, setDetail] = useState(null)
  const [comment, setComment] = useState('')
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [labels, setLabels] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [discussionError, setDiscussionError] = useState('')

  const loadIssues = useCallback(async () => {
    if (!repo) return
    setLoading(true)
    try {
      const params = new URLSearchParams({ repo, state: 'all' })
      const data = await api(`/api/issues?${params}`)
      const list = data.issues || []
      setIssues(list)
      onCount?.(list.filter(issue => issue.state === 'open').length)
      setError('')
    } catch (e) {
      setError(e.message || String(e))
    } finally {
      setLoading(false)
    }
  }, [repo, onCount])

  const loadDiscussions = useCallback(async () => {
    if (!repo) return
    setLoading(true)
    setDiscussionError('')
    try {
      const data = await api(`/api/discussions?repo=${encodeURIComponent(repo)}`)
      setDiscussions(data.discussions || [])
    } catch (e) {
      setDiscussions([])
      setDiscussionError(e.message || String(e))
    } finally {
      setLoading(false)
    }
  }, [repo])

  useEffect(() => {
    setDetail(null)
    loadIssues()
  }, [loadIssues, refreshKey])

  useEffect(() => {
    if (mode === 'discussions') loadDiscussions()
  }, [mode, loadDiscussions, refreshKey])

  const openIssue = async (number) => {
    setBusy('detail')
    try {
      setDetail(await api(`/api/issues/${number}?repo=${encodeURIComponent(repo)}`))
    } catch (e) {
      setError(e.message || String(e))
    } finally {
      setBusy('')
    }
  }

  const createIssue = async () => {
    if (!title.trim()) return
    setBusy('create')
    try {
      await api('/api/issues', {
        method: 'POST',
        body: {
          repo,
          title: title.trim(),
          body,
          labels: labels.split(',').map(item => item.trim()).filter(Boolean),
        },
      })
      setTitle('')
      setBody('')
      setLabels('')
      setShowForm(false)
      await loadIssues()
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
      await api(`/api/issues/${detail.issue.number}/comments`, {
        method: 'POST',
        body: { repo, body: comment.trim() },
      })
      setComment('')
      await openIssue(detail.issue.number)
    } catch (e) {
      setError(e.message || String(e))
    } finally {
      setBusy('')
    }
  }

  const toggleState = async () => {
    if (!detail) return
    const next = detail.issue.state === 'open' ? 'closed' : 'open'
    setBusy('state')
    try {
      await api(`/api/issues/${detail.issue.number}`, {
        method: 'PATCH',
        body: { repo, state: next },
      })
      await openIssue(detail.issue.number)
      await loadIssues()
    } catch (e) {
      setError(e.message || String(e))
    } finally {
      setBusy('')
    }
  }

  const visible = useMemo(() => issues.filter(issue => {
    if (stateFilter === 'all') return true
    return issue.state === stateFilter
  }), [issues, stateFilter])

  return (
    <section className="section">
      {error && <div className="banner error"><span>{error}</span></div>}

      <div className="section-head">
        <div className="seg-row">
          <button className={mode === 'issues' ? 'chip active' : 'chip'} onClick={() => setMode('issues')}>
            Issues
          </button>
          <button className={mode === 'discussions' ? 'chip active' : 'chip'} onClick={() => setMode('discussions')}>
            Discussions
          </button>
        </div>

        {mode === 'issues' ? (
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
            <button className="btn tiny" onClick={() => setShowForm(value => !value)}>
              {showForm ? 'Cancel' : 'New issue'}
            </button>
          </div>
        ) : null}
      </div>

      {mode === 'issues' && showForm && (
        <div className="form-col">
          <input className="input" value={title} onChange={event => setTitle(event.target.value)} placeholder="Issue title" />
          <textarea className="input area" rows={3} value={body} onChange={event => setBody(event.target.value)} placeholder="Description (optional)" />
          <div className="form-row">
            <input className="input" value={labels} onChange={event => setLabels(event.target.value)} placeholder="labels, comma separated" />
            <button className="btn primary" onClick={createIssue} disabled={busy !== '' || !title.trim()}>
              Create issue
            </button>
          </div>
        </div>
      )}

      {loading && <p className="muted small">Loading…</p>}

      {mode === 'issues' && (
        <>
          {!loading && visible.length === 0 && <p className="muted small">No issues in this state.</p>}
          <div className="list">
            {visible.map(issue => (
              <div className={`pr-item ${detail?.issue.number === issue.number ? 'is-active' : ''}`} key={issue.number}>
                <button className="pr-main" onClick={() => openIssue(issue.number)}>
                  <span className="pr-title">
                    <span className="mono pr-number">#{issue.number}</span>
                    <span className="pr-name">{issue.title}</span>
                    {issue.state === 'closed' && <span className="pill danger">closed</span>}
                    {issue.labels.map(label => <span className="pill" key={label}>{label}</span>)}
                  </span>
                  <span className="pr-meta">
                    <span>{issue.user} · {ago(issue.updated_at)}</span>
                    <span>{issue.comments} comments</span>
                    <span>{issue.state}</span>
                  </span>
                </button>
                {issue.html_url && (
                  <a className="pr-link" href={issue.html_url} target="_blank" rel="noopener noreferrer">Open ↗</a>
                )}
              </div>
            ))}
          </div>

          {detail && (
            <div className="detail">
              <div className="detail-head">
                <h3>#{detail.issue.number} {detail.issue.title}</h3>
                <div className="detail-actions">
                  <button className="btn tiny" onClick={toggleState} disabled={busy !== ''}>
                    {detail.issue.state === 'open' ? 'Close issue' : 'Reopen issue'}
                  </button>
                  <a className="btn tiny" href={detail.issue.html_url} target="_blank" rel="noopener noreferrer">
                    Open on GitHub ↗
                  </a>
                </div>
              </div>
              <p className="muted small">
                {detail.issue.user} · {ago(detail.issue.created_at)} · {detail.issue.state}
              </p>
              <pre className="body-text">{detail.issue.body || '(no description)'}</pre>

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
        </>
      )}

      {mode === 'discussions' && (
        <>
          {discussionError && (
            <div className="banner warn">
              <span>Discussions unavailable: {discussionError}</span>
            </div>
          )}
          {!loading && !discussionError && discussions.length === 0 && (
            <p className="muted small">No discussions in this repository.</p>
          )}
          <div className="list">
            {discussions.map(item => (
              <div className="pr-item" key={item.number}>
                <a className="pr-main" href={item.url} target="_blank" rel="noopener noreferrer">
                  <span className="pr-title">
                    <span className="mono pr-number">#{item.number}</span>
                    <span className="pr-name">{item.title}</span>
                    {item.category && <span className="pill">{item.category}</span>}
                  </span>
                  <span className="pr-meta">
                    <span>{item.author} · {ago(item.updated_at)}</span>
                    <span>{item.comments} comments</span>
                  </span>
                </a>
                <a className="pr-link" href={item.url} target="_blank" rel="noopener noreferrer">Open ↗</a>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  )
}
