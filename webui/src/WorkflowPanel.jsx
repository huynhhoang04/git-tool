import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api'

function Steps({ steps }) {
  if (!steps.length) return null
  return (
    <ol className="steps">
      {steps.map((step, index) => (
        <li key={`${step.name}-${index}`} className={step.ok ? 'ok' : 'fail'}>
          <span className="step-mark" aria-hidden="true">{step.ok ? '✓' : '✗'}</span>
          <div className="step-body">
            <div className="step-name">{step.name}</div>
            {step.error && <pre className="step-output">{step.error}</pre>}
            {!step.error && step.detail?.output && <pre className="step-output">{step.detail.output}</pre>}
            {!step.error && step.detail?.files?.length > 0 && (
              <div className="step-files">
                {step.detail.files.map(file => <span className="mono" key={file}>{file}</span>)}
              </div>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}

function Command({ parts }) {
  return (
    <p className="cmd-preview">
      {parts.map((part, index) => (
        <span key={part}>
          {index > 0 && <span className="cmd-arrow">→</span>}
          <span className="mono">{part}</span>
        </span>
      ))}
    </p>
  )
}

export default function WorkflowPanel({ localPath, repo, refreshKey = 0, onChanged }) {
  const [local, setLocal] = useState([])
  const [current, setCurrent] = useState('')
  const [defaultBase, setDefaultBase] = useState('')
  const [base, setBase] = useState('')
  const [branch, setBranch] = useState('')
  const [syncBase, setSyncBase] = useState('')
  const [syncBranch, setSyncBranch] = useState('')
  const [message, setMessage] = useState('')
  const [prTitle, setPrTitle] = useState('')
  const [prBody, setPrBody] = useState('')
  const [prDraft, setPrDraft] = useState(false)
  const [createdPr, setCreatedPr] = useState(null)
  const [busy, setBusy] = useState('')
  const [logs, setLogs] = useState({})
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    if (!localPath) return
    try {
      const data = await api(`/api/branches?path=${encodeURIComponent(localPath)}`)
      const branches = data.local || []
      const remoteDefault = data.default_base || ''
      const tracked = branches.find(branch => branch.upstream === remoteDefault)
      const localDefault = tracked?.name
        || repo?.default_branch
        || (remoteDefault.includes('/') ? remoteDefault.slice(remoteDefault.indexOf('/') + 1) : remoteDefault)
        || data.head
        || ''
      setLocal(branches)
      setCurrent(data.head || '')
      setDefaultBase(localDefault)
      const fallbackBranch = data.head && data.head !== localDefault
        ? data.head
        : (branches.find(item => item.name !== localDefault)?.name || data.head || '')
      setBase(prev => prev || localDefault)
      setSyncBase(prev => prev || localDefault)
      setSyncBranch(prev => prev || fallbackBranch)
      setPrTitle(prev => prev || data.head || '')
    } catch (e) {
      setError(e.message || String(e))
    }
  }, [localPath, repo, refreshKey])

  useEffect(() => { load() }, [load])

  const runAction = async (label, task, success) => {
    setBusy(label)
    setError('')
    setNotice('')
    setLogs(previous => ({ ...previous, ...(label === 'commit' || label === 'push' ? { commit: [], push: [] } : {}), [label]: [] }))
    try {
      const result = await task()
      setLogs(previous => ({ ...previous, [label]: result.steps || [] }))
      if (result.ok === false) return null
      if (success) setNotice(success)
      await load()
      onChanged()
      return result
    } catch (e) {
      setError(e.message || String(e))
      return null
    } finally {
      setBusy('')
    }
  }

  const startTask = () => runAction('start', () => api('/api/workflow/start', {
    method: 'POST',
    body: { path: localPath, base, branch: branch.trim() },
  }), `Branch ${branch.trim()} created from ${base}.`).then(result => result && setBranch(''))

  const syncTask = () => runAction('sync', () => api('/api/workflow/sync', {
    method: 'POST',
    body: { path: localPath, base: syncBase, branch: syncBranch },
  }), `${syncBase} merged into ${syncBranch}.`)

  const commitChanges = () => runAction('commit', () => api('/api/commit', {
    method: 'POST',
    body: { path: localPath, message },
  }), 'Committed.').then(result => result && setMessage(''))

  const pushBranch = () => runAction('push', () => api('/api/push', {
    method: 'POST',
    body: { path: localPath, branch: current },
  }), `Pushed ${current || 'current branch'}.`)

  const fullName = repo?.owner && repo?.repo ? `${repo.owner}/${repo.repo}` : ''
  const defaultBranch = repo?.default_branch || defaultBase || ''
  const canOpenPull = Boolean(fullName && current && current !== defaultBranch)

  const openPullRequest = async () => {
    if (!canOpenPull) return
    setBusy('pr')
    setError('')
    setNotice('')
    setCreatedPr(null)
    try {
      const data = await api('/api/prs', {
        method: 'POST',
        body: {
          repo: fullName,
          title: prTitle.trim() || current,
          head: current,
          base: defaultBranch,
          body: prBody,
          draft: prDraft,
        },
      })
      setCreatedPr(data.pull)
      setNotice(`Pull request #${data.pull.number} opened.`)
      setPrBody('')
    } catch (e) {
      setError(e.message || String(e))
    } finally {
      setBusy('')
    }
  }

  const branchOptions = useMemo(
    () => local.map(branch => ({ value: branch.name, label: branch.current ? `${branch.name} (current)` : branch.name })),
    [local],
  )

  return (
    <div className="workflow">
      {error && <div className="banner error"><span>{error}</span></div>}
      {notice && <div className="banner ok"><span>{notice}</span></div>}

      <section className="section">
        <div className="section-head">
          <h3 className="section-title">Start a task</h3>
          <span className="muted small">for collaborators</span>
        </div>
        <Command parts={[`checkout ${base || '<base>'}`, `pull origin ${base || '<base>'}`, `checkout -b ${branch || '<branch>'}`]} />
        <div className="form-row">
          <label className="check small">
            base
            <select className="input head-select" value={base} onChange={event => setBase(event.target.value)}>
              {branchOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <input
            className="input"
            value={branch}
            onChange={event => setBranch(event.target.value)}
            placeholder="task branch name"
            onKeyDown={event => { if (event.key === 'Enter') startTask() }}
          />
          <button className="btn primary" onClick={startTask} disabled={busy !== '' || !base || !branch.trim()}>
            {busy === 'start' ? 'Running…' : 'Start task'}
          </button>
        </div>
        <Steps steps={logs.start || []} />
      </section>

      <section className="section">
        <div className="section-head">
          <h3 className="section-title">Update my branch with the base</h3>
          <span className="muted small">when the default branch moved</span>
        </div>
        <Command parts={[`checkout ${syncBase || '<base>'}`, `pull origin ${syncBase || '<base>'}`, `checkout ${syncBranch || '<branch>'}`, `merge ${syncBase || '<base>'}`]} />
        <div className="form-row">
          <label className="check small">
            base
            <select className="input head-select" value={syncBase} onChange={event => setSyncBase(event.target.value)}>
              {branchOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <label className="check small">
            my branch
            <select className="input head-select" value={syncBranch} onChange={event => setSyncBranch(event.target.value)}>
              {branchOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <button
            className="btn primary"
            onClick={syncTask}
            disabled={busy !== '' || !syncBase || !syncBranch || syncBase === syncBranch}
            title={syncBase === syncBranch ? 'Pick a branch different from the base' : ''}
          >
            {busy === 'sync' ? 'Running…' : 'Merge base in'}
          </button>
        </div>
        {syncBase === syncBranch && (
          <p className="muted small" style={{ marginTop: 6 }}>Pick a branch different from the base.</p>
        )}
        <Steps steps={logs.sync || []} />
      </section>

      <section className="section">
        <div className="section-head">
          <h3 className="section-title">Commit &amp; push</h3>
          <span className="muted small">on {current || 'the current branch'}</span>
        </div>
        <Command parts={['add -A', `commit -m "${message || '<message>'}"`, `push -u origin ${current || '<branch>'}`]} />
        <div className="form-row">
          <input
            className="input"
            value={message}
            onChange={event => setMessage(event.target.value)}
            placeholder="commit message"
            onKeyDown={event => { if (event.key === 'Enter') commitChanges() }}
          />
          <button className="btn" onClick={commitChanges} disabled={busy !== '' || !message.trim()}>
            {busy === 'commit' ? 'Committing…' : 'Stage all & commit'}
          </button>
          <button className="btn primary" onClick={pushBranch} disabled={busy !== '' || !current}>
            {busy === 'push' ? 'Pushing…' : `Push ${current || ''}`}
          </button>
        </div>
        <Steps steps={[...(logs.commit || []), ...(logs.push || [])]} />
      </section>

      {canOpenPull && (
        <section className="section">
          <div className="section-head">
            <h3 className="section-title">Open pull request</h3>
            <span className="muted small mono">{current} → {defaultBranch}</span>
          </div>
          <p className="muted small">Push the branch first — GitHub rejects a PR for a branch that is not on the remote yet.</p>
          <div className="form-col">
            <div className="form-row">
              <input
                className="input"
                value={prTitle}
                onChange={event => setPrTitle(event.target.value)}
                placeholder={`title (defaults to ${current})`}
              />
              <label className="check">
                <input type="checkbox" checked={prDraft} onChange={event => setPrDraft(event.target.checked)} />
                Draft
              </label>
              <button className="btn primary" onClick={openPullRequest} disabled={busy !== ''}>
                {busy === 'pr' ? 'Opening…' : 'Open pull request'}
              </button>
            </div>
            <textarea
              className="input area"
              rows={3}
              value={prBody}
              onChange={event => setPrBody(event.target.value)}
              placeholder="Description (optional)"
            />
          </div>
          {createdPr && (
            <p className="small">
              #{createdPr.number} {createdPr.title} —{' '}
              <a href={createdPr.html_url} target="_blank" rel="noopener noreferrer">open on GitHub ↗</a>
            </p>
          )}
        </section>
      )}
    </div>
  )
}
