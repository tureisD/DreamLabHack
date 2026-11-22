import { useEffect, useState } from 'react';
import { screenHref } from './workspaceRoute';

type Task = { id: string; name: string };
type Guidance = {
  phase: string; headline: string; next_action: string; evidence: string[];
  target_screen: string; pilot_ready: boolean;
  suggested_recipe: { steps: number; lr_schedule: string; base_share: number } | null;
};
type WorkflowFinding = { id: string; episode_id: string; message: string; reason: string | null; reviewed_at: string | null };
type Diagnosis = {
  setup_count: number; data_count: number; unknown_count: number; failure_stages: Record<string, number>;
  recommendation: string; findings?: WorkflowFinding[]; open_finding_count?: number;
};
type Consistency = { threshold: number | null; scored_runs: number; successful_calibration_runs: number; alerts: number; labelled_failures_alerted: number; labelled_successes_alerted: number };

async function json<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    const detail = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail ?? `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export default function Guide({ onRepair, initialTaskId = '' }: { onRepair: () => void; initialTaskId?: string }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskId, setTaskId] = useState('');
  const [guidance, setGuidance] = useState<Guidance | null>(null);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [consistency, setConsistency] = useState<Consistency | null>(null);
  const [error, setError] = useState('');
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [reviewing, setReviewing] = useState(false);
  const [reviewError, setReviewError] = useState('');
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    void json<Task[]>('/api/tasks').then((values) => {
      setTasks(values);
      setTaskId(values.find((task) => task.id === initialTaskId)?.id ?? values[0]?.id ?? '');
    }).catch((caught: Error) => setError(caught.message));
  }, [initialTaskId]);

  useEffect(() => {
    setDiagnosis(null);
    if (!taskId) { setGuidance(null); return; }
    let active = true;
    const refresh = async () => {
      try {
        const [value, causes, signals] = await Promise.all([
          json<Guidance>(`/api/tasks/${taskId}/guidance`),
          json<Diagnosis>(`/api/tasks/${taskId}/diagnosis`),
          json<Consistency>(`/api/tasks/${taskId}/consistency`),
        ]);
        if (active) { setGuidance(value); setDiagnosis(causes); setConsistency(signals); setError(''); }
      } catch (caught) { if (active) setError(caught instanceof Error ? caught.message : 'Could not load task guidance.'); }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [taskId, revision]);

  async function acknowledge(finding: WorkflowFinding) {
    const reason = reasons[finding.id]?.trim();
    if (!taskId || !reason || reviewing) return;
    setReviewing(true);
    setReviewError('');
    try {
      const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/findings/${encodeURIComponent(finding.id)}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      });
      if (!response.ok) throw new Error('Could not save the review. Your note is still here.');
      setRevision((value) => value + 1);
    } catch (caught) {
      setReviewError(caught instanceof Error ? caught.message : 'Could not save the review.');
    } finally {
      setReviewing(false);
    }
  }

  return <main className="page">
    <header className="header"><div><p className="eyebrow">Task coach</p><h1>What should I do next?</h1><p className="subtitle">The next step comes from your labelled runs, accepted demos, and Dream job status.</p></div></header>
    {error && <div className="alert" role="alert">{error}</div>}
    {tasks.length === 0 ? <section className="card"><h2>Create a task to begin</h2><p>Open Tasks, define the robot instruction and success rule, then run the baseline checkpoint.</p></section> : <>
      <section className="card training-controls"><label>Task<select value={taskId} onChange={(event) => setTaskId(event.target.value)}>{tasks.map((task) => <option key={task.id} value={task.id}>{task.name}</option>)}</select></label></section>
      {guidance && <section className="card guide-card">
        <p className="eyebrow">{guidance.phase}</p>
        <h2>{guidance.headline}</h2>
        <p className="guide-action">{guidance.next_action}</p>
        <p><strong>Open:</strong> {guidance.target_screen === 'runs' ? 'Run review' : guidance.target_screen[0].toUpperCase() + guidance.target_screen.slice(1)} tab. Select this task there.</p>
        {guidance.target_screen === 'repair' && <button onClick={onRepair}>Open repair comparison</button>}
        <h3>What this is based on</h3>
        <ul>{guidance.evidence.map((item, index) => <li key={index}>{item}</li>)}</ul>
        {guidance.pilot_ready && <p className="notice">Ready to try an initial pilot, subject to Dream dataset validation. This is a coverage signal, not a predicted success rate.</p>}
        {guidance.suggested_recipe && <p className="hint">Suggested first recipe: {guidance.suggested_recipe.steps} steps, {guidance.suggested_recipe.lr_schedule} schedule, base share {guidance.suggested_recipe.base_share}. Review and edit it in Training before paid submission.</p>}
      </section>}
      {diagnosis && <section className="card guide-card"><h2>Why runs fail</h2><p>{diagnosis.setup_count} station or recording issues · {diagnosis.data_count} confirmed task failures without a logged station fault · {diagnosis.unknown_count} other runs.</p><p>{diagnosis.recommendation}</p>{Object.entries(diagnosis.failure_stages).length > 0 && <p><strong>Human-labelled failure stages:</strong> {Object.entries(diagnosis.failure_stages).map(([name, count]) => `${name} ${count}`).join(' · ')}</p>}<p className="hint">These are evidence categories, not a proof of root cause. Review the rollout before acting.</p></section>}
      {diagnosis?.findings?.length ? <section className="card guide-card">
        <h2>Recording issues</h2>
        <p>{diagnosis.open_finding_count ?? 0} awaiting review</p>
        {reviewError && <p role="alert" className="alert">{reviewError}</p>}
        {diagnosis.findings.map((finding) => <div className="finding" key={finding.id}>
          <a href={screenHref('runs', { task: taskId, run: finding.episode_id })}>{finding.message}</a>
          {finding.reviewed_at ? <p>Reviewed {new Date(finding.reviewed_at).toLocaleString()} · {finding.reason}</p>
            : <form className="label-form" onSubmit={(event) => { event.preventDefault(); void acknowledge(finding); }}>
              <label>Review notes<input required maxLength={1000} value={reasons[finding.id] ?? ''}
                onChange={(event) => setReasons((value) => ({ ...value, [finding.id]: event.target.value }))} /></label>
              <button disabled={reviewing || !reasons[finding.id]?.trim()}>Mark reviewed</button>
            </form>}
        </div>)}
      </section> : null}
      {consistency && <section className="card guide-card"><h2>Action consistency screen</h2><p>{consistency.scored_runs} runs scored from saved reply chunks. {consistency.threshold === null ? `Need at least 10 scored successful runs for a local threshold; ${consistency.successful_calibration_runs} available.` : `95th-percentile successful-run threshold: ${consistency.threshold.toFixed(2)}. ${consistency.alerts} alerts: ${consistency.labelled_failures_alerted} labelled failures, ${consistency.labelled_successes_alerted} labelled successes.`}</p><p className="hint">Offline screening only. The threshold is an empirical reference, not a proven 5% false-alarm bound; no robot run is stopped automatically.</p></section>}
    </>}
  </main>;
}
