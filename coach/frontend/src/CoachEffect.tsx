import { useEffect, useState } from 'react';
import repairStudy from '../../experiments/yam_sim_faas/closed_loop_repair_report.json';
import confirmationStudy from '../../experiments/yam_sim_faas/horizon_confirmation_report.json';

type Snapshot = { plan: object; outcomes: object[] };
type Arm = { participants: number; validated_by_horizon: number; validation_rate: number;
  mean_restricted_minutes: number; mean_demos_recorded: number; mean_faas_jobs: number;
  mean_faas_steps: number; mean_operator_minutes: number; mean_faas_cost_usd: number | null };
type Report = { study_id: string; data_kind: 'synthetic' | 'observed'; horizon_minutes: number;
  standard: Arm; coach: Arm; snapshot_sha256: string; warnings: string[];
  coach_minus_standard_validation_rate: number; coach_minus_standard_mean_restricted_minutes: number;
  coach_minus_standard_mean_demos: number; coach_minus_standard_mean_faas_jobs: number;
  coach_minus_standard_mean_faas_steps: number; coach_minus_standard_mean_operator_minutes: number;
  coach_minus_standard_mean_faas_cost_usd: number | null; fisher_two_sided_p: number };
type Task = { id: string; name: string };
type Footprint = { task_id: string; baseline_trials: number; repair_trials: number;
  demos_imported: number; demos_kept: number; faas_jobs_submitted: number;
  faas_steps_submitted: number; evaluations_planned: number; validated_improvements: number;
  notes: string[] };

const fmt = (value: number | null, suffix = '') => value === null ? 'Unknown' : `${value.toFixed(1)}${suffix}`;

export default function CoachEffect() {
  const [plan, setPlan] = useState('');
  const [outcomes, setOutcomes] = useState('');
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskId, setTaskId] = useState('');
  const [local, setLocal] = useState<Footprint | null>(null);

  useEffect(() => {
    void fetch('/api/tasks').then(async (response) => response.json() as Promise<Task[]>).then((items) => {
      setTasks(items); setTaskId((current) => current || items[0]?.id || '');
    }).catch(() => setTasks([]));
  }, []);
  useEffect(() => {
    if (!taskId) { setLocal(null); return; }
    void fetch(`/api/tasks/${taskId}/footprint`).then(async (response) => {
      if (!response.ok) throw new Error('Could not load local counts.');
      return response.json() as Promise<Footprint>;
    }).then(setLocal).catch(() => setLocal(null));
  }, [taskId]);

  async function example() {
    setBusy(true); setError(''); setReport(null);
    try {
      const response = await fetch('/api/coach-effect/synthetic-example');
      if (!response.ok) throw new Error(`Could not load example (${response.status}).`);
      const value = (await response.json()) as Snapshot;
      setPlan(JSON.stringify(value.plan, null, 2));
      setOutcomes(JSON.stringify(value.outcomes, null, 2));
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not load example.'); }
    finally { setBusy(false); }
  }

  async function analyze() {
    setBusy(true); setError(''); setReport(null);
    try {
      const payload: Snapshot = { plan: JSON.parse(plan) as object, outcomes: JSON.parse(outcomes) as object[] };
      const response = await fetch('/api/coach-effect/analyze', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      const value = await response.json() as Report & { detail?: string };
      if (!response.ok) throw new Error(value.detail ?? `Analysis failed (${response.status}).`);
      setReport(value);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not analyze study.'); }
    finally { setBusy(false); }
  }

  const rows: [string, number | null, number | null, number | null, string][] = report ? [
    ['Validated by horizon', report.standard.validation_rate * 100, report.coach.validation_rate * 100, report.coach_minus_standard_validation_rate * 100, '%'],
    ['Restricted time to validation', report.standard.mean_restricted_minutes, report.coach.mean_restricted_minutes, report.coach_minus_standard_mean_restricted_minutes, ' min'],
    ['Demos recorded', report.standard.mean_demos_recorded, report.coach.mean_demos_recorded, report.coach_minus_standard_mean_demos, ''],
    ['FaaS jobs', report.standard.mean_faas_jobs, report.coach.mean_faas_jobs, report.coach_minus_standard_mean_faas_jobs, ''],
    ['FaaS steps', report.standard.mean_faas_steps, report.coach.mean_faas_steps, report.coach_minus_standard_mean_faas_steps, ''],
    ['Operator time', report.standard.mean_operator_minutes, report.coach.mean_operator_minutes, report.coach_minus_standard_mean_operator_minutes, ' min'],
    ['Actual FaaS bill', report.standard.mean_faas_cost_usd, report.coach.mean_faas_cost_usd, report.coach_minus_standard_mean_faas_cost_usd, ' USD'],
  ] : [];

  return <main className="page">
    <header className="header"><div><p className="eyebrow">Operator study</p><h1>Does the coach save work?</h1><p className="subtitle">Compare real operator sessions against the ordinary workflow on one frozen task and time horizon.</p></div></header>
    <section className="card"><h2>Evidence needed</h2><p>Randomize operators before starting, use the same robot, task, budget, and held-out success rule, then count every assigned operator. Record demos, FaaS jobs and steps, operator minutes, and the actual bill when available. Validate successful outcomes with independent evaluation reports.</p><p>The operator-study example is <strong>synthetic</strong>. The observed simulator result below measures one evaluation decision; it provides no observed time, demo, or FaaS-spend savings.</p><button className="secondary" disabled={busy} onClick={() => void example()}>Load synthetic example</button></section>
    <section className="card"><p className="eyebrow">Observed simulator diagnostic</p><h2>Did the evaluation stop too early?</h2><p>We tested the same completed fine-tune on eight new apple scenes using the original nine-request limit and the coach’s twelve-request limit. All sixteen runs were saved and passed action replay.</p><div className="evaluation-metrics"><div><strong>{repairStudy.conditions.original_short.successes}/{repairStudy.conditions.original_short.valid}</strong><span>original limit</span></div><div><strong>{repairStudy.conditions.coach_extended.successes}/{repairStudy.conditions.coach_extended.valid}</strong><span>extended limit</span></div><div><strong>{repairStudy.coach_only_successes}</strong><span>scene passed only with extension</span></div></div><p>On scene 916, the extended trace first met the two-second lift rule during request 10. No new FaaS job was submitted. Twelve requests execute 33% more action rows than nine, and this eight-scene result does not measure operator time or financial savings.</p><div className="audit-table-wrap"><table className="audit-table"><thead><tr><th>Scene seed</th><th>Nine requests</th><th>Twelve requests</th></tr></thead><tbody>{repairStudy.pairs.map((pair) => <tr key={pair.seed}><td>{pair.seed}</td><td>{pair.original_short_success ? 'Pass' : 'Fail'}</td><td>{pair.coach_extended_success ? 'Pass' : 'Fail'}</td></tr>)}</tbody></table></div><p>Frozen-plan SHA-256: <code>{repairStudy.plan_sha256}</code>.</p><button className="secondary" onClick={() => { const url = URL.createObjectURL(new Blob([JSON.stringify(repairStudy, null, 2)], { type: 'application/json' })); const link = document.createElement('a'); link.href = url; link.download = 'closed-loop-repair-report.json'; link.click(); URL.revokeObjectURL(url); }}>Download measured report</button></section>
    <section className="card"><p className="eyebrow">Fresh confirmation · same trajectory</p><h2>How often did the extra horizon matter?</h2><p>A separate frozen plan tested twenty new scenes. We scored each saved twelve-request trajectory again at its nine-request prefix, so both scores use the same model actions up to that cutoff.</p><div className="evaluation-metrics"><div><strong>{confirmationStudy.prefix_9_successes}/{confirmationStudy.valid_trials}</strong><span>passed by request 9</span></div><div><strong>{confirmationStudy.full_12_successes}/{confirmationStudy.valid_trials}</strong><span>passed by request 12</span></div><div><strong>{confirmationStudy.extra_requests_needed}</strong><span>needed request 10 or 11</span></div></div><p><strong>Coach decision:</strong> test the unchanged checkpoint with enough execution time before collecting new demos or paying for another fine-tune. One of {confirmationStudy.planned_trials} attempts was invalid after a Dream episode restart and remains in the report. This simulator comparison does not measure saved operator time, demonstrations, or FaaS dollars.</p><details><summary>Inspect the scenes needing extra time and the invalid attempt</summary><div className="audit-table-wrap"><table className="audit-table"><thead><tr><th>Scene seed</th><th>Nine-request prefix</th><th>First successful request</th><th>Evidence</th></tr></thead><tbody>{confirmationStudy.trials.filter((trial) => !trial.valid || !trial.prefix_success).map((trial) => <tr key={trial.seed}><td>{trial.seed}</td><td>{trial.valid ? 'Failed' : 'Invalid'}</td><td>{trial.earliest_success_request ?? '—'}</td><td>{trial.reason}</td></tr>)}</tbody></table></div></details><p>Frozen-plan SHA-256: <code>{confirmationStudy.plan_sha256}</code>.</p><button className="secondary" onClick={() => { const url = URL.createObjectURL(new Blob([JSON.stringify(confirmationStudy, null, 2)], { type: 'application/json' })); const link = document.createElement('a'); link.href = url; link.download = 'horizon-confirmation-report.json'; link.click(); URL.revokeObjectURL(url); }}>Download confirmation report</button></section>
    <section className="card"><h2>Observed local task counts</h2>{tasks.length ? <label>Task<select value={taskId} onChange={(event) => setTaskId(event.target.value)}>{tasks.map((task) => <option key={task.id} value={task.id}>{task.name}</option>)}</select></label> : <p>No local task yet.</p>}{local && <><div className="evaluation-metrics"><div><strong>{local.baseline_trials}</strong><span>baseline trials</span></div><div><strong>{local.repair_trials}</strong><span>repair trials</span></div><div><strong>{local.demos_kept}/{local.demos_imported}</strong><span>kept/imported demos</span></div><div><strong>{local.faas_steps_submitted}</strong><span>submitted FaaS steps</span></div></div><p>{local.faas_jobs_submitted} submitted jobs · {local.evaluations_planned} planned evaluations · {local.validated_improvements} validated improvements.</p><ul>{local.notes.map((note) => <li key={note}>{note}</li>)}</ul></>}</section>
    <section className="card"><h2>Analyze a fixed-horizon study</h2><label className="audit-file">Frozen plan JSON<input type="file" accept=".json,application/json" onChange={async (event) => { const file = event.target.files?.[0]; if (file) { setPlan(await file.text()); setReport(null); } }} /><textarea value={plan} onChange={(event) => { setPlan(event.target.value); setReport(null); }} spellCheck={false} /></label><label className="audit-file">All participant outcomes JSON<input type="file" accept=".json,application/json" onChange={async (event) => { const file = event.target.files?.[0]; if (file) { setOutcomes(await file.text()); setReport(null); } }} /><textarea value={outcomes} onChange={(event) => { setOutcomes(event.target.value); setReport(null); }} spellCheck={false} /></label><button disabled={busy || !plan.trim() || !outcomes.trim()} onClick={() => void analyze()}>{busy ? 'Checking…' : 'Analyze operator study'}</button></section>
    {error && <div className="alert" role="alert">{error}</div>}
    {report && <section className="card evaluation-report" aria-live="polite"><p className="eyebrow">{report.data_kind === 'synthetic' ? 'Synthetic demonstration — no measured savings' : 'Operator-reported study — verify source logs'}</p><h2>{report.study_id}</h2><p>{report.coach.validated_by_horizon}/{report.coach.participants} coach operators versus {report.standard.validated_by_horizon}/{report.standard.participants} standard operators reached validation within {report.horizon_minutes} minutes.</p><div className="audit-table-wrap"><table className="audit-table"><thead><tr><th>Outcome per operator</th><th>Standard</th><th>Coach</th><th>Coach − standard</th></tr></thead><tbody>{rows.map(([label, standard, coached, delta, suffix]) => <tr key={label}><td>{label}</td><td>{fmt(standard, suffix)}</td><td>{fmt(coached, suffix)}</td><td>{fmt(delta, suffix)}</td></tr>)}</tbody></table></div><p>Two-sided Fisher p-value for validation: {report.fisher_two_sided_p.toFixed(3)}. Snapshot SHA-256: <code>{report.snapshot_sha256}</code>.</p><ul>{report.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul><button className="secondary" onClick={() => { const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })); const link = document.createElement('a'); link.href = url; link.download = 'coach-effect-report.json'; link.click(); URL.revokeObjectURL(url); }}>Download report JSON</button></section>}
  </main>;
}
