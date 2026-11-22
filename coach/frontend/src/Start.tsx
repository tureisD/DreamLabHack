import { useCallback, useEffect, useState } from 'react';

type Screen = 'preflight' | 'tasks' | 'demos' | 'training' | 'evaluation' | 'statistical';
type Account = { configured: boolean; source: string; message: string; dashboard_url: string };
type Check = { state: string; message: string };
type Preflight = { dream: Check; station: Check; models: { id: string; servable: boolean }[] };
type Task = { id: string; name: string; prompt: string; success_rule: string; baseline_checkpoint: string };
type Guidance = { phase: string; headline: string; next_action: string; target_screen: string; evidence: string[] };
type Demo = { decision: string };
type Dataset = { status: string };
type Job = { status: string; checkpoint: string | null };
type Evaluation = { id: string };
type Answer = { answer: string; mode: string; external_ai_available: boolean };

async function request<T>(url: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method, cache: 'no-store',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(data.detail ?? `Request failed (${response.status})`);
  }
  return await response.json() as T;
}

export default function Start({ open }: { open: (screen: Screen) => void }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskId, setTaskId] = useState('');
  const [guidance, setGuidance] = useState<Guidance | null>(null);
  const [demos, setDemos] = useState<Demo[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [apiKey, setApiKey] = useState('');
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [rule, setRule] = useState('');
  const [checkpoint, setCheckpoint] = useState('');
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [externalAi, setExternalAi] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [nextAccount, nextPreflight, nextTasks] = await Promise.all([
        request<Account>('/api/account/status'), request<Preflight>('/api/preflight'),
        request<Task[]>('/api/tasks'),
      ]);
      setAccount(nextAccount); setPreflight(nextPreflight); setTasks(nextTasks);
      setCheckpoint((current) => current || nextPreflight.models.find((model) => model.servable)?.id || 'dreamlabs/dream-1');
      setTaskId((current) => nextTasks.some((task) => task.id === current) ? current : nextTasks[0]?.id ?? '');
      setError('');
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not refresh setup.'); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!taskId) { setGuidance(null); setDemos([]); setDatasets([]); setJobs([]); setEvaluations([]); return; }
    let active = true;
    void Promise.all([
      request<Guidance>(`/api/tasks/${taskId}/guidance`),
      request<Demo[]>(`/api/tasks/${taskId}/demos`),
      request<Dataset[]>(`/api/tasks/${taskId}/datasets`),
      request<Job[]>(`/api/tasks/${taskId}/finetunes`),
      request<Evaluation[]>(`/api/tasks/${taskId}/evaluations`),
    ]).then(([guide, recordings, versions, training, checks]) => {
      if (active) { setGuidance(guide); setDemos(recordings); setDatasets(versions); setJobs(training); setEvaluations(checks); }
    }).catch((caught: Error) => { if (active) setError(caught.message); });
    return () => { active = false; };
  }, [taskId, message]);

  async function connect(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    try {
      const status = await request<Account>('/api/account/connect', 'POST', { api_key: apiKey });
      setApiKey(''); setAccount(status); setMessage('Dream account connected. Next, check the robot or simulator setup.');
      await refresh();
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not connect account.'); }
    finally { setBusy(false); }
  }

  async function createTask(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    try {
      const task = await request<Task>('/api/tasks', 'POST', {
        name, prompt, baseline_checkpoint: checkpoint, success_rule: rule,
      });
      setName(''); setPrompt(''); setRule('');
      setMessage('Task saved. Measure how the base checkpoint performs before collecting new demonstrations.');
      await refresh(); setTaskId(task.id);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not create task.'); }
    finally { setBusy(false); }
  }

  async function ask(event: React.FormEvent) {
    event.preventDefault(); if (!question.trim()) return;
    setBusy(true); setError(''); setAnswer(null);
    try {
      setAnswer(await request<Answer>('/api/assistant/ask', 'POST', {
        question: question.trim(), phase: guidance?.phase ?? (account?.configured ? 'task setup' : 'account setup'),
        next_action: guidance?.next_action ?? 'Connect Dream Labs and define a task.',
        allow_external_ai: externalAi,
      }));
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not answer.'); }
    finally { setBusy(false); }
  }

  const selected = tasks.find((task) => task.id === taskId);
  const kept = demos.filter((demo) => demo.decision === 'keep').length;
  const readyJob = jobs.find((job) => job.status === 'succeeded' && job.checkpoint);
  const steps = [
    { title: 'Connect Dream Labs', done: account?.configured && preflight?.dream.state === 'ready', detail: account && !account.configured ? account.message : preflight?.dream.message ?? 'Checking account…', action: 'Account setup' },
    { title: 'Check your setup', done: preflight?.station.state === 'ready', detail: preflight?.station.message ?? 'Checking robot station…', action: 'Open preflight' },
    { title: 'Define one task', done: Boolean(selected), detail: selected ? `${selected.name}: ${selected.success_rule}` : 'Name the job and decide what counts as success.', action: 'Create task' },
    { title: 'Measure the base model', done: guidance?.phase !== 'baseline' && Boolean(guidance), detail: 'Run a few supervised trials and label success or failure.', action: 'Open tasks' },
    { title: 'Collect demonstrations', done: kept > 0, detail: `${kept} kept recording${kept === 1 ? '' : 's'}. Record examples where the base model fails.`, action: 'Open demonstrations' },
    { title: 'Fine-tune with FaaS', done: Boolean(readyJob), detail: readyJob ? 'Candidate checkpoint is ready.' : `${datasets.length} dataset version(s), ${jobs.length} training job(s).`, action: 'Open training' },
    { title: 'Prove it improved', done: evaluations.length > 0 && guidance?.phase === 'verdict', detail: 'Compare base and candidate on held-out scenes; save an audited verdict.', action: 'Open evaluation' },
  ];
  const next = steps.findIndex((step) => !step.done);

  return <main className="page onboarding-page">
    <header className="header"><div><p className="eyebrow">Beginner walkthrough</p><h1>Teach Dream-1 a task</h1><p className="subtitle">We’ll help you connect an account, gather useful demonstrations, train, and check whether the result works.</p></div><button className="secondary" onClick={() => void refresh()}>Refresh progress</button></header>
    {error && <div className="alert" role="alert">{error}</div>}
    {message && <div className="notice" role="status">{message}</div>}
    <section className="card onboarding-next"><p className="eyebrow">Your next step</p><h2>{steps[next]?.title ?? 'Review your results'}</h2><p>{guidance && next > 2 ? guidance.next_action : steps[next]?.detail ?? 'Open Evaluation to inspect the audited result.'}</p>{guidance && next > 2 && <p className="hint">Based on: {guidance.evidence.slice(0, 2).join(' ')}</p>}</section>
    <div className="onboarding-layout"><div className="onboarding-main">
      <section className="card"><h2>1. Connect your Dream account</h2><p>{account && !account.configured ? account.message : preflight?.dream.message ?? 'Checking connection…'}</p><p>Need a key? <a href={account?.dashboard_url ?? 'https://platform.dreamlabs.ai/'} target="_blank" rel="noreferrer">Open the Dream Labs platform</a>, sign in, and create an API key in your account settings. Return here and paste it below.</p><form onSubmit={(event) => void connect(event)} className="label-form"><label>Dream API key<input type="password" required minLength={12} maxLength={300} autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Paste your Dream API key" /></label><button disabled={busy || !apiKey.trim()}>Validate and connect</button></form><p className="hint">The key is validated with Dream Labs and saved in the SDK’s local credentials file. It is not kept in browser storage or displayed again. A server environment key takes precedence.</p></section>
      <section className="card"><h2>2. Check how you’ll collect data</h2><p>{preflight?.station.message ?? 'Checking the robot station…'}</p><p>If you have a connected robot, open Preflight and check that both arms and camera frames are live. The supported SO-101 recorder is in Demonstrations. If you have no robot, inspect the included simulator comparison and follow its setup guide; a new training dataset still requires recorded episodes.</p><div className="onboarding-actions"><button className="secondary" onClick={() => open('preflight')}>Check robot and cameras</button><button className="secondary" onClick={() => open('statistical')}>See simulator example</button></div></section>
      <section className="card"><h2>3. Describe the task</h2><p>Start with one concrete job. Use a success rule a person can judge from the final rollout.</p>{tasks.length > 0 && <label>Work on task<select value={taskId} onChange={(event) => setTaskId(event.target.value)}>{tasks.map((task) => <option key={task.id} value={task.id}>{task.name}</option>)}</select></label>}<form onSubmit={(event) => void createTask(event)} className="label-form"><label>Short name<input required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} placeholder="Pick up the apple" /></label><label>Instruction for the robot<input required maxLength={500} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Pick up the apple and hold it above the table" /></label><label>What counts as success?<textarea required maxLength={1000} value={rule} onChange={(event) => setRule(event.target.value)} placeholder="Apple stays at least 8 cm above the table for 2 seconds" /></label><label>Base checkpoint<input required maxLength={200} value={checkpoint} onChange={(event) => setCheckpoint(event.target.value)} /></label><button disabled={busy}>Save task</button></form></section>
      <section className="card"><h2>4. Measure, record, train, evaluate</h2><p>Run and label the base model first. Then record demonstrations of the failure, review their quality and coverage, freeze a dataset, submit an explicit paid FaaS job, and compare its checkpoint with the base on held-out scenes.</p><div className="onboarding-actions"><button onClick={() => open('tasks')}>Run baseline</button><button className="secondary" onClick={() => open('demos')}>Record demos</button><button className="secondary" onClick={() => open('training')}>Open fine-tuning</button><button className="secondary" onClick={() => open('evaluation')}>Open evaluation</button></div></section>
    </div><aside className="onboarding-side"><section className="card"><h2>Your progress</h2><ol className="onboarding-steps">{steps.map((step, index) => <li key={step.title} className={step.done ? 'done' : index === next ? 'current' : ''}><strong>{step.done ? '✓ ' : `${index + 1}. `}{step.title}</strong><span>{step.detail}</span></li>)}</ol></section><section className="card"><h2>Ask the coach</h2><p>Unsure what to do? Ask about your next step, data collection, training, or evaluation.</p><form onSubmit={(event) => void ask(event)} className="label-form"><label>Your question<textarea required minLength={3} maxLength={1500} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="How do I collect my first demonstration?" /></label><label className="onboarding-consent"><input type="checkbox" checked={externalAi} onChange={(event) => setExternalAi(event.target.checked)} /> Use an external AI answer when configured. This sends my question and current step to OpenAI.</label><button disabled={busy || question.trim().length < 3}>Ask</button></form>{answer && <div className="onboarding-answer" role="status"><small>{answer.mode === 'ai' ? 'AI answer' : 'Local guided help'}</small><p>{answer.answer}</p>{!answer.external_ai_available && externalAi && <p className="hint">External AI needs OPENAI_API_KEY on the coach server.</p>}</div>}</section></aside></div>
  </main>;
}
