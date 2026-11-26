import { useCallback, useEffect, useState } from 'react';
import { RolloutPreview } from './Runs';

type Task = { id: string; name: string; prompt: string; success_rule: string };
type Triage = { action: string; reason: string; evidence: string[] };
type Study = {
  id: string; kind: 'prompt' | 'setup'; candidate_prompt: string | null;
  setup_change: string | null; planned_pairs: number; minimum_gain: number; created_at: string;
};
type Trial = {
  id: string; status: string; checkpoint: string; repair_role: 'baseline' | 'candidate';
  sequence_index: number; scene_index: number; setup_note: string;
  prompt_override: string | null; episode_id: string | null; last_error: string | null;
};
type Report = {
  decision: 'use_fix' | 'consider_faas' | 'inconclusive' | 'not_evaluable';
  planned_pairs: number; usable_pairs: number; baseline_successes: number;
  candidate_successes: number; observed_gain: number | null;
  difference_interval: [number, number] | null; baseline_safety_stops: number;
  candidate_safety_stops: number; problems: string[]; recommendation: string;
  input_sha256: string;
};

async function json<T>(url: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method, headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function pct(value: number | null) { return value === null ? '—' : `${(value * 100).toFixed(1)}%`; }

export default function Repair({ onDemos, onTraining, initialTaskId = '', embedded = false }: {
  onDemos: (taskId: string) => void;
  onTraining: (taskId: string) => void;
  initialTaskId?: string;
  embedded?: boolean;
}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskId, setTaskId] = useState('');
  const [triage, setTriage] = useState<Triage | null>(null);
  const [studies, setStudies] = useState<Study[]>([]);
  const [studyId, setStudyId] = useState('');
  const [trials, setTrials] = useState<Trial[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [kind, setKind] = useState<'prompt' | 'setup'>('prompt');
  const [candidatePrompt, setCandidatePrompt] = useState('');
  const [setupChange, setSetupChange] = useState('');
  const [pairs, setPairs] = useState(12);
  const [gain, setGain] = useState(0.1);
  const [outcome, setOutcome] = useState<'success' | 'failure'>('success');
  const [reviewer, setReviewer] = useState('');
  const [note, setNote] = useState('');
  const [resetAttested, setResetAttested] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  useEffect(() => {
    void json<Task[]>('/api/tasks').then((values) => {
      setTasks(values); setTaskId(values.find((task) => task.id === initialTaskId)?.id ?? values[0]?.id ?? '');
    }).catch((caught: Error) => setError(caught.message));
  }, [initialTaskId]);

  useEffect(() => {
    if (!taskId) { setTriage(null); setStudies([]); setStudyId(''); return; }
    let active = true;
    const refresh = async () => {
      try {
        const [nextTriage, nextStudies] = await Promise.all([
          json<Triage>(`/api/tasks/${taskId}/repair/triage`),
          json<Study[]>(`/api/tasks/${taskId}/repair-studies`),
        ]);
        if (active) {
          setTriage(nextTriage); setStudies(nextStudies);
          setStudyId((current) => nextStudies.some((study) => study.id === current) ? current : (nextStudies[0]?.id ?? ''));
        }
      } catch (caught) { if (active) setError(caught instanceof Error ? caught.message : 'Could not load repair status.'); }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [taskId]);

  const refreshStudy = useCallback(async (id: string) => {
    const [nextTrials, nextReport] = await Promise.all([
      json<Trial[]>(`/api/repair-studies/${id}/trials`),
      json<Report>(`/api/repair-studies/${id}/report`),
    ]);
    setTrials(nextTrials); setReport(nextReport);
  }, []);

  useEffect(() => {
    setResetAttested(false);
    if (!studyId) { setTrials([]); setReport(null); return; }
    let active = true;
    const refresh = async () => {
      try { if (active) await refreshStudy(studyId); }
      catch (caught) { if (active) setError(caught instanceof Error ? caught.message : 'Could not load repair study.'); }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10000);
    return () => { active = false; window.clearInterval(timer); };
  }, [studyId, refreshStudy]);

  async function act(work: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('');
    try { await work(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Action failed.'); }
    finally { setBusy(false); }
  }

  function create() {
    if (!taskId) return;
    void act(async () => {
      const study = await json<Study>(`/api/tasks/${taskId}/repair-studies`, 'POST', {
        kind, candidate_prompt: kind === 'prompt' ? candidatePrompt.trim() : null,
        setup_change: kind === 'setup' ? setupChange.trim() : null,
        planned_pairs: pairs, minimum_gain: gain,
      });
      setStudies(await json<Study[]>(`/api/tasks/${taskId}/repair-studies`));
      setStudyId(study.id);
      setMessage('Matched diagnostic scenes are frozen. Reset the scene between runs.');
    });
  }

  function trialAction(trial: Trial, operation: 'start' | 'stop' | 'sync' | 'reconcile') {
    if (!studyId) return;
    if (operation === 'start' && !window.confirm(
      `Robot motion will start. ${trial.setup_note} Prompt: ${trial.prompt_override ?? task?.prompt}. Supervise the workspace. Continue?`,
    )) return;
    void act(async () => {
      const result = await json<Trial>(`/api/trials/${trial.id}/${operation}`, 'POST');
      await refreshStudy(studyId);
      setMessage(`Trial is ${result.status.replaceAll('_', ' ')}.`);
    });
  }

  function saveLabel(trial: Trial) {
    if (!studyId) return;
    void act(async () => {
      await json<Trial>(`/api/trials/${trial.id}/label`, 'POST', {
        success: outcome === 'success', failure_stage: null, note: note.trim() || null,
        reviewer_id: reviewer.trim(),
      });
      await refreshStudy(studyId);
      setOutcome('success'); setNote('');
      setMessage('Reviewed outcome saved. Reset the scene before the next trial.');
    });
  }

  function audit() {
    if (!studyId) return;
    void act(async () => {
      const result = await json<Report>(`/api/repair-studies/${studyId}/audit`, 'POST', {
        reset_attested: resetAttested,
      });
      setReport(result);
      setMessage('Repair comparison audited. The result will invalidate if evidence changes.');
    });
  }

  const task = tasks.find((value) => value.id === taskId);
  const study = studies.find((value) => value.id === studyId);
  const unusable = trials.some((trial) => trial.status === 'abandoned');
  const next = unusable ? undefined : trials.find((trial) => !['completed', 'abandoned'].includes(trial.status));

  const Container = embedded ? 'div' : 'main';
  return <Container className="page">
    <header className="header"><div>{!embedded && <><p className="eyebrow">Before paid training</p><h1>Repair the task first</h1></>}<p className="subtitle">Check the station, compare one cheap change on matched scenes, then decide whether demonstrations and FaaS are warranted.</p></div></header>
    {error && <div className="alert" role="alert">{error}</div>}
    {message && <div className="notice" role="status">{message}</div>}
    <section className="card training-controls"><label>Task<select value={taskId} onChange={(event) => { setTaskId(event.target.value); setStudyId(''); }}>{tasks.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>{task && <p><strong>Success rule:</strong> {task.success_rule}</p>}</section>
    {triage && <section className="card"><p className="eyebrow">Current decision · {triage.action.replaceAll('_', ' ')}</p><h2>{triage.reason}</h2><ul>{triage.evidence.map((item, index) => <li key={index}>{item}</li>)}</ul>{triage.action === 'collect_demos' && <button onClick={() => onDemos(taskId)}>Collect targeted demos</button>}{triage.action === 'use_fix' && <p className="notice">Keep this cheap change for further supervised testing. The task prompt itself is unchanged.</p>}</section>}
    <section className="card"><h2>Plan one cheap change</h2><p>Baseline and candidate use the same checkpoint and diagnostic scene. Change only the prompt or only the setup. The operator runs both trials and reviews outcomes.</p><div className="training-controls">
      <label>Change<select value={kind} onChange={(event) => setKind(event.target.value as 'prompt' | 'setup')}><option value="prompt">Prompt wording</option><option value="setup">Physical setup</option></select></label>
      {kind === 'prompt' ? <label>Candidate prompt<input maxLength={500} value={candidatePrompt} onChange={(event) => setCandidatePrompt(event.target.value)} placeholder={task?.prompt ?? 'New prompt'} /></label> : <label>One setup change<input maxLength={500} value={setupChange} onChange={(event) => setSetupChange(event.target.value)} placeholder="Example: move overhead camera" /></label>}
      <label>Matched scene pairs<input type="number" min={4} max={128} value={pairs} onChange={(event) => setPairs(Number(event.target.value))} /></label>
      <label>Minimum useful gain (%)<input type="number" min={0} max={99} value={Math.round(gain * 100)} onChange={(event) => setGain(Number(event.target.value) / 100)} /></label>
      <button disabled={busy || !taskId || !Number.isInteger(pairs) || pairs < 4 || pairs > 128 || gain < 0 || gain >= 1 || !(kind === 'prompt' ? candidatePrompt.trim() : setupChange.trim())} onClick={create}>Freeze repair comparison</button>
    </div><p className="hint">The station can change a prompt per run. Its action horizon is part of the model/config contract, so this page does not change it on a moving robot.</p></section>
    {studies.length > 0 && <section className="card"><label>Comparison<select value={studyId} onChange={(event) => setStudyId(event.target.value)}>{studies.map((item) => <option key={item.id} value={item.id}>{item.kind} · {item.created_at}</option>)}</select></label></section>}
    {study && report && <section className="card evaluation-report"><p className="eyebrow">Audited cheap-fix decision</p><h2>{report.decision.replaceAll('_', ' ')}</h2><p>{report.recommendation}</p><div className="evaluation-metrics"><div><strong>{report.usable_pairs}/{report.planned_pairs}</strong><span>usable pairs</span></div><div><strong>{report.baseline_successes}</strong><span>original successes</span></div><div><strong>{report.candidate_successes}</strong><span>changed successes</span></div><div><strong>{pct(report.observed_gain)}</strong><span>observed gain</span></div></div><p>Conservative gain interval: {pct(report.difference_interval?.[0] ?? null)} to {pct(report.difference_interval?.[1] ?? null)}. Safety stops: {report.baseline_safety_stops} original, {report.candidate_safety_stops} changed.</p>{report.problems.length > 0 && <div className="alert"><strong>Evidence needed</strong><ul>{report.problems.map((item) => <li key={item}>{item}</li>)}</ul></div>}<p className="hint">Evidence checksum: <code>{report.input_sha256}</code>. A result about this task does not establish safety or reliability in other setups.</p>{report.decision === 'consider_faas' && <div className="trial-actions"><button onClick={() => onDemos(taskId)}>Review demonstrations</button><button className="secondary" onClick={() => onTraining(taskId)}>Open FaaS</button></div>}</section>}
    {study && next && <section className="card evaluation-next"><p className="eyebrow">Trial {next.sequence_index + 1} of {trials.length}</p><h2>{next.repair_role === 'baseline' ? 'Original' : 'Cheap change'} · scene {next.scene_index + 1}</h2><p>{next.setup_note}</p><p><strong>Prompt:</strong> {next.prompt_override ?? task?.prompt}</p><p><strong>Status:</strong> {next.status.replaceAll('_', ' ')}</p>{next.last_error && <p className="trial-error">{next.last_error}</p>}<div className="trial-actions">{next.status === 'planned' && <button disabled={busy} onClick={() => trialAction(next, 'start')}>Start supervised run</button>}{next.status === 'starting' && <button disabled={busy} onClick={() => trialAction(next, 'reconcile')}>Check station</button>}{next.status === 'running' && <><button disabled={busy} onClick={() => trialAction(next, 'stop')}>Stop robot</button><button className="secondary" disabled={busy} onClick={() => trialAction(next, 'sync')}>Sync if ended</button></>}{next.status === 'awaiting_rollout' && <button disabled={busy} onClick={() => trialAction(next, 'sync')}>Find rollout</button>}</div>{next.status === 'awaiting_label' && <div className="label-form trial-label">{next.episode_id && <details key={next.episode_id}><summary>Review rollout</summary><RolloutPreview episodeId={next.episode_id} /></details>}<label>Outcome<select value={outcome} onChange={(event) => setOutcome(event.target.value as 'success' | 'failure')}><option value="success">Success</option><option value="failure">Failure</option></select></label><label>Reviewer name or ID<input maxLength={120} value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label><label>Note<textarea maxLength={2000} value={note} onChange={(event) => setNote(event.target.value)} /></label><button disabled={busy || !reviewer.trim()} onClick={() => saveLabel(next)}>Save reviewed outcome</button></div>}</section>}
    {study && !next && !unusable && <section className="card"><h2>Audit the completed comparison</h2><label><input type="checkbox" checked={resetAttested} onChange={(event) => setResetAttested(event.target.checked)} /> I checked that every diagnostic scene was reset between the two runs.</label><button disabled={busy || !resetAttested} onClick={audit}>Audit cheap fix</button></section>}
    {study && unusable && <section className="card"><h2>One run is unusable</h2><p>Keep this comparison as incomplete and freeze a fresh plan. Unknown attempts cannot be silently discarded.</p></section>}
  </Container>;
}
