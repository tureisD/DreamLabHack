import { useEffect, useRef, useState, type ReactNode } from 'react';

type Demo = {
  id: string;
  task_id: string;
  task_text: string;
  camera_keys: string[];
  findings: { code: string; severity: 'error' | 'review'; message: string }[];
  decision: 'unreviewed' | 'keep' | 'redo';
  start_cell: number | null;
  note: string | null;
};

type ReviewSelection = {
  demoId: string;
  camera: string;
  startCell: number | null;
  note: string;
};

export type DemoKeepReceipt = { taskId: string; kept: number; remaining: number };

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { cache: 'no-store', ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Request failed (${response.status}).`);
  }
  return response.json() as Promise<T>;
}

function cameraRole(key: string) {
  return key.replace(/^observation\.images\./, '');
}

function cameraLabel(role: string) {
  if (role === 'wrist_l') return 'Left wrist';
  if (role === 'wrist_r') return 'Right wrist';
  return role.replace(/[-_]/g, ' ').replace(/^\w/, (letter) => letter.toUpperCase());
}

function selectDemo(demo: Demo): ReviewSelection {
  const roles = demo.camera_keys.map(cameraRole);
  return {
    demoId: demo.id,
    camera: roles.includes('overhead') ? 'overhead' : roles[0] ?? '',
    startCell: demo.start_cell,
    note: demo.note ?? '',
  };
}

export default function ChatDemoReview({ taskId, onClose, onKeep }: {
  taskId: string;
  onClose: () => void;
  onKeep: (receipt: DemoKeepReceipt) => void;
}) {
  const [demos, setDemos] = useState<Demo[]>([]);
  const [selection, setSelection] = useState<ReviewSelection | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [loadFailed, setLoadFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const [message, setMessage] = useState('');
  const [videoError, setVideoError] = useState(false);
  const requestScope = useRef<AbortController | null>(null);
  const pending = demos.filter((demo) => demo.task_id === taskId && demo.decision === 'unreviewed');
  const demo = pending.find((item) => item.id === selection?.demoId);
  const hasIssue = demo?.findings.some((finding) => finding.severity === 'error');

  useEffect(() => {
    const controller = new AbortController();
    requestScope.current = controller;
    setLoading(true);
    setLoadFailed(false);
    setSaving(false);
    setDemos([]);
    setSelection(null);
    setError('');
    setMessage('');
    setVideoError(false);

    void request<Demo[]>(`/api/tasks/${encodeURIComponent(taskId)}/demos`, { signal: controller.signal })
      .then((values) => {
        if (controller.signal.aborted) return;
        const first = values.find((item) => item.task_id === taskId && item.decision === 'unreviewed');
        setDemos(values);
        setSelection(first ? selectDemo(first) : null);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : 'Could not load demos.');
          setLoadFailed(true);
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });

    return () => controller.abort();
  }, [taskId, retry]);

  function choose(item: Demo) {
    setSelection(selectDemo(item));
    setVideoError(false);
    setError('');
    setMessage('');
  }

  async function decide(decision: 'keep' | 'redo') {
    const signal = requestScope.current?.signal;
    if (!demo || !selection || saving || !signal || signal.aborted || (decision === 'keep' && hasIssue)) return;
    const startCell = decision === 'keep' ? selection.startCell : null;
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const saved = await request<Demo>(`/api/demos/${encodeURIComponent(demo.id)}/decision`, {
        method: 'POST',
        signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision,
          start_cell: startCell,
          note: selection.note.trim() || null,
          ...(decision === 'keep' && startCell === null ? { defer_coverage_label: true } : {}),
        }),
      });
      if (signal.aborted) return;
      if (saved.id !== demo.id || saved.task_id !== taskId || saved.decision !== decision) {
        throw new Error('The server did not confirm this demo decision.');
      }
      const updated = demos.map((item) => item.id === saved.id ? saved : item).filter((item) => item.task_id === taskId);
      const remaining = updated.filter((item) => item.decision === 'unreviewed');
      if (saved.decision === 'keep') {
        onKeep({
          taskId,
          kept: updated.filter((item) => item.decision === 'keep').length,
          remaining: remaining.length,
        });
      } else {
        setDemos(updated);
        const nextIndex = pending.findIndex((item) => item.id === demo.id);
        const next = remaining[nextIndex] ?? remaining[0];
        setSelection(next ? selectDemo(next) : null);
        setVideoError(false);
        setMessage('Demo marked for redo.');
      }
    } catch (caught) {
      if (!signal.aborted) setError(caught instanceof Error ? caught.message : 'Could not save your decision.');
    } finally {
      if (!signal.aborted) setSaving(false);
    }
  }

  let content: ReactNode;
  if (loading) {
    content = <p role="status">Loading demos…</p>;
  } else if (loadFailed) {
    content = <button type="button" className="secondary" onClick={() => setRetry((previous) => previous + 1)}>Retry</button>;
  } else if (!demo || !selection) {
    content = <p>No demos waiting for review.</p>;
  } else {
    const roles = demo.camera_keys.map(cameraRole);
    content = <>
      {pending.length > 1 && <label className="chat-workspace-field">Demo
        <select value={demo.id} disabled={saving} onChange={(event) => {
          const next = pending.find((item) => item.id === event.target.value);
          if (next) choose(next);
        }}>
          {pending.map((item, index) => <option key={item.id} value={item.id}>Demo {index + 1} of {pending.length}</option>)}
        </select>
      </label>}
      {roles.length > 1 && <div className="role-tabs" role="group" aria-label="Camera view">
        {roles.map((role) => <button
          type="button"
          key={role}
          className={selection.camera === role ? 'role-active' : ''}
          aria-pressed={selection.camera === role}
          disabled={saving}
          onClick={() => {
            setSelection({ ...selection, camera: role });
            setVideoError(false);
          }}
        >{cameraLabel(role)}</button>)}
      </div>}
      {selection.camera ? <video
        className="chat-demo-video"
        key={`${demo.id}:${selection.camera}`}
        aria-label={`${cameraLabel(selection.camera)} camera demo`}
        src={`/api/demos/${encodeURIComponent(demo.id)}/video/${encodeURIComponent(selection.camera)}`}
        controls
        playsInline
        preload="metadata"
        onError={() => setVideoError(true)}
      /> : <p>No camera clips are available for this demo.</p>}
      {videoError && <p role="status">This camera clip could not be played.</p>}
      {demo.findings.length > 0 ? <div>
        <h3>{hasIssue ? 'Fix before keeping' : 'Check these in the clip'}</h3>
        <ul className="chat-demo-findings">
          {demo.findings.map((finding, index) => <li key={`${finding.code}-${index}`}>{finding.message}</li>)}
        </ul>
      </div> : <p>No issues flagged by the automated checks. Watch the clip before keeping it.</p>}
      <details className="chat-demo-details">
        <summary>Review details</summary>
        <div className="label-form">
          <label>Object start cell (optional)
            <select value={selection.startCell ?? ''} disabled={saving} onChange={(event) => {
              const value = event.target.value;
              setSelection({ ...selection, startCell: value === '' ? null : Number(value) });
            }}>
              <option value="">Unlabeled</option>
              {Array.from({ length: 9 }, (_, index) => <option key={index} value={index}>Cell {index + 1}</option>)}
            </select>
          </label>
          <label>Note (optional)
            <textarea maxLength={2000} value={selection.note} disabled={saving} onChange={(event) => {
              setSelection({ ...selection, note: event.target.value });
            }} />
          </label>
        </div>
      </details>
      <div className="chat-workspace-actions">
        <button type="button" onClick={() => void decide('keep')} disabled={saving || hasIssue}>Keep demo</button>
        <button type="button" className="secondary" onClick={() => void decide('redo')} disabled={saving}>Redo</button>
        {saving && <small role="status">Saving…</small>}
      </div>
    </>;
  }

  return <section className="chat-inline-workspace" aria-label="Demo review" aria-busy={loading || saving}>
    <header className="chat-workspace-header">
      <div>
        <h2>Review demos</h2>
        {demo && <p>{demo.task_text}</p>}
      </div>
      <button type="button" className="secondary" disabled={saving} onClick={onClose}>Back to chat</button>
    </header>
    {error && <p className="alert" role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {content}
  </section>;
}
