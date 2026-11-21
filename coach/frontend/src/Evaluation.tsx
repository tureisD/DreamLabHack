import { useCallback, useEffect, useState } from 'react';

type Task = { id: string; name: string; success_rule: string; baseline_checkpoint: string };
type Job = { id: string; status: string; checkpoint: string | null };
type Evaluation = {
  id: string; task_id: string; fine_tune_job_id: string; baseline_checkpoint: string;
  candidate_checkpoint: string; minimum_effect: number; created_at: string;
  auto_promote: boolean;
};
type Deployment = { checkpoint: string; baseline_checkpoint: string };
type Trial = {
  id: string; status: string; checkpoint: string; scene_index: number;
  sequence_index: number; start_cell: number; setup_note: string;
  episode_id: string | null; last_error: string | null;
};
type Report = {
  usable_pairs: number; target_pairs: number; baseline_successes: number; candidate_successes: number;
  baseline_only: number; candidate_only: number; paired_difference: number | null;
  ci_low: number | null; ci_high: number | null; exact_p_value: number | null;
  baseline_safety_stops: number; candidate_safety_stops: number;
  decision: 'improved' | 'inconclusive' | 'worse'; reason: string;
};

async function json<T>(url: string, method = 'GET', body?: unknown): Promise<T> {
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

function percent(value: number | null) { return value === null ? '—' : `${(value * 100).toFixed(1)}%`; }

export default function EvaluationPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskId, setTaskId] = useState('');
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobId, setJobId] = useState('');
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [trials, setTrials] = useState<Trial[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [minimumEffect, setMinimumEffect] = useState(0.15);
  const [autoPromote, setAutoPromote] = useState(false);
  const [deployment, setDeployment] = useState<Deployment | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [outcome, setOutcome] = useState<'success' | 'failure'>('success');
  const [stage, setStage] = useState('');
  const [note, setNote] = useState('');

  useEffect(() => {
    void json<Task[]>('/api/tasks').then((values) => {
      setTasks(values); if (values.length) setTaskId(values[0].id);
    }).catch((caught: Error) => setError(caught.message));
  }, []);

  useEffect(() => {
    if (!taskId) return;
    let active = true;
    const refresh = async () => {
      try {
        const [work, values] = await Promise.all([
          json<Job[]>(`/api/tasks/${taskId}/finetunes`),
          json<Evaluation[]>(`/api/tasks/${taskId}/evaluations`),
        ]);
        if (active) {
          setJobs(work);
          setJobId((current) => work.some((job) => job.id === current) ? current : (work.find((job) => job.status === 'succeeded')?.id ?? ''));
          setEvaluations(values);
          setSelectedId((current) => values.some((item) => item.id === current) ? current : (values[0]?.id ?? ''));
          setDeployment(await json<Deployment>(`/api/tasks/${taskId}/deployment`));
        }
      } catch (caught) { if (active) setError(caught instanceof Error ? caught.message : 'Could not load evaluations.'); }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [taskId]);

  const refreshEvaluation = useCallback(async (id: string) => {
    const [nextTrials, nextReport] = await Promise.all([
      json<Trial[]>(`/api/evaluations/${id}/trials`),
      json<Report>(`/api/evaluations/${id}/report`),
    ]);
    setTrials(nextTrials); setReport(nextReport);
  }, []);

  useEffect(() => {
    if (!selectedId) { setTrials([]); setReport(null); return; }
    let active = true;
    const refresh = async () => {
      try { if (active) await refreshEvaluation(selectedId); }
      catch (caught) { if (active) setError(caught instanceof Error ? caught.message : 'Could not load evaluation.'); }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10000);
    return () => { active = false; window.clearInterval(timer); };
  }, [selectedId, refreshEvaluation]);

  async function act(operation: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('');
    try { await operation(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Action failed.'); }
    finally { setBusy(false); }
  }

  function create() {
    if (!taskId || !jobId) return;
    void act(async () => {
      const result = await json<Evaluation>(`/api/tasks/${taskId}/evaluations`, 'POST', {
        fine_tune_job_id: jobId, minimum_effect: minimumEffect, auto_promote: autoPromote,
      });
      setEvaluations(await json<Evaluation[]>(`/api/tasks/${taskId}/evaluations`));
      setSelectedId(result.id);
      setMessage('Evaluation planned. Follow the displayed scene order and reset the setup between runs.');
    });
  }

  function trialAction(trial: Trial, action: 'start' | 'stop' | 'sync' | 'reconcile') {
    if (!selectedId) return;
    if (action === 'start' && !window.confirm(`Robot motion will start with ${trial.checkpoint}. ${trial.setup_note} Clear the workspace and supervise the run. Continue?`)) return;
    void act(async () => {
      const result = await json<Trial>(`/api/trials/${trial.id}/${action}`, 'POST');
      await refreshEvaluation(selectedId);
      setMessage(`Trial is ${result.status.replaceAll('_', ' ')}.`);
    });
  }

  function label(trial: Trial) {
    if (!selectedId) return;
    void act(async () => {
      await json<Trial>(`/api/trials/${trial.id}/label`, 'POST', {
        success: outcome === 'success', failure_stage: outcome === 'failure' && stage ? stage : null,
        note: note.trim() || null,
      });
      await refreshEvaluation(selectedId);
      setOutcome('success'); setStage(''); setNote('');
      setMessage('Outcome saved. Reset the scene for the next run.');
    });
  }

  function abandon(trial: Trial) {
    if (!selectedId) return;
    const reason = window.prompt('Why is this stopped trial unusable? This evaluation will remain inconclusive.');
    if (!reason?.trim()) return;
    void act(async () => {
      await json<Trial>(`/api/trials/${trial.id}/abandon`, 'POST', { reason: reason.trim() });
      await refreshEvaluation(selectedId);
      setMessage('Trial marked unusable. Create a new evaluation for a complete comparison.');
    });
  }

  function rollback() {
    if (!taskId || !window.confirm('Restore the baseline checkpoint for future coach task runs?')) return;
    void act(async () => {
      setDeployment(await json<Deployment>(`/api/tasks/${taskId}/deployment/rollback`, 'POST'));
      setMessage('Future deployed trials will use the baseline checkpoint.');
    });
  }

  function promote() {
    if (!selectedId || !taskId || !window.confirm('Use this verified candidate for future coach task runs?')) return;
    void act(async () => {
      setDeployment(await json<Deployment>(`/api/evaluations/${selectedId}/promote`, 'POST'));
      setMessage('Future deployed trials will use the candidate checkpoint.');
    });
  }

  const selected = evaluations.find((value) => value.id === selectedId);
  const unusable = trials.some((trial) => trial.status === 'abandoned');
  const nextTrial = unusable ? undefined : trials.find((trial) => !['completed', 'abandoned'].includes(trial.status));
  const task = tasks.find((value) => value.id === taskId);
  const candidates = jobs.filter((job) => job.status === 'succeeded' && job.checkpoint);

  return <main className="page">
    <header className="header"><div><p className="eyebrow">Before and after</p><h1>Evaluate the fine-tune</h1><p className="subtitle">Run both checkpoints on the same 30 held-out setups, then read the paired result.</p></div></header>
    {error && <div className="alert" role="alert">{error}</div>}
    {message && <div className="notice" role="status">{message}</div>}
    <section className="card">
      <div className="training-controls">
        <label>Task<select value={taskId} onChange={(event) => { setTaskId(event.target.value); setSelectedId(''); }}><option value="">Choose a task</option>{tasks.map((value) => <option key={value.id} value={value.id}>{value.name}</option>)}</select></label>
        <label>Fine-tuned checkpoint<select value={jobId} onChange={(event) => setJobId(event.target.value)}><option value="">Choose a completed job</option>{candidates.map((job) => <option key={job.id} value={job.id}>{job.checkpoint}</option>)}</select></label>
        <label>Minimum useful gain<input type="number" min="0" max="100" step="1" value={Math.round(minimumEffect * 100)} onChange={(event) => setMinimumEffect(Number(event.target.value) / 100)} />%</label>
        <label>After a verified improvement<select value={autoPromote ? 'yes' : 'no'} onChange={(event) => setAutoPromote(event.target.value === 'yes')}><option value="no">Review before switching</option><option value="yes">Automatically use candidate for future coach runs</option></select></label>
        <button disabled={busy || !taskId || !jobId || !Number.isFinite(minimumEffect) || minimumEffect < 0 || minimumEffect > 1} onClick={create}>Plan comparison</button>
      </div>
      <p className="hint">The gain threshold is fixed when you plan the evaluation. Each setup is specified as a position on your marked table and a rotation. Use the same object, lighting, and success rule for both runs in a pair. Keep these setups out of training.</p>
      {task && <p><strong>Success rule:</strong> {task.success_rule}</p>}
      {deployment && <p><strong>Checkpoint for future task runs:</strong> {deployment.checkpoint} {deployment.checkpoint !== deployment.baseline_checkpoint && <button className="secondary" disabled={busy} onClick={rollback}>Roll back to baseline</button>}</p>}
      {evaluations.length > 0 && <label className="evaluation-select">Comparison<select value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>{evaluations.map((item) => <option key={item.id} value={item.id}>{item.candidate_checkpoint} · {item.created_at}</option>)}</select></label>}
    </section>

    {selected && report && <section className="card evaluation-report">
      <h2>Verdict: {report.decision}</h2>
      <p>{report.reason}</p>
      <div className="evaluation-metrics">
        <div><strong>{report.usable_pairs}/{report.target_pairs}</strong><span>usable pairs</span></div>
        <div><strong>{report.baseline_successes}/{report.usable_pairs}</strong><span>baseline successes</span></div>
        <div><strong>{report.candidate_successes}/{report.usable_pairs}</strong><span>candidate successes</span></div>
        <div><strong>{percent(report.paired_difference)}</strong><span>paired gain</span></div>
      </div>
      <p className="hint">95% paired bootstrap interval: {percent(report.ci_low)} to {percent(report.ci_high)}. Exact paired test p={report.exact_p_value?.toFixed(4) ?? '—'}. Candidate-only wins: {report.candidate_only}; baseline-only wins: {report.baseline_only}. Safety stops: {report.baseline_safety_stops} baseline, {report.candidate_safety_stops} candidate.</p>
      {report.decision === 'improved' && deployment?.checkpoint !== selected.candidate_checkpoint && <button disabled={busy} onClick={promote}>Use verified candidate</button>}
      <p className="hint">Checkpoint changes affect future coach runs only. Review the rollouts and safety stops before any robot motion.</p>
      <p className="hint">Auto promotion for this comparison: {selected.auto_promote ? 'on' : 'off'}. It only changes the checkpoint used by future coach runs after an improved verdict; it never starts robot motion.</p>
    </section>}

    {selected && nextTrial && <section className="card evaluation-next">
      <p className="eyebrow">Trial {(nextTrial.sequence_index ?? 0) + 1} of {trials.length}</p>
      <h2>Scene {(nextTrial.scene_index ?? 0) + 1} · cell {nextTrial.start_cell + 1}</h2>
      <p>{nextTrial.setup_note}</p>
      <p><strong>Checkpoint:</strong> {nextTrial.checkpoint === selected.baseline_checkpoint ? 'Baseline' : 'Candidate'} · {nextTrial.checkpoint}</p>
      <p><strong>Status:</strong> {nextTrial.status.replaceAll('_', ' ')}</p>
      {nextTrial.last_error && <p className="trial-error">{nextTrial.last_error}</p>}
      <div className="trial-actions">
        {nextTrial.status === 'planned' && <button disabled={busy} onClick={() => trialAction(nextTrial, 'start')}>Start supervised run</button>}
        {nextTrial.status === 'starting' && <button disabled={busy} onClick={() => trialAction(nextTrial, 'reconcile')}>Check station</button>}
        {nextTrial.status === 'running' && <><button disabled={busy} onClick={() => trialAction(nextTrial, 'stop')}>Stop robot</button><button className="secondary" disabled={busy} onClick={() => trialAction(nextTrial, 'sync')}>Sync if ended</button></>}
        {nextTrial.status === 'awaiting_rollout' && <><button disabled={busy} onClick={() => trialAction(nextTrial, 'sync')}>Find rollout</button><button className="secondary" disabled={busy} onClick={() => abandon(nextTrial)}>Mark unusable</button></>}
      </div>
      {nextTrial.status === 'awaiting_label' && <div className="label-form trial-label">
        {nextTrial.episode_id && <a href={`/api/episodes/${nextTrial.episode_id}`} target="_blank" rel="noreferrer">Open rollout details</a>}
        <label>Outcome<select value={outcome} onChange={(event) => setOutcome(event.target.value as 'success' | 'failure')}><option value="success">Success</option><option value="failure">Failure</option></select></label>
        {outcome === 'failure' && <label>Failure stage<select value={stage} onChange={(event) => setStage(event.target.value)}><option value="">Unknown</option><option value="approach">Approach</option><option value="grasp">Grasp</option><option value="transport">Transport</option><option value="release">Release</option><option value="other">Other</option></select></label>}
        <label>Note<textarea maxLength={2000} value={note} onChange={(event) => setNote(event.target.value)} /></label>
        <button disabled={busy} onClick={() => label(nextTrial)}>Save outcome</button>
      </div>}
    </section>}
    {selected && trials.length > 0 && !nextTrial && <section className="card"><h2>{unusable ? 'This comparison has an unusable run' : 'All planned runs are finished'}</h2><p>{unusable ? 'Plan a fresh comparison with the same fine-tune. The incomplete result stays in the record.' : 'Read the verdict above before deciding whether to deploy the candidate.'}</p></section>}
  </main>;
}
