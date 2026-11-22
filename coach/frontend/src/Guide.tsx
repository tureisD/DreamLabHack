import { useEffect, useState } from 'react';
import { ArrowRight, CheckCircle2, Circle } from 'lucide-react';
import { initialTask, screenHref, selectTask, type Screen } from './workspaceRoute';

type Task = { id: string; name: string; prompt: string };
type Guidance = {
  phase: string; headline: string; next_action: string; evidence: string[];
  target_screen: Screen; target_episode_id: string | null; target_cell: number | null; pilot_ready: boolean;
  suggested_recipe: { steps: number; lr_schedule: string; base_share: number } | null;
};
type Issue = { id:string; episode_id:string; message:string; reason:string|null; reviewed_at:string|null };
type Diagnosis = { findings:Issue[]; open_finding_count:number; runs:{episode_id:string;category:string}[]; setup_count: number; data_count: number; unknown_count: number; failure_stages: Record<string, number>; recommendation: string };
type Consistency = { heldout_successes: number; heldout_failures: number; threshold: number | null; scored_runs: number; successful_calibration_runs: number; alerts: number; labelled_failures_alerted: number; labelled_successes_alerted: number };

async function json<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    const detail = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail ?? `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export default function Guide() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskId, setTaskId] = useState('');
  const [guidance, setGuidance] = useState<Guidance | null>(null);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [consistency, setConsistency] = useState<Consistency | null>(null);
  const [error, setError] = useState('');

  const [reload,setReload] = useState(0);
  const [reasons,setReasons] = useState<Record<string,string>>({});
  const [saving,setSaving] = useState(false);
  const selectedTask = tasks.find(t => t.id === taskId);
  async function acknowledge(issue:Issue){
    const reason=reasons[issue.id]?.trim(); if(!reason||saving)return;
    setSaving(true);
    try{const res=await fetch(`/api/tasks/${taskId}/findings/${issue.id}/review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason})});if(!res.ok)throw Error();setReload(v=>v+1);}catch{setError('Review not saved. Your note is still here.');}finally{setSaving(false);}
  }

  useEffect(() => {
    void json<Task[]>('/api/tasks').then((values) => {
      setTasks(values); if (values.length) setTaskId(initialTask(values)?.id || '');
    }).catch((caught: Error) => setError(caught.message));
  }, []);

  useEffect(() => {
    if (!taskId) { setGuidance(null); return; }
    let active = true;
    setGuidance(null); setDiagnosis(null); setConsistency(null);
    const refresh = async () => {
      try {
        void json<Consistency>(`/api/tasks/${taskId}/consistency`).then(s=>{if(active)setConsistency(s);}).catch(()=>{if(active)setConsistency(null);});
        const [value, causes] = await Promise.all([
          json<Guidance>(`/api/tasks/${taskId}/guidance`),
          json<Diagnosis>(`/api/tasks/${taskId}/diagnosis`),
        ]);
        if (active) { setGuidance(value); setDiagnosis(causes); setError(''); }
      } catch (caught) { if (active) setError(caught instanceof Error ? caught.message : 'Could not load task guidance.'); }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [taskId, reload]);

  return <main className="page">
    <header className="header"><div><p className="eyebrow">Task coach</p><h1>What should I do next?</h1><p className="subtitle">The next step comes from your labelled runs, accepted demos, and Dream job status.</p></div></header>
    {error && <div className="alert" role="alert">{error}</div>}
    {tasks.length === 0 ? (
      <section className="card">
        <h2>Create a task to begin</h2>
        <p>Define the robot instruction and success rule, then run the baseline checkpoint.</p>
        <a href={screenHref('tasks')} style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', marginTop: '16px', padding: '10px 16px', background: 'var(--accent)', color: 'white', textDecoration: 'none', borderRadius: '8px', fontWeight: 600 }}>
          Open Tasks <ArrowRight size={16} />
        </a>
      </section>
    ) : (
      <>
        <section className="card training-controls">
          <label>
            Task
            <select value={taskId} onChange={(event) => { selectTask(event.target.value); setTaskId(event.target.value); }}>
              {tasks.map((task) => (
                <option key={task.id} value={task.id}>
                  {task.name}
                </option>
              ))}
            </select>
          </label>
        </section>
        {guidance && (
          <section className="card guide-card">
            <p className="eyebrow">{guidance.phase}</p>
            <h2>{guidance.headline}</h2>
            <p className="guide-action">{guidance.next_action}</p>

            {guidance.target_screen === 'runs' && selectedTask ? (
              <a
                href={screenHref('runs', {task:taskId, ...(guidance.target_episode_id ? {run: guidance.target_episode_id} : {prompt:selectedTask.prompt})})}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '8px',
                  marginTop: '16px',
                  padding: '11px 18px',
                  background: 'var(--accent)',
                  color: 'white',
                  textDecoration: 'none',
                  borderRadius: '8px',
                  fontWeight: 600,
                  fontSize: '14px'
                }}
              >
                Review recordings <ArrowRight size={16} />
              </a>
            ) : guidance.target_screen === 'tasks' ? (
              <a
                href={screenHref('tasks')}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '8px',
                  marginTop: '16px',
                  padding: '11px 18px',
                  background: 'var(--accent)',
                  color: 'white',
                  textDecoration: 'none',
                  borderRadius: '8px',
                  fontWeight: 600,
                  fontSize: '14px'
                }}
              >
                Open Tasks <ArrowRight size={16} />
              </a>
            ) : guidance.target_screen === 'demos' ? (
              <a
                href={screenHref('demos',{task:taskId,...(guidance.target_cell!=null?{cell:String(guidance.target_cell)}:{})})}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '8px',
                  marginTop: '16px',
                  padding: '11px 18px',
                  background: 'var(--accent)',
                  color: 'white',
                  textDecoration: 'none',
                  borderRadius: '8px',
                  fontWeight: 600,
                  fontSize: '14px'
                }}
              >
                Open Demonstrations <ArrowRight size={16} />
              </a>
            ) : guidance.target_screen === 'training' ? (
              <a
                href={screenHref('training',{task:taskId})}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '8px',
                  marginTop: '16px',
                  padding: '11px 18px',
                  background: 'var(--accent)',
                  color: 'white',
                  textDecoration: 'none',
                  borderRadius: '8px',
                  fontWeight: 600,
                  fontSize: '14px'
                }}
              >
                Open Training <ArrowRight size={16} />
              </a>
            ) : (
              <p style={{ marginTop: '12px', fontSize: '14px', color: 'var(--muted)' }}>
                <a href={screenHref(guidance.target_screen,{task:taskId})}>Open {guidance.target_screen}</a>
              </p>
            )}

            <h3>What this is based on</h3>
            <ul>
              {guidance.evidence.map((item, index) => (
                <li key={index} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                  <Circle size={8} style={{ marginTop: '8px', flexShrink: 0, fill: 'currentColor' }} />
                  {item}
                </li>
              ))}
            </ul>
            {guidance.phase === 'train' && guidance.pilot_ready && (
              <p className="notice" style={{ display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
                <CheckCircle2 size={18} style={{ flexShrink: 0, marginTop: '2px' }} />
                <span>Ready to try an initial pilot, subject to Dream dataset validation. This is a coverage signal, not a predicted success rate.</span>
              </p>
            )}
            {guidance.suggested_recipe && (
              <p className="hint">
                Suggested first recipe: {guidance.suggested_recipe.steps} steps, {guidance.suggested_recipe.lr_schedule} schedule, base share {guidance.suggested_recipe.base_share}. Review and edit it in Training before paid submission.
              </p>
            )}
          </section>
        )}
        {diagnosis && (
          <section className="card guide-card">
            <h2>Why runs fail</h2>
            <p>
              {diagnosis.setup_count} station or recording issues · {diagnosis.data_count} confirmed task failures without a logged station fault · {diagnosis.unknown_count} other runs.
            </p>
            <p>{diagnosis.recommendation}</p>
            {diagnosis.runs.filter(r=>r.category==='data').map(r=><p key={r.episode_id}><a href={screenHref('runs',{task:taskId,run:r.episode_id})}>Review failure recording · {r.episode_id.slice(0,8)}</a></p>)}
            {diagnosis.findings.length>0&&<div><h3>Recording issues · {diagnosis.open_finding_count} open</h3>{diagnosis.findings.map(issue=><div key={issue.id}><a href={screenHref('runs',{task:taskId,run:issue.episode_id})}>{issue.message}</a>{issue.reviewed_at?<p>Reviewed {new Date(issue.reviewed_at).toLocaleString()}: {issue.reason}</p>:<form onSubmit={e=>{e.preventDefault();void acknowledge(issue);}}><label>Review reason<input required maxLength={1000} value={reasons[issue.id]||''} onChange={e=>setReasons({...reasons,[issue.id]:e.target.value})}/></label><button disabled={saving||!reasons[issue.id]?.trim()}>Mark reviewed</button></form>}</div>)}</div>}
            {Object.entries(diagnosis.failure_stages).length > 0 && (
              <p>
                <strong>Human-labelled failure stages:</strong>{' '}
                {Object.entries(diagnosis.failure_stages)
                  .map(([name, count]) => `${name} ${count}`)
                  .join(' · ')}
              </p>
            )}
            <p className="hint">
              These are evidence categories, not a proof of root cause. Review the rollout before acting.
            </p>
          </section>
        )}
        {consistency && (
          <section className="card guide-card">
            <h2>Action consistency screen</h2>
            <p>
              {consistency.scored_runs} runs scored from saved reply chunks.{' '}
              {consistency.threshold === null
                ? `Need at least 10 scored successful runs for a local threshold; ${consistency.successful_calibration_runs} available.`
                : `Mean per transition: threshold ${consistency.threshold.toFixed(2)} from 10 distinct successful recordings. On ${consistency.heldout_successes + consistency.heldout_failures} separate labelled recordings, ${consistency.alerts} alerts: ${consistency.labelled_failures_alerted} labelled failures, ${consistency.labelled_successes_alerted} labelled successes.`}
            </p>
            <p className="hint">
              Offline screening only. The threshold is an empirical reference, not a proven 5% false-alarm bound; no robot run is stopped automatically.
            </p>
          </section>
        )}
      </>
    )}
  </main>;
}
