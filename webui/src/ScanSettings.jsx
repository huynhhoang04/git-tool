import { useEffect, useState } from 'react'
import { api } from './api'

function ago(value) {
  if (!value) return 'never'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const seconds = Math.max(1, Math.floor((Date.now() - date.getTime()) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

export default function ScanSettings({ settings, busy, onRefreshGithub, onScanLocal, onSaveRoots }) {
  const scan = settings?.scan || {}
  const github = settings?.github || {}
  const allowedRoots = scan.allowed_roots || []

  const [roots, setRoots] = useState(scan.roots || [])
  const [depth, setDepth] = useState(scan.depth || 3)
  const [newRoot, setNewRoot] = useState('')
  const [error, setError] = useState('')
  const [browsing, setBrowsing] = useState(false)

  useEffect(() => {
    setRoots(scan.roots || [])
    setDepth(scan.depth || 3)
  }, [settings])

  const addRoot = (value) => {
    const path = value.trim().replace(/\/+$/, '')
    if (!path) return
    setRoots(current => (current.includes(path) ? current : [...current, path]))
    setNewRoot('')
  }

  const browse = async () => {
    setBrowsing(true)
    setError('')
    try {
      const picked = await api('/api/browse-folder')
      if (picked.path) addRoot(picked.path)
    } catch (e) {
      setError(e.message || String(e))
    } finally {
      setBrowsing(false)
    }
  }

  return (
    <section className="section scan-panel">
      <h3 className="section-title">GitHub discovery</h3>
      <div className="scan-row">
        <div>
          <p className="small">
            {settings?.github_token?.has_token
              ? <>Connected as <strong>@{github.login || 'unknown'}</strong></>
              : 'No GitHub token — only local repositories are listed.'}
          </p>
          <p className="muted small">
            Repos fetched {ago(github.fetched_at)}
            {github.truncated ? ' · truncated (more than 500 per role)' : ''}
          </p>
        </div>
        <button className="btn" onClick={onRefreshGithub} disabled={busy || !settings?.github_token?.has_token}>
          {busy === 'github' ? 'Refreshing…' : 'Refresh GitHub'}
        </button>
      </div>

      <h3 className="section-title">Local scan</h3>
      <p className="muted small">
        {settings?.github_token?.has_token
          ? 'Only repositories this token can reach are listed; the scan below just marks which of them has a clone on this machine.'
          : 'Without a GitHub token the list falls back to clones found under the scan roots.'}
      </p>
      <p className="muted small">
        Roots default to key-router <code>allowed_roots</code>. A repo that is not under these roots shows as
        “not found on this machine”.
      </p>

      <div className="root-list">
        {roots.length === 0 && <p className="muted small">No roots configured (using key-router defaults).</p>}
        {roots.map(root => (
          <div className="root-row" key={root}>
            <span className="mono" title={root}>{root}</span>
            <button
              className="root-remove"
              title="Remove root"
              onClick={() => setRoots(current => current.filter(item => item !== root))}
            >
              ×
            </button>
          </div>
        ))}
      </div>

      <div className="form-row">
        <input
          className="input"
          value={newRoot}
          onChange={event => setNewRoot(event.target.value)}
          placeholder="/path/to/projects"
          onKeyDown={event => {
            if (event.key === 'Enter' && newRoot.trim()) addRoot(newRoot)
          }}
        />
        <button className="btn" onClick={browse} disabled={browsing}>{browsing ? 'Choosing…' : 'Browse…'}</button>
        <button className="btn" onClick={() => addRoot(newRoot)} disabled={!newRoot.trim()}>Add</button>
      </div>

      {allowedRoots.length > 0 && (
        <p className="muted small">
          key-router allows: <span className="mono">{allowedRoots.join(' · ')}</span>
        </p>
      )}

      <div className="form-row">
        <label className="check">
          Depth{' '}
          <select className="input depth-select" value={depth} onChange={event => setDepth(Number(event.target.value))}>
            {[1, 2, 3, 4].map(value => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <button className="btn" onClick={onScanLocal} disabled={busy}>
          {busy === 'scan' ? 'Scanning…' : 'Scan now'}
        </button>
        <button
          className="btn primary"
          onClick={() => onSaveRoots(roots, depth)}
          disabled={busy}
        >
          Save & scan
        </button>
      </div>

      <p className="muted small">
        Last scan {ago(scan.scanned_at)} · {scan.dirs_visited || 0} folders
        {scan.truncated ? ' · hit the scan cap, some folders were skipped' : ''}
      </p>
      {error && <p className="small" style={{ color: 'var(--danger)' }}>{error}</p>}
    </section>
  )
}
