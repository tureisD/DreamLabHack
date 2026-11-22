import { useCallback, useEffect, useState } from 'react';

type Task = { id: string; name: string; success_rule: string; baseline_checkpoint: string };
type Job = { id: string; status: string; checkpoint: string | null };
export type Evaluation = {
  id: string; task_id: string; fine_tune_job_id: string; baseline_checkpoint: string;
  candidate_checkpoint: string; minimum_effect: number; created_at: string;
  planned_pairs: number;
};
type Deployment = { checkpoint: string; baseline_checkpoint: string };
type Trial = {
  id: string; status: string; checkpoint: string; scene_index: number;
  sequence_index: number; start_cell: number; setup_note: string;
  episode_id: string | null; last_error: string | null;
};
export type Report = {
  usable_pairs: number; target_pairs: number; baseline_successes: number; candidate_successes: number;
  baseline_reviewed: number; candidate_reviewed: number;
  baseline_only: number; candidate_only: number; paired_difference: number | null;
  ci_low: number | null; ci_high: number | null; exact_p_value: number | null;
  baseline_safety_stops: number; candidate_safety_stops: number;
  decision: 'improved' | 'inconclusive' | 'worse' | 'not_evaluable'; reason: string;
  problems?: string[]; warnings?: string[]; observed_difference?: number | null;
  difference_interval?: [number, number] | null; input_sha256?: string;
  baseline_interventions?: number; candidate_interventions?: number;
  baseline_mean_duration_s?: number | null; candidate_mean_duration_s?: number | null;
  baseline_mean_first_response_s?: number | null; candidate_mean_first_response_s?: number | null;
};
type PairPlan = {
  required_pairs: number | null; feasible: boolean; recommended_pairs: number | null;
  estimated_robot_hours: number | null; explanation: string;
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

export default function EvaluationPage({ initialTaskId = '', initialEvaluationId = '' }: {
  initialTaskId?: string;
  initialEvaluationId?: string;
}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskId, setTaskId] = useState('');
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobId, setJobId] = useState('');
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [selectedId, setSelectedId] = useState(initialEvaluationId);
  const [trials, setTrials] = useState<Trial[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [minimumEffect, setMinimumEffect] = useState(0.15);
  const [plannedPairs, setPlannedPairs] = useState(30);
  const [expectedGain, setExpectedGain] = useState(0.6);
  const [maxPairs, setMaxPairs] = useState(100);
  const [minutesPerPair, setMinutesPerPair] = useState(12);
  const [pairPlan, setPairPlan] = useState<PairPlan | null>(null);
  const [deployment, setDeployment] = useState<Deployment | null>(null);
  const [sceneAdapter, setSceneAdapter] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [outcome, setOutcome] = useState<'success' | 'failure'>('success');
  const [stage, setStage] = useState('');
  const [note, setNote] = useState('');
  const [reviewerId, setReviewerId] = useState('');
  const [heldoutAttested, setHeldoutAttested] = useState(false);
  const [resetsAttested, setResetsAttested] = useState(false);
  const [auditDecision, setAuditDecision] = useState('');
  const [interventions, setInterventions] = useState(0);
  const [firstResponseS, setFirstResponseS] = useState('');

  useEffect(() => {
    setAuditDecision('');
    setHeldoutAttested(false);
    setResetsAttested(false);
  }, [selectedId]);

  useEffect(() => {
    void json<Task[]>('/api/tasks').then((values) => {
      setTasks(values);
      setTaskId(values.find((task) => task.id === initialTaskId)?.id ?? values[0]?.id ?? '');
    }).catch((caught: Error) => setError(caught.message));
    void json<{ configured: boolean }>('/api/scene-adapter/status').then((value) => setSceneAdapter(value.configured));
  }, [initialTaskId]);

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
        fine_tune_job_id: jobId, minimum_effect: minimumEffect, planned_pairs: plannedPairs,
      });
      setEvaluations(await json<Evaluation[]>(`/api/tasks/${taskId}/evaluations`));
      setSelectedId(result.id);
      setMessage('Evaluation planned. Follow the displayed scene order and reset the setup between runs.');
    });
  }

  function planPairs() {
    void act(async () => {
      const value = await json<PairPlan>('/api/paired-evaluations/plan', 'POST', {
        expected_gain: expectedGain, minimum_improvement: minimumEffect,
        max_pairs: maxPairs, minutes_per_pair: minutesPerPair,
      });
      setPairPlan(value);
      if (value.recommended_pairs !== null) setPlannedPairs(value.recommended_pairs);
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

  function prepare(trial: Trial) {
    if (!window.confirm(`Move the scene fixture to place object for scene ${(trial.scene_index ?? 0) + 1}? Keep the robot workspace clear.`)) return;
    void act(async () => {
      const result = await json<{ detail: string }>(`/api/trials/${trial.id}/prepare-scene`, 'POST');
      setMessage(result.detail);
    });
  }

  function label(trial: Trial) {
    if (!selectedId) return;
    void act(async () => {
      await json<Trial>(`/api/trials/${trial.id}/label`, 'POST', {
        success: outcome === 'success', failure_stage: outcome === 'failure' && stage ? stage : null,
        note: note.trim() || null,
        reviewer_id: reviewerId.trim(),
        interventions,
        first_response_s: firstResponseS.trim() ? Number(firstResponseS) : null,
      });
      await refreshEvaluation(selectedId);
      setOutcome('success'); setStage(''); setNote(''); setInterventions(0); setFirstResponseS('');
      setMessage('Outcome saved. Reset the scene for the next run.');
    });
  }

  function auditSnapshot() {
    if (!selectedId) return;
    void act(async () => {
      const snapshot = await json<unknown>(`/api/evaluations/${selectedId}/paired-snapshot`, 'POST', {
        heldout_attested: heldoutAttested, resets_attested: resetsAttested,
      });
      const audit = await json<{ decision: string; problems: string[]; usable_pairs: number }>(
        `/api/evaluations/${selectedId}/audit`, 'GET',
      );
      setAuditDecision(`${audit.decision}: ${audit.usable_pairs}/${selected?.planned_pairs ?? plannedPairs} usable pairs${audit.problems.length ? `; ${audit.problems.join(' ')}` : ''}`);
      await refreshEvaluation(selectedId);
      const url = URL.createObjectURL(new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' }));
      const link = document.createElement('a');
      link.href = url; link.download = `paired-evaluation-${selectedId}.json`; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage('The reviewed audit is saved and its evidence snapshot has been downloaded.');
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
    <header className="header"><div><p className="eyebrow">Before and after</p><h1>Evaluate the fine-tune</h1><p className="subtitle">Plan matched held-out scenes, review every outcome, then audit the candidate against the base.</p></div></header>
    {error && <div className="alert" role="alert">{error}</div>}
    {message && <div className="notice" role="status">{message}</div>}
    <section className="card evaluation-workflow" aria-label="Evaluation steps">
      <span>1 · Plan scenes</span><span>2 · Run both models</span><span>3 · Review rollouts</span><span>4 · Audit and decide</span>
    </section>
    <section className="card">
      <h2>Choose the trial budget</h2>
      <p>Estimate how many matched scenes could clear your minimum useful gain under the conservative paired rule. The expected gain is an assumption, not a measurement.</p>
      <div className="training-controls">
        <label>Expected gain (%)<input type="number" min={0} max={100} step={5} value={Math.round(expectedGain * 100)} onChange={(event) => { setExpectedGain(Number(event.target.value) / 100); setPairPlan(null); }} /></label>
        <label>Minimum useful gain (%)<input type="number" min={0} max={99} step={1} value={Math.round(minimumEffect * 100)} onChange={(event) => { setMinimumEffect(Number(event.target.value) / 100); setPairPlan(null); }} /></label>
        <label>Maximum pairs<input type="number" min={1} max={512} step={1} value={maxPairs} onChange={(event) => { setMaxPairs(Number(event.target.value)); setPairPlan(null); }} /></label>
        <label>Minutes per pair<input type="number" min={1} max={1000} step={1} value={minutesPerPair} onChange={(event) => { setMinutesPerPair(Number(event.target.value)); setPairPlan(null); }} /></label>
        <button disabled={busy || !Number.isFinite(expectedGain) || expectedGain <= minimumEffect || expectedGain > 1 || !Number.isInteger(maxPairs) || maxPairs < 1 || maxPairs > 512 || !Number.isFinite(minutesPerPair) || minutesPerPair <= 0} onClick={planPairs}>Estimate pairs</button>
      </div>
      {pairPlan && <div className={pairPlan.feasible ? 'notice' : 'alert'} role="status">
        <strong>{pairPlan.feasible ? `${pairPlan.recommended_pairs} pairs recommended` : 'Budget may be too small'}</strong>
        <p>{pairPlan.explanation} {pairPlan.estimated_robot_hours !== null && `About ${pairPlan.estimated_robot_hours.toFixed(1)} robot hours at your timing assumption.`}</p>
      </div>}
    </section>
    <section className="card">
      <div className="training-controls">
        <label>Task<select value={taskId} onChange={(event) => { setTaskId(event.target.value); setSelectedId(''); }}><option value="">Choose a task</option>{tasks.map((value) => <option key={value.id} value={value.id}>{value.name}</option>)}</select></label>
        <label>Fine-tuned checkpoint<select value={jobId} onChange={(event) => setJobId(event.target.value)}><option value="">Choose a completed job</option>{candidates.map((job) => <option key={job.id} value={job.id}>{job.checkpoint}</option>)}</select></label>
        <label>Planned scene pairs<input type="number" min="1" max="512" step="1" value={plannedPairs} onChange={(event) => setPlannedPairs(Number(event.target.value))} /></label>
        <button disabled={busy || !taskId || !jobId || !Number.isFinite(minimumEffect) || minimumEffect < 0 || minimumEffect >= 1 || !Number.isInteger(plannedPairs) || plannedPairs < 1 || plannedPairs > 512} onClick={create}>Freeze comparison plan</button>
      </div>
      <p className="hint">The scene count and gain threshold are fixed when you create the comparison. Use the same object, lighting, and success rule for both models in a pair. Keep these scenes out of training. The estimate does not guarantee statistical power.</p>
      {task && <p><strong>Success rule:</strong> {task.success_rule}</p>}
      {deployment && <p><strong>Checkpoint for future task runs:</strong> {deployment.checkpoint} {deployment.checkpoint !== deployment.baseline_checkpoint && <button className="secondary" disabled={busy} onClick={rollback}>Roll back to baseline</button>}</p>}
      {evaluations.length > 0 && <label className="evaluation-select">Comparison<select value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>{evaluations.map((item) => <option key={item.id} value={item.id}>{item.candidate_checkpoint} · {item.created_at}</option>)}</select></label>}
    </section>

    {selected && report && <section className="card evaluation-report">
      <h2>Audited verdict: {report.decision.replace('_', ' ')}</h2>
      <p>{report.reason}</p>
      <div className="evaluation-metrics">
        <div><strong>{report.usable_pairs}/{report.target_pairs}</strong><span>usable pairs</span></div>
        <div><strong>{report.baseline_successes}/{report.usable_pairs}</strong><span>baseline successes</span></div>
        <div><strong>{report.candidate_successes}/{report.usable_pairs}</strong><span>candidate successes</span></div>
        <div><strong>{percent(report.observed_difference ?? report.paired_difference)}</strong><span>paired gain</span></div>
      </div>
      <p className="hint">Conservative paired interval: {percent(report.difference_interval?.[0] ?? report.ci_low)} to {percent(report.difference_interval?.[1] ?? report.ci_high)}. Candidate-only wins: {report.candidate_only}; baseline-only wins: {report.baseline_only}. Safety stops: {report.baseline_safety_stops} baseline, {report.candidate_safety_stops} candidate.</p>
      <div className="evaluation-secondary-metrics">
        <div><strong>Human interventions</strong><span>Base {report.baseline_interventions ?? '—'} · candidate {report.candidate_interventions ?? '—'}</span></div>
        <div><strong>Mean run duration</strong><span>Base {report.baseline_mean_duration_s?.toFixed(1) ?? '—'}s · candidate {report.candidate_mean_duration_s?.toFixed(1) ?? '—'}s</span></div>
        <div><strong>Mean first response</strong><span>Base {report.baseline_mean_first_response_s?.toFixed(1) ?? '—'}s · candidate {report.candidate_mean_first_response_s?.toFixed(1) ?? '—'}s</span></div>
      </div>
      {report.problems && report.problems.length > 0 && <div className="alert"><strong>Evidence needed</strong><ul>{report.problems.map((problem) => <li key={problem}>{problem}</li>)}</ul></div>}
      {report.warnings && report.warnings.length > 0 && <details><summary>Audit limits</summary><ul>{report.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></details>}
      {report.input_sha256 && <p className="hint">Evidence checksum: <code>{report.input_sha256}</code></p>}
      {report.decision === 'improved' && deployment?.checkpoint !== selected.candidate_checkpoint && <button disabled={busy} onClick={promote}>Use verified candidate</button>}
      <p className="hint">Checkpoint changes affect future coach runs only. Review the rollouts and safety stops before any robot motion.</p>
      <p className="hint">A completed audit is required before checkpoint promotion. Promotion affects future coach task runs only and never starts robot motion.</p>
    </section>}

    {selected && <section className="card">
      <h2>Paired statistical audit</h2>
      <p>Save the authoritative statistical check. Older labels without a reviewer and unfinished scenes remain in the snapshot but cannot earn an improvement verdict.</p>
      <label><input type="checkbox" checked={heldoutAttested} onChange={(event) => setHeldoutAttested(event.target.checked)} /> I checked that these scenes were kept out of training.</label>
      <label><input type="checkbox" checked={resetsAttested} onChange={(event) => setResetsAttested(event.target.checked)} /> I checked that the scene was reset between runs.</label>
      <button disabled={busy || !heldoutAttested || !resetsAttested} onClick={auditSnapshot}>Save audit and download evidence</button>
      {auditDecision && <p role="status">{auditDecision}</p>}
    </section>}

    {selected && nextTrial && <section className="card evaluation-next">
      <p className="eyebrow">Trial {(nextTrial.sequence_index ?? 0) + 1} of {trials.length}</p>
      <h2>Scene {(nextTrial.scene_index ?? 0) + 1} · cell {nextTrial.start_cell + 1}</h2>
      <p>{nextTrial.setup_note}</p>
      <p><strong>Checkpoint:</strong> {nextTrial.checkpoint === selected.baseline_checkpoint ? 'Baseline' : 'Candidate'} · {nextTrial.checkpoint}</p>
      <p><strong>Status:</strong> {nextTrial.status.replaceAll('_', ' ')}</p>
      {nextTrial.last_error && <p className="trial-error">{nextTrial.last_error}</p>}
      <div className="trial-actions">
        {nextTrial.status === 'planned' && sceneAdapter && <button className="secondary" disabled={busy} onClick={() => prepare(nextTrial)}>Place scene with fixture</button>}
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
        <label>Reviewer name or ID<input maxLength={120} value={reviewerId} onChange={(event) => setReviewerId(event.target.value)} /></label>
        <label>Human interventions<input type="number" min={0} max={999} step={1} value={interventions} onChange={(event) => setInterventions(Number(event.target.value))} /></label>
        <label>Time to first model response (seconds, if measured)<input type="number" min={0} step="0.1" value={firstResponseS} onChange={(event) => setFirstResponseS(event.target.value)} placeholder="Optional" /></label>
        <button disabled={busy || !reviewerId.trim() || !Number.isInteger(interventions) || interventions < 0 || (firstResponseS.trim() !== '' && (!Number.isFinite(Number(firstResponseS)) || Number(firstResponseS) < 0))} onClick={() => label(nextTrial)}>Save outcome</button>
      </div>}
    </section>}
    {selected && trials.length > 0 && !nextTrial && <section className="card"><h2>{unusable ? 'This comparison has an unusable run' : 'All planned runs are finished'}</h2><p>{unusable ? 'Plan a fresh comparison with the same fine-tune. The incomplete result stays in the record.' : 'Read the verdict above before deciding whether to deploy the candidate.'}</p></section>}
  </main>;
}
