import { useEffect, useRef, useState } from 'react';
import LiveEvaluation from './LiveEvaluation';

type Screen = 'preflight' | 'tasks' | 'demos' | 'training' | 'evaluation' | 'statistical';
type Message = { role: 'user' | 'assistant'; content: string };
type TaskDraft = { name: string; prompt: string; success_rule: string };
type Reply = { message: string; input_kind: 'text' | 'dream_key'; suggested_screen: Screen | null; task_draft: TaskDraft | null; suggestions: string[]; setup_help: 'robot' | 'simulator' | null };
type Account = { configured: boolean; source: string; dashboard_url: string };
type Task = { id: string; name: string; baseline_checkpoint: string };
type Status = { configured: boolean; source: string };
type Workspace = { state: string; message: string; datasets: { id: string; name: string; status: string }[]; fine_tuning_jobs: { id: string; name: string; status: string }[]; models: { id: string; name: string; status: string }[] };
type Simulator = { state: string; message: string };

async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(path, { method, cache: 'no-store', headers: body === undefined ? undefined : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(detail.detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function savedMessages(): Message[] {
  try {
    const result: unknown = JSON.parse(sessionStorage.getItem('coach-chat-v2') || '[]');
    return Array.isArray(result) ? result.filter((item): item is Message => item && (item.role === 'user' || item.role === 'assistant') && typeof item.content === 'string').slice(-24) : [];
  } catch { return []; }
}

export default function CoachChat({ open, openEvaluation }: {
  open: (screen: Screen) => void;
  openEvaluation: (taskId?: string, evaluationId?: string) => void;
}) {
  const [messages, setMessages] = useState<Message[]>(savedMessages);
  const [reply, setReply] = useState<Reply | null>(null);
  const [ai, setAi] = useState<Status | null>(null);
  const [account, setAccount] = useState<Account | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [simulator, setSimulator] = useState<Simulator | null>(null);
  const [dreamAccess, setDreamAccess] = useState('unknown');
  const [text, setText] = useState('');
  const [secret, setSecret] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [begun, setBegun] = useState(sessionStorage.getItem('coach-begun-v2') === 'yes');
  const thread = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  useEffect(() => { sessionStorage.setItem('coach-chat-v2', JSON.stringify(messages.slice(-24))); thread.current?.scrollTo({ top: thread.current.scrollHeight, behavior: 'smooth' }); }, [messages]);
  useEffect(() => { sessionStorage.setItem('coach-begun-v2', begun ? 'yes' : 'no'); }, [begun]);
  useEffect(() => {
    void Promise.all([api<Status>('/api/assistant/status'), api<Account>('/api/account/status')])
      .then(([aiStatus, dreamStatus]) => { setAi(aiStatus); setAccount(dreamStatus); })
      .catch((caught: Error) => setError(caught.message));
    void api<Simulator>('/api/simulator/status').then(setSimulator).catch(() => undefined);
  }, []);
  useEffect(() => {
    if (simulator?.state !== 'preparing') return;
    const timer = window.setInterval(() => { void api<Simulator>('/api/simulator/status').then(setSimulator).catch(() => undefined); }, 1500);
    return () => window.clearInterval(timer);
  }, [simulator?.state]);
  useEffect(() => {
    if (ai?.configured && !started.current && messages.length === 0) {
      started.current = true;
      void turn([], 'introduction');
    }
  // Initial turn only. Subsequent turns are sent by submit or Continue.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ai?.configured]);
  useEffect(() => { if (messages.length > 0 && begun) void workflowState().catch(() => undefined);
  // The opening introduction does not run account checks until Begin.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function workflowState() {
    const dream = await api<Account>('/api/account/status');
    setAccount(dream);
    const [preflight, tasks, sim] = await Promise.all([
      api<{ dream: { state: string; message: string }; station: { state: string; message: string }; models: { id: string; servable: boolean }[] }>('/api/preflight'),
      api<Task[]>('/api/tasks'),
      api<Simulator>('/api/simulator/status'),
    ]);
    setSimulator(sim);
    setDreamAccess(preflight.dream.state);
    const current = tasks[0];
    const remote = dream.configured && preflight.dream.state === 'ready' ? await api<Workspace>('/api/account/workspace').catch(() => null) : null;
    setWorkspace(remote);
    const taskData = current ? await Promise.all([
      api<{ phase: string; next_action: string; evidence: string[] }>(`/api/tasks/${current.id}/guidance`),
      api<{ decision: string }[]>(`/api/tasks/${current.id}/demos`),
      api<{ status: string }[]>(`/api/tasks/${current.id}/datasets`),
      api<{ status: string; checkpoint: string | null }[]>(`/api/tasks/${current.id}/finetunes`),
      api<unknown[]>(`/api/tasks/${current.id}/evaluations`),
    ]) : null;
    return {
      dream_connected: preflight.dream.state === 'ready', dream_api_ready: preflight.dream.state === 'ready',
      local_api_key_configured: dream.configured, browser_login_checked: false,
      dream_preflight: preflight.dream,
      dream_account_inventory: remote ? { state: remote.state, datasets: remote.datasets,
        fine_tuning_jobs: remote.fine_tuning_jobs, models: remote.models } : null,
      bundled_example: { task: 'YAM apple pickup', local_archives: ['independent.zip', 'varied.zip'],
        existing_training_and_evaluation: true, new_failure_conditioned_sim_collection_available: true,
        simulator_status: sim.state,
        note: 'Existing data and a 500-step Dream checkpoint can be inspected without recording new demos or submitting another paid job.' },
      robot_station: preflight.station, available_models: preflight.models.filter((model) => model.servable).map((model) => model.id).slice(0, 8),
      tasks: tasks.map((task) => ({ id: task.id, name: task.name, baseline_checkpoint: task.baseline_checkpoint })),
      current_task: current ? { id: current.id, name: current.name, guidance: taskData?.[0],
        kept_demos: taskData?.[1].filter((demo) => demo.decision === 'keep').length,
        dataset_count: taskData?.[2].length, training_jobs: taskData?.[3].map((job) => ({ status: job.status, checkpoint: job.checkpoint })),
        evaluations: taskData?.[4].length } : null,
    };
  }

  async function turn(history: Message[], stage: 'introduction' | 'guide' = 'guide') {
    setBusy(true); setError('');
    try {
      const state = stage === 'introduction' ? { introduction_only: true } : await workflowState();
      const result = await api<Reply>('/api/assistant/chat', 'POST', { messages: history.slice(-24), state, stage });
      setReply(result);
      setMessages([...history, { role: 'assistant', content: result.message }]);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'The coach could not reply.'); }
    finally { setBusy(false); }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const input = text.trim();
    if (!input || busy) return;
    if (/\b(?:dl_live_|sk-)[A-Za-z0-9_-]{12,}/.test(input)) { setError('Enter API keys in the masked key field, not the chat.'); return; }
    setText('');
    const history: Message[] = [...messages, { role: 'user', content: input }];
    setMessages(history);
    await turn(history);
  }

  async function connectDream(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const status = await api<Account>('/api/account/connect', 'POST', { api_key: secret.trim() });
      setSecret(''); setAccount(status);
      const history: Message[] = [...messages, { role: 'user', content: 'I connected my Dream Labs account successfully.' }];
      setMessages(history);
      await turn(history);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not connect Dream Labs.'); setBusy(false); }
  }

  async function saveTask(draft: TaskDraft) {
    setBusy(true); setError('');
    try {
      const preflight = await api<{ models: { id: string; servable: boolean }[] }>('/api/preflight');
      const checkpoint = preflight.models.find((model) => model.servable)?.id || 'dreamlabs/dream-1';
      await api('/api/tasks', 'POST', { ...draft, baseline_checkpoint: checkpoint });
      const history: Message[] = [...messages, { role: 'user', content: `I confirmed and saved the task “${draft.name}”.` }];
      setMessages(history); setReply(null);
      await turn(history);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not save task.'); setBusy(false); }
  }

  async function prepareSimulator() {
    setError('');
    try {
      const status = await api<Simulator>('/api/simulator/prepare', 'POST');
      setSimulator(status);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not prepare the simulator.'); }
  }

  function beginConversation() {
    const history: Message[] = [...messages, {
      role: 'user',
      content: 'Begin. Please check my Dream Labs connection and guide me one step at a time.',
    }];
    setBegun(true);
    setMessages(history);
    void turn(history, 'guide');
  }

  function startOver() {
    started.current = true;
    setBegun(false);
    setMessages([]);
    setReply(null);
    setText('');
    setSecret('');
    void turn([], 'introduction');
  }

  return <main className="page chat-page">
    <header className="header"><div><h1>DreamCoach</h1><p className="subtitle">Fine-tune Dream-1 for a task and measure how it performs.</p></div></header>
    {error && <div className="alert" role="alert">{error}</div>}
    <div className="chat-layout">
    <section className="card chat-shell" aria-label="Fine-tuning coach conversation">
      <div className="chat-landscape" aria-hidden="true"><video autoPlay loop muted playsInline poster="/dream/sunrise-hd-poster.webp"><source src="/dream/sunrise-hd.mp4" type="video/mp4" /></video><span className="chat-spark chat-spark-one">✦</span><span className="chat-spark chat-spark-two">✦</span></div>
      <div className="chat-panel-top">
        <span className="chat-landscape-title">Conversation</span>
        {begun && <button type="button" className="chat-reset" disabled={!ai?.configured || busy} onClick={startOver}>Start over</button>}
      </div>
      <div className="chat-thread" ref={thread} aria-live="polite">
        {ai && !ai.configured && <div className="chat-bubble chat-assistant"><span>DreamCoach</span><p>The AI coach is unavailable on this server. Ask the operator to configure its AI credential, then refresh this page.</p></div>}
        {messages.map((item, index) => <div key={index} className={`chat-bubble chat-${item.role}`}><span>{item.role === 'assistant' ? 'DreamCoach' : 'You'}</span><p>{item.content}</p></div>)}
        {busy && <div className="chat-bubble chat-assistant"><span>DreamCoach</span><p>Thinking through your next step…</p></div>}
      {begun && account && (!account.configured || dreamAccess === 'blocked') && <div className="chat-action"><p><a href={account.dashboard_url} target="_blank" rel="noreferrer">Open Dream Labs API keys</a>, sign in, and create a key. Paste it in this private field when you have it. The key is not saved in this chat. This checks API access on this machine, not your browser’s Dream website login.</p><form onSubmit={(event) => void connectDream(event)} className="chat-secret"><input aria-label="Dream API key" type="password" autoComplete="off" value={secret} onChange={(event) => setSecret(event.target.value)} placeholder="Dream API key" /><button disabled={busy || !secret.trim()}>Connect Dream</button></form></div>}
      {begun && workspace?.state === 'ready' && <details className="chat-inventory"><summary>Dream account data · {workspace.datasets.length} datasets · {workspace.fine_tuning_jobs.length} jobs</summary><div><p>Read from Dream’s API with this server’s key. These are account resources, separate from local coach tasks.</p><h3>Datasets</h3><ul>{workspace.datasets.map((item) => <li key={item.id}>{item.name} · {item.status}</li>)}</ul><h3>Fine-tuning jobs</h3><ul>{workspace.fine_tuning_jobs.map((item) => <li key={item.id}>{item.name} · {item.status}</li>)}</ul><div className="chat-inventory-links"><a href="/api/docs/apple-training" target="_blank" rel="noreferrer">Committed apple dataset and training record</a><a href="/api/docs/apple-evaluation" target="_blank" rel="noreferrer">Measured 500-step comparison</a><button className="secondary" onClick={() => open('statistical')}>Open existing apple audit</button></div></div></details>}
      {begun && reply && reply.suggestions.length > 0 && <div className="chat-suggestions"><span>Try an answer, or edit it before sending</span><div>{reply.suggestions.map((suggestion, index) => <button key={`${suggestion}-${index}`} className="secondary" disabled={busy} onClick={() => setText(suggestion)}>{suggestion}</button>)}</div></div>}
      {begun && reply?.setup_help === 'robot' && <div className="chat-action chat-setup-help"><strong>Robot setup</strong><p>Connect the arms and cameras, then run Preflight to confirm fresh camera frames before a baseline trial.</p><button className="secondary" onClick={() => open('preflight')}>Check arms and cameras</button><a href="https://platform.dreamlabs.ai/setup" target="_blank" rel="noreferrer">Dream robot setup guide</a></div>}
      {begun && (reply?.setup_help === 'simulator' || /simulator screen|set up the YAM simulator/i.test(reply?.message || '')) && <div className="chat-action chat-setup-help"><strong>Bundled YAM simulator · {simulator?.state || 'checking'}</strong><p>{simulator?.message || 'Checking local simulator setup.'} This path is for optional new apple-pickup demonstrations; your existing Dream dataset and checkpoint can be reviewed first.</p><button className="secondary" disabled={simulator?.state === 'preparing'} onClick={() => void prepareSimulator()}>{simulator?.state === 'ready' ? 'Recheck YAM simulator' : 'Prepare YAM simulator'}</button><a href="/api/docs/simulator" target="_blank" rel="noreferrer">Open the real simulator setup guide</a></div>}
      {begun && reply?.task_draft && <div className="chat-action"><strong>Ready to save this task?</strong><p>{reply.task_draft.name} · {reply.task_draft.prompt}<br />Success: {reply.task_draft.success_rule}</p><button disabled={busy} onClick={() => void saveTask(reply.task_draft!)}>Confirm and save task</button></div>}
      {begun && reply?.suggested_screen && reply.suggested_screen !== 'tasks' && <div className="chat-action"><button className="secondary" onClick={() => open(reply.suggested_screen!)}>{`Open ${reply.suggested_screen}`}</button><span>Return here afterward and tell the coach what happened.</span></div>}
      </div>
      {!begun && ai?.configured && messages.length > 0 && <div className="chat-begin">
        <p id="chat-begin-description">First, we’ll check Dream Labs access.</p>
        <button type="button" aria-describedby="chat-begin-description" disabled={busy} onClick={beginConversation}>
          Begin<span className="chat-begin-arrow" aria-hidden="true">→</span>
        </button>
      </div>}
      {begun && <form onSubmit={(event) => void submit(event)} className="chat-composer"><textarea aria-label="Message to coach" disabled={!ai?.configured} value={text} maxLength={2000} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit(event); } }} placeholder="Tell me about your robot or ask what to do next…" /><button disabled={!ai?.configured || busy || !text.trim()}>Send</button></form>}
    </section>
    <LiveEvaluation onOpen={openEvaluation} onOpenAudit={() => open('statistical')} />
    </div>
  </main>;
}
