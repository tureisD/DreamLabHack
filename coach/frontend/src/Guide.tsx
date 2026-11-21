import { useEffect, useState } from 'react';

type Task = { id: string; name: string };
type Guidance = {
  phase: string; headline: string; next_action: string; evidence: string[];
  target_screen: string; pilot_ready: boolean;
  suggested_recipe: { steps: number; lr_schedule: string; base_share: number } | null;
};

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
  const [error, setError] = useState('');

  useEffect(() => {
    void json<Task[]>('/api/tasks').then((values) => {
      setTasks(values); if (values.length) setTaskId(values[0].id);
    }).catch((caught: Error) => setError(caught.message));
  }, []);

  useEffect(() => {
    if (!taskId) { setGuidance(null); return; }
    let active = true;
    const refresh = async () => {
      try {
        const value = await json<Guidance>(`/api/tasks/${taskId}/guidance`);
        if (active) { setGuidance(value); setError(''); }
      } catch (caught) { if (active) setError(caught instanceof Error ? caught.message : 'Could not load task guidance.'); }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [taskId]);

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
        <h3>What this is based on</h3>
        <ul>{guidance.evidence.map((item, index) => <li key={index}>{item}</li>)}</ul>
        {guidance.pilot_ready && <p className="notice">Ready to try an initial pilot, subject to Dream dataset validation. This is a coverage signal, not a predicted success rate.</p>}
        {guidance.suggested_recipe && <p className="hint">Suggested first recipe: {guidance.suggested_recipe.steps} steps, {guidance.suggested_recipe.lr_schedule} schedule, base share {guidance.suggested_recipe.base_share}. Review and edit it in Training before paid submission.</p>}
      </section>}
    </>}
  </main>;
}
