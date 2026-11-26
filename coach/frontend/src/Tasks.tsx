import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, ChevronRight, Film, Plus, X } from 'lucide-react';
import { initialTask, screenHref, selectTask } from './workspaceRoute';
import './task-workflow.css';

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

export default function Tasks({ initialTaskId = '', embedded = false, onTaskSelected, onReview }: {
  initialTaskId?: string;
  embedded?: boolean;
  onTaskSelected?: (taskId: string) => void;
  onReview?: (taskId: string, prompt: string) => void;
} = {}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [tasksLoading, setTasksLoading] = useState(true);
  const [tasksFailed, setTasksFailed] = useState(false);
  const [trialsFailed, setTrialsFailed] = useState(false);
  const trialRequest = useRef(0);
  const [selected, setSelected] = useState<Task | null>(null);
  const [trials, setTrials] = useState<Trial[]>([]);
  const [trialsLoading, setTrialsLoading] = useState(false);
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
  const [createFormOpen, setCreateFormOpen] = useState(false);

  const loadTasks = useCallback(async () => {
    try {
      setTasksLoading(true);
      const data = await requestJson<Task[]>('/api/tasks');
      setTasks(data);
      setSelected(prev => data.find(task => task.id === (prev?.id ?? initialTaskId))
        ?? (embedded ? null : initialTask(data)) ?? null);
      setTasksFailed(false);
      setError('');
    } catch (caught) {
      setTasksFailed(true);
      setError(caught instanceof Error ? caught.message : 'Failed to load tasks');
    } finally {
      setTasksLoading(false);
    }
  }, [embedded, initialTaskId]);

  const loadTrials = useCallback(async (taskId: string, purpose: 'baseline' | 'deployed' = mode) => {
    const token = ++trialRequest.current;
    try {
      setTrialsLoading(true); setTrialsFailed(false); setTrials([]); setDeployedCheckpoint('');
      const [trialData, deployData] = await Promise.all([
        requestJson<Trial[]>(`/api/tasks/${taskId}/${purpose}-trials`),
        requestJson<{ checkpoint: string }>(`/api/tasks/${taskId}/deployment`),
      ]);
      if (token !== trialRequest.current) return;
      setTrials(trialData);
      setDeployedCheckpoint(deployData.checkpoint);
      setError('');
    } catch (caught) {
      if (token === trialRequest.current) { setTrialsFailed(true); setError(caught instanceof Error ? caught.message : 'Failed to load trials'); }
    } finally {
      if (token === trialRequest.current) setTrialsLoading(false);
    }
  }, [mode]);

  useEffect(() => { void loadTasks(); }, [loadTasks]);

  useEffect(() => {
    if (selected) void loadTrials(selected.id);
    return () => { trialRequest.current++; };
  }, [selected, loadTrials]);

  async function act(operation: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('');
    try { await operation(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Action failed.'); }
    finally { setBusy(false); }
  }

  function choose(task: Task) {
    setSelected(task);
    if (onTaskSelected) onTaskSelected(task.id);
    else selectTask(task.id);
    setLabelTrial(null);
    setMessage(''); setCreateFormOpen(false);
  }

  function createTask(event: React.FormEvent) {
    event.preventDefault();
    void act(async () => {
      const task = await requestJson<Task>('/api/tasks', 'POST', { name, prompt, baseline_checkpoint: checkpoint, success_rule: successRule });
      await loadTasks();
      choose(task);
      setName('');
      setPrompt('');
      setCheckpoint('');
      setSuccessRule('');
      setCreateFormOpen(false);
      setMessage('Task created. Set up a baseline trial below.');
    });
  }

  function createTrial() {
    if (!selected) return;
    void act(async () => {
      await requestJson<Trial>(`/api/tasks/${selected.id}/${mode}-trials`, 'POST', { start_cell: cell, setup_note: setupNote.trim() || null });
      await loadTrials(selected.id);
      setSetupNote('');
      setMessage('Trial planned. Prepare the scene before Start.');
    });
  }

  function runAction(trial: Trial, action: 'start' | 'stop' | 'sync' | 'reconcile') {
    if (!selected) return;
    if (action === 'start' && !window.confirm(`Caution: Robot motion will start. Place the object in grid cell ${trial.start_cell + 1}, clear the workspace, and supervise this run. Continue?`)) return;
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

  const Container = embedded ? 'div' : 'main';
  return <Container className="page task-workspace">
    {!embedded && <header className="header" style={{ gridColumn: '1 / -1', margin: 0 }}><div><p className="eyebrow">Guided baseline</p><h1>Tasks and trials</h1><p className="subtitle">Define success, then measure the current checkpoint on marked starting positions.</p></div></header>}
    {error && <div className="task-status-message error" role="alert">{error}</div>}
    {message && <div className="task-status-message success" role="status">{message}</div>}

    <aside className="task-sidebar">
      <div className="task-list-header">
        <h2>Tasks</h2>
        <span className="task-count" aria-label={`${tasks.length} tasks`}>{tasks.length}</span>
      </div>
      {tasksLoading ? (
        <div className="task-loading">Loading tasks…</div>
      ) : tasksFailed ? (
        <button type="button" onClick={() => void loadTasks()}>Retry loading tasks</button>
      ) : tasks.length === 0 ? (
        <div className="task-empty">No tasks yet. Create one to begin.</div>
      ) : (
        <div className="task-list">
          {tasks.map((task) => (
            <button
              key={task.id}
              className={`task-item ${selected?.id === task.id ? 'selected' : ''}`}
              onClick={() => choose(task)}
              aria-current={selected?.id === task.id ? 'true' : undefined}
            >
              <div className="task-item-name">{task.name}</div>
              <div className="task-item-checkpoint">{task.baseline_checkpoint}</div>
            </button>
          ))}
        </div>
      )}
      {!tasksLoading && !tasksFailed && <button type="button" className="task-create-toggle" disabled={busy} aria-expanded={createFormOpen} onClick={() => setCreateFormOpen(v => !v)}>{createFormOpen ? <X size={15}/> : <Plus size={15}/>} {createFormOpen ? 'Cancel creation' : 'New task'}</button>}
    </aside>

    <div className="task-content">
      {selected && !createFormOpen ? (
        <>
          <section className="task-overview">
            <div className="task-overview-header">
              <h2 className="task-overview-title">{selected.name}</h2>
              {onReview ? <button type="button" className="secondary task-recordings-link"
                onClick={() => onReview(selected.id, selected.prompt)}><Film size={16} />Review recordings</button>
              : <a href={screenHref('runs', { task: selected.id, prompt: selected.prompt })} className="task-recordings-link">
                <Film size={16} />
                Review recordings
                <ChevronRight size={16} />
              </a>}
            </div>

            <div className="task-meta-row">
              <span className="task-meta-label">Instruction</span>
              <p className="task-meta-value">{selected.prompt}</p>
            </div>

            <div>
              <span className="task-meta-label">Success rule</span>
              <div className="task-success-rule">{selected.success_rule}</div>
            </div>

            <div className="task-meta-row">
              <span className="task-meta-label">Baseline checkpoint</span>
              <div className="task-meta-value emphasis">{selected.baseline_checkpoint}</div>
            </div>
          </section>

          <section className="trial-section">
            <div className="trial-section-header">
              <h2>{mode === 'baseline' ? 'Baseline experiment' : 'Deployed checkpoint'}</h2>
            </div>

            <div className="trial-mode-control">
              <label htmlFor="mode-select">Run type</label>
              <select
                id="mode-select"
                className="trial-mode-select"
                value={mode}
                onChange={(event) => {
                  const value = event.target.value as 'baseline' | 'deployed';
                  setLabelTrial(null); setMode(value);
                }}
              >
                <option value="baseline">Baseline experiment</option>
                <option value="deployed">Current deployed checkpoint</option>
              </select>
            </div>

            {mode === 'deployed' && deployedCheckpoint && (
              <div className="trial-deployed-checkpoint">
                <strong>Checkpoint for new runs:</strong> {deployedCheckpoint}
              </div>
            )}

            <div className="trial-safety-notice">
              <AlertTriangle size={16} aria-hidden="true"/> Place the object within a cell of the marked 3×3 grid. Confirm setup before starting. The robot will move.
            </div>

            <form
              className="trial-create-form"
              onSubmit={(e) => {
                e.preventDefault();
                createTrial();
              }}
            >
              <div className="trial-create-label">
                <span>Start cell</span>
                <select
                  className="trial-create-select" aria-label="Start cell"
                  value={cell}
                  onChange={(event) => setCell(Number(event.target.value))}
                >
                  {Array.from({ length: 9 }, (_, index) => (
                    <option key={index} value={index}>
                      Cell {index + 1}
                    </option>
                  ))}
                </select>
              </div>
              <div className="trial-create-label">
                <span>Setup note (optional)</span>
                <input
                  className="trial-create-input" aria-label="Setup note"
                  type="text"
                  maxLength={1000}
                  value={setupNote}
                  onChange={(event) => setSetupNote(event.target.value)}
                  placeholder="Position, lighting, etc."
                />
              </div>
              <button type="submit" className="trial-create-submit" disabled={busy || trialsLoading}>
                Plan trial
              </button>
            </form>

            <div className="trial-list-header">
              <h3>Trials</h3>
            </div>

            {trialsLoading ? (
              <div className="trial-empty">Loading trials…</div>
            ) : trialsFailed ? (
              <button type="button" onClick={() => void loadTrials(selected.id)}>Retry loading trials</button>
            ) : trials.length === 0 ? (
              <div className="trial-empty">No trials planned yet.</div>
            ) : (
              <div className="trial-list">
                {trials.map((trial) => (
                  <div key={trial.id}>
                    <div className="trial-item">
                      <div className="trial-info">
                        <div className="trial-cell">Cell {trial.start_cell + 1}</div>
                        <div className="trial-status">
                          {trial.status.replaceAll('_', ' ')}
                          {trial.setup_note && ` · ${trial.setup_note}`}
                        </div>
                        {trial.last_error && <div className="trial-error">{trial.last_error}</div>}
                      </div>
                      <div className="trial-actions">
                        {trial.status === 'planned' && (
                          <button
                            type="button"
                            className="trial-action-btn primary"
                            onClick={() => runAction(trial, 'start')}
                            disabled={busy}
                          >
                            Start robot
                          </button>
                        )}
                        {trial.status === 'starting' && (
                          <button
                            type="button"
                            className="trial-action-btn"
                            onClick={() => runAction(trial, 'reconcile')}
                            disabled={busy}
                          >
                            Check station
                          </button>
                        )}
                        {trial.status === 'running' && (
                          <>
                            <button
                              type="button"
                              className="trial-action-btn"
                              onClick={() => runAction(trial, 'stop')}
                              disabled={busy}
                            >
                              Stop robot
                            </button>
                            <button
                              type="button"
                              className="trial-action-btn secondary"
                              onClick={() => runAction(trial, 'sync')}
                              disabled={busy}
                            >
                              Sync if ended
                            </button>
                          </>
                        )}
                        {trial.status === 'awaiting_rollout' && (
                          <>
                            <button
                              type="button"
                              className="trial-action-btn"
                              onClick={() => runAction(trial, 'sync')}
                              disabled={busy}
                            >
                              Find rollout
                            </button>
                            <button
                              type="button"
                              className="trial-action-btn secondary"
                              onClick={() => abandon(trial)}
                              disabled={busy}
                            >
                              Abandon
                            </button>
                          </>
                        )}
                        {trial.status === 'awaiting_label' && (
                          <button
                            type="button"
                            className="trial-action-btn primary"
                            onClick={() => {
                              setLabelTrial(trial.id);
                              setOutcome('success');
                              setStage('');
                            }}
                            disabled={busy}
                          >
                            Label outcome
                          </button>
                        )}
                        {trial.status === 'completed' && <div className="trial-completed">Labelled</div>}
                      </div>
                    </div>
                    {labelTrial === trial.id && (
                      <form
                        className="trial-label-form"
                        onSubmit={(e) => {
                          e.preventDefault();
                          saveLabel(trial);
                        }}
                      >
                        <label>
                          <span>Outcome</span>
                          <select
                            value={outcome}
                            onChange={(event) => setOutcome(event.target.value)}
                          >
                            <option value="success">Success</option>
                            <option value="failure">Failure</option>
                          </select>
                        </label>
                        {outcome === 'failure' && (
                          <label>
                            <span>Failure stage</span>
                            <select value={stage} onChange={(event) => setStage(event.target.value)}>
                              <option value="">Unknown</option>
                              <option value="approach">Approach</option>
                              <option value="grasp">Grasp</option>
                              <option value="transport">Transport</option>
                              <option value="release">Release</option>
                              <option value="other">Other</option>
                            </select>
                          </label>
                        )}
                        <label>
                          <span>Observation</span>
                          <textarea
                            maxLength={2000}
                            value={labelNote}
                            onChange={(event) => setLabelNote(event.target.value)}
                            placeholder="Any notes about this run…"
                          />
                        </label>
                        <button type="submit" className="trial-label-submit" disabled={busy}>
                          Save outcome
                        </button>
                      </form>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      ) : (
        <section className="task-create-section">
          <div className="task-create-header"><h2>{createFormOpen ? 'Create task' : tasksLoading ? 'Loading…' : tasksFailed ? 'Tasks unavailable' : 'No task selected'}</h2></div>
          {createFormOpen && (
            <form className="task-form" onSubmit={createTask} style={{ marginTop: 'var(--spacing-lg)' }}>
              <div className="task-form-label">
                <span className="task-form-label-text">Task name</span>
                <input
                  className="task-form-input"
                  aria-label="Task name"
                  type="text"
                  required
                  maxLength={120}
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="e.g., Block into bin"
                />
              </div>
              <div className="task-form-label">
                <span className="task-form-label-text">Robot instruction</span>
                <input
                  className="task-form-input"
                  type="text"
                  required
                  aria-label="Robot instruction"
                  maxLength={500}
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  placeholder="e.g., Put the block into the bin"
                />
              </div>
              <div className="task-form-label">
                <span className="task-form-label-text">Baseline checkpoint</span>
                <input
                  className="task-form-input"
                  type="text"
                  required
                  aria-label="Baseline checkpoint"
                  maxLength={200}
                  value={checkpoint}
                  onChange={(event) => setCheckpoint(event.target.value)}
                  placeholder="e.g., dreamlabs/dream-1-beta"
                />
              </div>
              <div className="task-form-label">
                <span className="task-form-label-text">Success rule</span>
                <textarea
                  className="task-form-textarea"
                  aria-label="Success rule"
                  required
                  maxLength={1000}
                  value={successRule}
                  onChange={(event) => setSuccessRule(event.target.value)}
                  placeholder="e.g., The block rests inside the bin at the end of the run."
                />
              </div>
              <button type="submit" className="task-form-submit" disabled={busy}>
                Create task
              </button>
            </form>
          )}
        </section>
      )}
    </div>
  </Container>;
}
