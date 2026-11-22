import { useCallback, useEffect, useState } from 'react';

type Task = { id: string; name: string; prompt: string; baseline_checkpoint: string; success_rule: string; created_at: string };
type Trial = {
  id: string; task_id: string; start_cell: number; setup_note: string | null;
  status: string; episode_id: string | null; last_error: string | null;
};

async function requestJson<T>(url: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail ?? `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export default function Tasks() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selected, setSelected] = useState<Task | null>(null);
  const [trials, setTrials] = useState<Trial[]>([]);
  const [mode, setMode] = useState<'baseline' | 'deployed'>('baseline');
  const [deployedCheckpoint, setDeployedCheckpoint] = useState('');
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [checkpoint, setCheckpoint] = useState('');
  const [successRule, setSuccessRule] = useState('');
  const [cell, setCell] = useState(0);
  const [setupNote, setSetupNote] = useState('');
  const [labelTrial, setLabelTrial] = useState<string | null>(null);
  const [outcome, setOutcome] = useState('success');
  const [stage, setStage] = useState('');
  const [labelNote, setLabelNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const loadTasks = useCallback(async () => setTasks(await requestJson<Task[]>('/api/tasks')), []);
  const loadTrials = useCallback(async (taskId: string, purpose: 'baseline' | 'deployed' = mode) => {
    setTrials(await requestJson<Trial[]>(`/api/tasks/${taskId}/${purpose}-trials`));
    setDeployedCheckpoint((await requestJson<{ checkpoint: string }>(`/api/tasks/${taskId}/deployment`)).checkpoint);
  }, [mode]);

  useEffect(() => { void loadTasks().catch((caught: Error) => setError(caught.message)); }, [loadTasks]);

  async function act(operation: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('');
    try { await operation(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Action failed.'); }
    finally { setBusy(false); }
  }

  function choose(task: Task) {
    setSelected(task);
    setLabelTrial(null);
    void loadTrials(task.id).catch((caught: Error) => setError(caught.message));
  }

  function createTask(event: React.FormEvent) {
    event.preventDefault();
    void act(async () => {
      const task = await requestJson<Task>('/api/tasks', 'POST', { name, prompt, baseline_checkpoint: checkpoint, success_rule: successRule });
      await loadTasks(); choose(task);
      setName(''); setPrompt(''); setCheckpoint(''); setSuccessRule('');
      setMessage('Task created. Set up a baseline trial below.');
    });
  }

  function createTrial() {
    if (!selected) return;
    void act(async () => {
      await requestJson<Trial>(`/api/tasks/${selected.id}/${mode}-trials`, 'POST', { start_cell: cell, setup_note: setupNote.trim() || null });
      await loadTrials(selected.id);
      setSetupNote(''); setMessage('Trial planned. Prepare the scene before Start.');
    });
  }

  function runAction(trial: Trial, action: 'start' | 'stop' | 'sync' | 'reconcile') {
    if (!selected) return;
    if (action === 'start' && !window.confirm(`Robot motion will start. Place the object in grid cell ${trial.start_cell + 1}, clear the workspace, and supervise this run. Continue?`)) return;
    void act(async () => {
      const result = await requestJson<Trial>(`/api/trials/${trial.id}/${action}`, 'POST');
      await loadTrials(selected.id);
      setMessage(`Trial is ${result.status.replaceAll('_', ' ')}.`);
    });
  }

  function saveLabel(trial: Trial) {
    if (!selected) return;
    void act(async () => {
      await requestJson<Trial>(`/api/trials/${trial.id}/label`, 'POST', {
        success: outcome === 'success', failure_stage: outcome === 'failure' && stage ? stage : null,
        note: labelNote.trim() || null,
      });
      await loadTrials(selected.id);
      setLabelTrial(null); setLabelNote(''); setMessage('Outcome saved.');
    });
  }

  function abandon(trial: Trial) {
    if (!selected) return;
    const reason = window.prompt('Why is this stopped trial being abandoned? Its run will not enter the baseline.');
    if (!reason?.trim()) return;
    void act(async () => {
      await requestJson<Trial>(`/api/trials/${trial.id}/abandon`, 'POST', { reason: reason.trim() });
      await loadTrials(selected.id);
      setMessage('Trial abandoned. You can plan a replacement.');
    });
  }

  return <main className="page">
    <header className="header"><div><p className="eyebrow">Guided baseline</p><h1>Tasks and trials</h1><p className="subtitle">Define success, then measure the current checkpoint on marked starting positions.</p></div></header>
    {error && <div className="alert" role="alert">{error}</div>}
    {message && <div className="notice" role="status">{message}</div>}
    <div className="runs-layout">
      <section className="card runs-list">
        <h2>Tasks</h2>
        {tasks.map((task) => <button className={`run-row ${selected?.id === task.id ? 'selected' : ''}`} key={task.id} onClick={() => choose(task)}><strong>{task.name}</strong><span>{task.baseline_checkpoint}</span></button>)}
        {tasks.length === 0 && <p>No tasks yet.</p>}
      </section>
      <div className="task-column">
        <section className="card">
          <h2>Create task</h2>
          <form className="label-form task-form" onSubmit={createTask}>
            <label>Name<input required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} placeholder="Block into bin" /></label>
            <label>Robot instruction<input required maxLength={500} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Put the block into the bin" /></label>
            <label>Baseline checkpoint<input required maxLength={200} value={checkpoint} onChange={(event) => setCheckpoint(event.target.value)} placeholder="dreamlabs/dream-1-beta" /></label>
            <label>Success rule<textarea required maxLength={1000} value={successRule} onChange={(event) => setSuccessRule(event.target.value)} placeholder="The block rests inside the bin at the end of the run." /></label>
            <button disabled={busy}>Create task</button>
          </form>
        </section>
        {selected && <section className="card">
          <h2>{selected.name}: {mode === 'baseline' ? 'baseline' : 'deployed checkpoint'}</h2>
          <label>Run type <select value={mode} onChange={(event) => { const value = event.target.value as 'baseline' | 'deployed'; setMode(value); void loadTrials(selected.id, value); }}><option value="baseline">Baseline experiment</option><option value="deployed">Current deployed checkpoint</option></select></label>
          {mode === 'deployed' && <p><strong>Checkpoint for new runs:</strong> {deployedCheckpoint}</p>}
          <p><strong>Instruction:</strong> {selected.prompt}</p>
          <p><strong>Success:</strong> {selected.success_rule}</p>
          <p className="hint">Place the object within the selected cell of a marked 3×3 grid. Confirm each setup before starting; the robot may move.</p>
          <div className="trial-create">
            <label>Start cell<select value={cell} onChange={(event) => setCell(Number(event.target.value))}>{Array.from({ length: 9 }, (_, index) => <option key={index} value={index}>Cell {index + 1}</option>)}</select></label>
            <label>Setup note<input maxLength={1000} value={setupNote} onChange={(event) => setSetupNote(event.target.value)} placeholder="Object position or lighting" /></label>
            <button onClick={createTrial} disabled={busy}>Plan trial</button>
          </div>
          <h3>Trials</h3>
          {trials.length === 0 && <p className="muted">No trials planned yet.</p>}
          {trials.map((trial) => <div className="trial-row" key={trial.id}>
            <div><strong>Cell {trial.start_cell + 1}</strong><small>{trial.status.replaceAll('_', ' ')}{trial.setup_note ? ` · ${trial.setup_note}` : ''}</small>{trial.last_error && <small className="trial-error">{trial.last_error}</small>}</div>
            <div className="trial-actions">
              {trial.status === 'planned' && <button onClick={() => runAction(trial, 'start')} disabled={busy}>Start robot</button>}
              {trial.status === 'starting' && <button onClick={() => runAction(trial, 'reconcile')} disabled={busy}>Check station</button>}
              {trial.status === 'running' && <><button onClick={() => runAction(trial, 'stop')} disabled={busy}>Stop robot</button><button className="secondary" onClick={() => runAction(trial, 'sync')} disabled={busy}>Sync if ended</button></>}
              {trial.status === 'awaiting_rollout' && <><button onClick={() => runAction(trial, 'sync')} disabled={busy}>Find rollout</button><button className="secondary" onClick={() => abandon(trial)} disabled={busy}>Abandon</button></>}
              {trial.status === 'awaiting_label' && <button onClick={() => { setLabelTrial(trial.id); setOutcome('success'); setStage(''); }} disabled={busy}>Label outcome</button>}
              {trial.status === 'completed' && <span className="model-ready">Label saved</span>}
            </div>
            {labelTrial === trial.id && <div className="label-form trial-label">
              <label>Outcome<select value={outcome} onChange={(event) => setOutcome(event.target.value)}><option value="success">Success</option><option value="failure">Failure</option></select></label>
              {outcome === 'failure' && <label>Failure stage<select value={stage} onChange={(event) => setStage(event.target.value)}><option value="">Unknown</option><option value="approach">Approach</option><option value="grasp">Grasp</option><option value="transport">Transport</option><option value="release">Release</option><option value="other">Other</option></select></label>}
              <label>Note<textarea maxLength={2000} value={labelNote} onChange={(event) => setLabelNote(event.target.value)} /></label>
              <button onClick={() => saveLabel(trial)} disabled={busy}>Save outcome</button>
            </div>}
          </div>)}
        </section>}
      </div>
    </div>
  </main>;
}
