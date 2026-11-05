import { useEffect, useState } from 'react'
import BranchesPanel from './BranchesPanel'
import RepoList from './RepoList'
import ScanSettings from './ScanSettings'
import IssuesPanel from './IssuesPanel'
import PullsPanel from './PullsPanel'
import WorkflowPanel from './WorkflowPanel'
import { api, EXPECTED_API_VERSION } from './api'

const ROLE_LABEL = {
  owner: 'Owner',
  collaborator: 'Collaborator',
  organization_member: 'Org member',
  local: 'Local',
}

function Pill({ tone = 'neutral', children }) {
  return <span className={`pill ${tone}`}>{children}</span>
}

function Banner({ tone, children, onClose }) {
  if (!children) return null
  return (
    <div className={`banner ${tone}`}>
      <span>{children}</span>
      {onClose && <button type="button" onClick={onClose} className="banner-close">×</button>}
    </div>
  )
}

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

export default function App() {
  const [status, setStatus] = useState(null)
  const [repos, setRepos] = useState([])
  const [reposMeta, setReposMeta] = useState(null)
  const [reposLoading, setReposLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [repoKey, setRepoKey] = useState('')
  const [repo, setRepo] = useState(null)
  const [branchCount, setBranchCount] = useState(0)
  const [tab, setTab] = useState('branches')
  const [myPullCount, setMyPullCount] = useState(0)
  const [allPullCount, setAllPullCount] = useState(0)
  const [issueCount, setIssueCount] = useState(0)
  const [dataVersion, setDataVersion] = useState(0)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const [settings, setSettings] = useState(null)
  const [tokenDraft, setTokenDraft] = useState('')

  const fullName = repo?.owner && repo?.repo ? `${repo.owner}/${repo.repo}` : ''
  const localPath = repo?.local_path || repo?.path || ''
  const isLocal = Boolean(repo?.local && localPath)
  const backendStale = Boolean(settings && settings.api_version !== EXPECTED_API_VERSION)

  const run = async (label, task, success) => {
    setBusy(label)
    setError('')
    setNotice('')
    try {
      const result = await task()
      if (success) setNotice(success)
      return result
    } catch (e) {
      setError(e.message || String(e))
      return null
    } finally {
      setBusy(null)
    }
  }

  const loadStatus = async () => {
    try {
      setStatus(await api('/api/status'))
    } catch (e) {
      setError(e.message || String(e))
    }
  }

  const loadSettings = async () => {
    try {
      setSettings(await api('/api/settings'))
    } catch (e) {
      setError(e.message || String(e))
    }
  }

  const saveToken = async () => {
    const value = tokenDraft.trim()
    if (!value) return
    const data = await run('token', () => api('/api/settings/github-token', {
      method: 'PUT',
      body: { value },
    }), 'GitHub token saved.')
    if (data) {
      setSettings(data)
      setTokenDraft('')
      await loadStatus()
      try {
        applyRepos(await api('/api/repos/refresh?scope=github', { method: 'POST' }))
        await loadSettings()
      } catch (e) {
        setError(e.message || String(e))
      }
    }
  }

  const removeToken = async () => {
    const data = await run('token', () => api('/api/settings/github-token', { method: 'DELETE' }), 'GitHub token removed.')
    if (data) {
      setSettings(data)
      await loadStatus()
      try {
        applyRepos(await api('/api/repos/refresh?scope=github', { method: 'POST' }))
        await loadSettings()
      } catch (e) {
        setError(e.message || String(e))
      }
    }
  }

  const applyRepos = (data) => {
    setRepos(data.repos || [])
    setReposMeta(data.meta || null)
  }

  const loadRepos = async () => {
    try {
      const data = await api('/api/repos')
      applyRepos(data)
      return data
    } catch (e) {
      setError(e.message || String(e))
      return null
    } finally {
      setReposLoading(false)
    }
  }

  const refreshRepos = async (scope = 'all') => {
    setRefreshing(true)
    setError('')
    setNotice('')
    try {
      const data = await api(`/api/repos/refresh?scope=${scope}`, { method: 'POST' })
      applyRepos(data)
      if (data.github_error) setError(`GitHub: ${data.github_error}`)
      return data
    } catch (e) {
      setError(e.message || String(e))
      return null
    } finally {
      setRefreshing(false)
    }
  }

  const refreshGithub = async () => {
    const result = await run('github', async () => {
      const data = await api('/api/repos/refresh?scope=github', { method: 'POST' })
      applyRepos(data)
      await loadSettings()
      await loadStatus()
      if (data.github_error) throw new Error(data.github_error)
      return data
    }, 'GitHub repositories refreshed.')
    return result
  }

  const scanLocal = async () => {
    const result = await run('scan', async () => {
      const data = await api('/api/repos/refresh?scope=local', { method: 'POST' })
      applyRepos(data)
      await loadSettings()
      return data
    }, 'Local repositories scanned.')
    return result
  }

  const saveRoots = async (roots, depth) => {
    const payload = await run('scan-settings', () => api('/api/settings/scan', {
      method: 'PUT',
      body: { roots, depth },
    }), 'Scan roots saved.')
    if (!payload) return
    setSettings(payload)
    await scanLocal()
  }

  const pinRepo = async (item) => {
    try {
      applyRepos(await api('/api/repos/pin', { method: 'POST', body: { key: item.key, pinned: !item.pinned } }))
    } catch (e) {
      setError(e.message || String(e))
    }
  }

  const selectRepo = async (item) => {
    setRepoKey(item.key)
    setTab(item.local ? 'branches' : 'mine')
    let merged = { ...item }
    if (item.local && item.local_path) {
      try {
        merged = { ...item, ...(await api(`/api/repo?path=${encodeURIComponent(item.local_path)}`)) }
      } catch (e) {
        setError(e.message || String(e))
      }
    }
    setRepo(merged)
    refreshCounts(merged)
    api('/api/repos/open', { method: 'POST', body: { key: item.key } }).catch(() => {})
  }

  useEffect(() => { loadStatus(); loadSettings() }, [])
  useEffect(() => {
    (async () => {
      const data = await loadRepos()
      if (!data) return
      const list = data.repos || []
      const meta = data.meta || {}
      const neverScanned = !meta.scan?.scanned_at && !meta.github?.fetched_at
      if (list.length === 0 && neverScanned) {
        const refreshed = await refreshRepos('all')
        if (refreshed && (refreshed.repos || []).length > 0) selectRepo(refreshed.repos[0])
      } else if (list.length > 0) {
        selectRepo(list[0])
      }
    })()
  }, [])

  const refreshCounts = async (target) => {
    if (!target?.owner || !target?.repo || !status?.token) {
      setMyPullCount(0)
      setAllPullCount(0)
      setIssueCount(0)
      return
    }
    const name = `${target.owner}/${target.repo}`
    try {
      const [prs, issueData] = await Promise.all([
        api(`/api/prs?repo=${encodeURIComponent(name)}&state=all`),
        api(`/api/issues?repo=${encodeURIComponent(name)}&state=all`),
      ])
      const open = (prs.pulls || []).filter(pull => pull.state === 'open')
      setAllPullCount(open.length)
      setMyPullCount(open.filter(pull => pull.user === status?.login).length)
      setIssueCount((issueData.issues || []).filter(issue => issue.state === 'open').length)
    } catch {
      /* counts are best-effort */
    }
  }

  useEffect(() => {
    if (repo) refreshCounts(repo)
  }, [status?.token, repoKey])

  const refreshRepo = async () => {
    if (repo && localPath) {
      try {
        const data = await api(`/api/repo?path=${encodeURIComponent(localPath)}`)
        setRepo(current => ({ ...(current || {}), ...data }))
        setRepos(list => list.map(item => (item.key === repoKey ? { ...item, ...data } : item)))
      } catch (e) {
        setError(e.message || String(e))
      }
    }
    setDataVersion(version => version + 1)
    refreshCounts(repo)
  }

  const syncRepo = async () => {
    if (!repo) return
    if (isLocal) {
      const ok = await run('sync', () => api('/api/fetch', { method: 'POST', body: { path: localPath } }), 'Fetched origin.')
      if (!ok) return
    }
    await refreshRepo()
  }

  const hasNotice = Boolean(backendStale || !status?.token || error || notice)

  return (
    <div className="app">
      <aside className="sidebar">
        <RepoList
          repos={repos}
          selectedKey={repoKey}
          loading={reposLoading}
          refreshing={refreshing}
          onSelect={selectRepo}
          onPin={pinRepo}
          onRefresh={() => refreshRepos('all')}
        />
        <SymbolLegend />
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="brand">
            <span className="logo">Git</span>
            <div className="brand-text">
              <h1>Git workspace</h1>
              <p>Branches, pull requests and issues</p>
            </div>
          </div>
          <div className="status">
            {status?.token ? (
              <>
                <span className="pill ok">@{status.login || 'token'}</span>
                <span className="muted small nowrap">API {status.rate_remaining}/{status.rate_limit}</span>
              </>
            ) : (
              <span className="pill danger">no GitHub token</span>
            )}
          </div>
        </header>

        {hasNotice && (
          <div className="notices">
            {backendStale && (
              <Banner tone="error">
                Tool backend is outdated (UI expects API v{EXPECTED_API_VERSION}). Click Restart in the dashboard header, then reopen the tool.
              </Banner>
            )}
            {!status?.token && (
              <Banner tone="error">
                GitHub token is missing. Open the Settings tab to add it.
              </Banner>
            )}
            <Banner tone="error" onClose={() => setError('')}>{error}</Banner>
            <Banner tone="ok" onClose={() => setNotice('')}>{notice}</Banner>
          </div>
        )}

        {repo && (
          <div className="repo-bar">
            <div className="repo-bar-main">
              <div className="repo-title-row">
                <h2>{repo.full_name || repo.name}</h2>
                {repo.role && <span className={`pill role-${repo.role}`}>{ROLE_LABEL[repo.role] || repo.role}</span>}
                {repo.private && <span className="pill">private</span>}
                {repo.fork && <span className="pill">fork</span>}
                {repo.archived && <span className="pill warn">archived</span>}
                {repo.language && <span className="pill">{repo.language}</span>}
              </div>
              <p className="repo-bar-meta">
                {isLocal ? (
                  <>
                    <span className="mono">{localPath}</span>
                    <span className="dot-sep">·</span>
                    <span>{repo.dirty ? `${repo.changed_files} changed` : 'clean'}</span>
                  </>
                ) : (
                  'not found on this machine (or outside allowed roots)'
                )}
                {repo.github && repo.updated_at && (
                  <>
                    <span className="dot-sep">·</span>
                    <span>updated {ago(repo.updated_at)}</span>
                  </>
                )}
              </p>
            </div>
            <div className="repo-actions">
              {isLocal && <span className="pill">{repo.branch}</span>}
              <button
                className="btn"
                onClick={syncRepo}
                disabled={busy !== null}
                title="git fetch, then reload branches, pull requests and issues"
              >
                {busy === 'sync' ? 'Syncing…' : 'Sync'}
              </button>
              {repo.html_url && (
                <a className="btn" href={repo.html_url} target="_blank" rel="noopener noreferrer">GitHub ↗</a>
              )}
            </div>
          </div>
        )}

        <nav className="tabs">
          <button className={tab === 'branches' ? 'tab active' : 'tab'} onClick={() => setTab('branches')} disabled={!isLocal}>
            Branches <span className="tab-count">{branchCount}</span>
          </button>
          <button className={tab === 'workflow' ? 'tab active' : 'tab'} onClick={() => setTab('workflow')} disabled={!isLocal}>
            Workflow
          </button>
          <button className={tab === 'mine' ? 'tab active' : 'tab'} onClick={() => setTab('mine')} disabled={!fullName}>
            My pull requests <span className="tab-count">{myPullCount}</span>
          </button>
          {repo?.role === 'owner' && (
            <button className={tab === 'pulls' ? 'tab active' : 'tab'} onClick={() => setTab('pulls')} disabled={!fullName}>
              Pull requests <span className="tab-count">{allPullCount}</span>
            </button>
          )}
          <button className={tab === 'issues' ? 'tab active' : 'tab'} onClick={() => setTab('issues')} disabled={!fullName}>
            Issues &amp; discussions <span className="tab-count">{issueCount}</span>
          </button>
          <button className={tab === 'settings' ? 'tab active' : 'tab'} onClick={() => setTab('settings')}>
            Settings
          </button>
        </nav>

        <main className="content">
          {!repo && tab !== 'settings' ? (
            <div className="empty">
              <p>Pick a repository to start.</p>
              <button className="btn" onClick={() => setTab('settings')}>Open settings</button>
            </div>
          ) : (
            <>
              {repo && !fullName && (
                <Banner tone="warn">
                  No GitHub remote configured for this folder; pull requests and issues are unavailable.
                </Banner>
              )}
              {repo && fullName && !isLocal && (
                <Banner tone="warn">
                  This repo is not cloned inside the scan roots. Branches need a local checkout.
                </Banner>
              )}

              {tab === 'settings' && (
                <div className="settings-stack">
                  <section className="section">
                    <h3 className="section-title">GitHub token</h3>
                    <p className="muted small">
                      Stored by key-router in <code>secrets.json</code> and read by this tool server-side. The token never reaches this page.
                    </p>
                    <div className="form-row">
                      <input
                        type="password"
                        className="input"
                        value={tokenDraft}
                        onChange={e => setTokenDraft(e.target.value)}
                        placeholder={settings?.github_token?.has_token ? 'Replace token…' : 'ghp_…'}
                        autoComplete="off"
                      />
                      <button className="btn primary" onClick={saveToken} disabled={busy !== null || !tokenDraft.trim()}>Save</button>
                      <button className="btn" onClick={removeToken} disabled={busy !== null || !settings?.github_token?.has_token}>Remove</button>
                    </div>
                    <p className="muted small">
                      {settings?.github_token?.has_token ? `Stored: ${settings.github_token.preview}` : 'No token configured.'}
                      {settings && !settings.managed_by_key_router ? ' Standalone mode: set GITHUB_TOKEN in the environment.' : ''}
                    </p>
                    <p className="muted small">
                      The token needs read access to repositories; creating pull requests or issues also needs read/write on Issues and Pull requests.
                    </p>
                  </section>
                  <ScanSettings
                    settings={settings}
                    busy={busy}
                    onRefreshGithub={refreshGithub}
                    onScanLocal={scanLocal}
                    onSaveRoots={saveRoots}
                  />
                </div>
              )}

              {tab === 'branches' && (
                <BranchesPanel
                  localPath={localPath}
                  refreshKey={dataVersion}
                  onChanged={refreshRepo}
                  onCount={setBranchCount}
                />
              )}

              {tab === 'workflow' && (
                <WorkflowPanel localPath={localPath} repo={repo} refreshKey={dataVersion} onChanged={refreshRepo} />
              )}

              {tab === 'mine' && fullName && (
                <PullsPanel
                  repo={fullName}
                  login={status?.login}
                  mineOnly
                  refreshKey={dataVersion}
                  onCount={setMyPullCount}
                />
              )}

              {tab === 'pulls' && fullName && repo?.role === 'owner' && (
                <PullsPanel
                  repo={fullName}
                  login={status?.login}
                  canMerge
                  refreshKey={dataVersion}
                  onCount={setAllPullCount}
                />
              )}

              {tab === 'issues' && fullName && (
                <IssuesPanel
                  repo={fullName}
                  refreshKey={dataVersion}
                  onCount={setIssueCount}
                />
              )}
            </>
          )}
        </main>
      </div>
    </div>
  )
}

function SymbolLegend() {
  return (
    <details className="legend" open>
      <summary>Symbols</summary>
      <dl>
        <div><dt><span className="legend-dot" /></dt><dd>current branch</dd></div>
        <div><dt className="legend-ahead">↑ n</dt><dd>commits only on this branch</dd></div>
        <div><dt className="legend-behind">↓ n</dt><dd>commits only on the base</dd></div>
        <div><dt><span className="legend-merge" /></dt><dd>merge commit</dd></div>
        <div><dt className="legend-files">A M D R</dt><dd>file change status</dd></div>
        <div><dt className="legend-star">★</dt><dd>pinned repository</dd></div>
      </dl>
    </details>
  )
}
