import { useEffect, useRef, useState } from 'react';
import LiveEvaluation from './LiveEvaluation';
import ChatDemoReview, { type DemoKeepReceipt } from './ChatDemoReview';
import ChatTraining from './ChatTraining';
import type { ScenePreset } from './SceneTask';
import YamChatWorkflow, { type SimulatorMode, type TaskPipeline, type YamJob } from './YamChatWorkflow';

type Screen = 'preflight' | 'tasks' | 'demos' | 'training' | 'evaluation' | 'statistical';
type Message = { role: 'user' | 'assistant'; content: string; answerOptions?: string[] };
type TaskDraft = { name: string; prompt: string; success_rule: string };
type Reply = { message: string; input_kind: 'text' | 'dream_key'; suggested_screen: Screen | null; task_draft: TaskDraft | null; suggestions: string[]; setup_help: 'robot' | 'simulator' | null };
type Account = { configured: boolean; source: string; dashboard_url: string };
type Task = { id: string; name: string; baseline_checkpoint: string };
type Status = { configured: boolean; source: string };
type Workspace = { state: string; message: string; datasets: { id: string; name: string; status: string }[]; fine_tuning_jobs: { id: string; name: string; status: string }[]; models: { id: string; name: string; status: string }[] };
type Simulator = { state: string; message: string };
type WorkSurface = { kind: 'demos' | 'training'; taskId: string };
const hosted = Boolean(document.querySelector('meta[name="dreamcoach-mode"][content="hosted"]'));
const hostedIntroduction = 'Hi, I’m DreamCoach. I’ll guide you through teaching Dream-1 a task, from recording YAM demonstrations to fine-tuning and comparing the result with the base model. Press Begin to get started.';

const simulatorHelpPattern = /simulator screen|set up the YAM simulator/i;

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

export default function CoachChat({
  open, openEvaluation, activeTaskId, selectTask, showSimulatorOnOpen,
  simulatorMode, chooseSimulatorMode, openRecorder, demoApproval, clearDemoApproval, onDemoKept,
  needsHostedConnection, onHostedConnection,
}: {
  open: (screen: Screen) => void;
  openEvaluation: (taskId?: string, evaluationId?: string) => void;
  activeTaskId: string;
  selectTask: (taskId: string) => void;
  showSimulatorOnOpen: boolean;
  simulatorMode: SimulatorMode;
  chooseSimulatorMode: (mode: SimulatorMode) => void;
  openRecorder: (mode: 'fruit' | 'scene', preset?: ScenePreset) => void;
  demoApproval: DemoKeepReceipt | null;
  clearDemoApproval: () => void;
  onDemoKept: (receipt: DemoKeepReceipt) => void;
  needsHostedConnection: boolean;
  onHostedConnection: () => void;
}) {
  const [messages, setMessages] = useState<Message[]>(() => needsHostedConnection ? [] : savedMessages());
  const [reply, setReply] = useState<Reply | null>(null);
  const [ai, setAi] = useState<Status | null>(null);
  const [account, setAccount] = useState<Account | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [simulator, setSimulator] = useState<Simulator | null>(null);
  const [yamJob, setYamJob] = useState<YamJob | null>(null);
  const [pipeline, setPipeline] = useState<TaskPipeline | null>(null);
  const [workflowTask, setWorkflowTask] = useState<Task>();
  const [workSurface, setWorkSurface] = useState<WorkSurface | null>(null);
  const [comparisonReady, setComparisonReady] = useState<{ taskId: string; jobId: string; yam: boolean | null } | null>(null);
  const [comparisonStarting, setComparisonStarting] = useState(false);
  const [showSimulator, setShowSimulator] = useState(showSimulatorOnOpen);
  const [exampleCheckpoints, setExampleCheckpoints] = useState<string[]>([]);
  const [dreamAccess, setDreamAccess] = useState('unknown');
  const [text, setText] = useState('');
  const [secret, setSecret] = useState('');
  const [hostedAiKey, setHostedAiKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [begun, setBegun] = useState(() => !needsHostedConnection && sessionStorage.getItem('coach-begun-v2') === 'yes');
  const thread = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const started = useRef(false);

  useEffect(() => {
    sessionStorage.setItem('coach-chat-v2', JSON.stringify(messages.slice(-24)));
    if (!workSurface) thread.current?.scrollTo({ top: thread.current.scrollHeight });
  }, [messages, workSurface]);
  useEffect(() => {
    const content = thread.current;
    if (!content) return;
    if (workSurface) {
      content.scrollTop = 0;
      content.focus({ preventScroll: true });
    } else if (demoApproval || comparisonReady) {
      content.scrollTop = content.scrollHeight;
      content.querySelector<HTMLButtonElement>('.chat-workspace-return button')?.focus({ preventScroll: true });
    }
  }, [workSurface, demoApproval, comparisonReady]);
  useEffect(() => { sessionStorage.setItem('coach-begun-v2', begun ? 'yes' : 'no'); }, [begun]);
  useEffect(() => {
    if (needsHostedConnection) return;
    void Promise.all([api<Status>('/api/assistant/status'), api<Account>('/api/account/status')])
      .then(([aiStatus, dreamStatus]) => { setAi(aiStatus); setAccount(dreamStatus); })
      .catch((caught: Error) => setError(caught.message));
    void api<Simulator>('/api/simulator/status').then(setSimulator).catch(() => undefined);
    void api<string[]>('/api/simulator/example-checkpoints').then(setExampleCheckpoints).catch(() => undefined);
  }, [needsHostedConnection]);
  useEffect(() => {
    if (simulator?.state !== 'preparing') return;
    const timer = window.setInterval(() => { void api<Simulator>('/api/simulator/status').then(setSimulator).catch(() => undefined); }, 1500);
    return () => window.clearInterval(timer);
  }, [simulator?.state]);
  useEffect(() => {
    if (!begun || needsHostedConnection) return;
    let cancelled = false;
    let timer: number;
    async function poll() {
      try {
        const next = await api<YamJob | null>('/api/simulator/workflow');
        if (cancelled) return;
        setYamJob(next);
        if (!activeTaskId) return;
        const root = `/api/tasks/${activeTaskId}`;
        const [demos, datasets, jobs] = await Promise.all([
          api<{ decision: string }[]>(`${root}/demos`),
          api<{ status: string }[]>(`${root}/datasets`),
          api<NonNullable<TaskPipeline['job']>[]>(`${root}/finetunes`),
        ]);
        if (!cancelled) setPipeline({
          kept: demos.filter((demo) => demo.decision === 'keep').length,
          unreviewed: demos.filter((demo) => demo.decision === 'unreviewed').length,
          validated: datasets.some((dataset) => dataset.status === 'validated'),
          job: jobs[0],
        });
      } catch {
        // Keep the last result if a read fails and retry on the next poll.
      } finally {
        if (!cancelled) timer = window.setTimeout(poll, 4000);
      }
    }
    setPipeline(null);
    void poll();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [begun, activeTaskId, needsHostedConnection]);
  useEffect(() => {
    if (!hosted && !begun && !started.current) {
      started.current = true;
      void turn([], 'introduction');
    }
  // Refresh the local welcome for sessions that have not clicked Begin.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [begun]);
  useEffect(() => { if (messages.length > 0 && begun) void workflowState().catch(() => undefined);
  // The opening introduction does not run account checks until Begin.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function workflowState(taskId = activeTaskId) {
    const dream = await api<Account>('/api/account/status');
    setAccount(dream);
    const [preflight, tasks, sim, workflow] = await Promise.all([
      api<{ dream: { state: string; message: string }; station: { state: string; message: string }; models: { id: string; servable: boolean }[] }>('/api/preflight'),
      api<Task[]>('/api/tasks'),
      api<Simulator>('/api/simulator/status'),
      api<YamJob | null>('/api/simulator/workflow'),
    ]);
    setSimulator(sim);
    setDreamAccess(preflight.dream.state);
    const current = tasks.find((task) => task.id === taskId) ?? tasks[0];
    setWorkflowTask(current);
    const remote = dream.configured && preflight.dream.state === 'ready' ? await api<Workspace>('/api/account/workspace').catch(() => null) : null;
    setWorkspace(remote);
    const taskData = current ? await Promise.all([
      api<{ phase: string; next_action: string; evidence: string[] }>(`/api/tasks/${current.id}/guidance`),
      api<{ decision: string }[]>(`/api/tasks/${current.id}/demos`),
      api<{ status: string }[]>(`/api/tasks/${current.id}/datasets`),
      api<{ status: string; checkpoint: string | null }[]>(`/api/tasks/${current.id}/finetunes`),
      api<unknown[]>(`/api/tasks/${current.id}/evaluations`),
      api<{ report: {
        decision: string; baseline_successes: number; baseline_attempted: number;
        candidate_successes: number; candidate_attempted: number; usable_pairs: number;
        planned_pairs: number; observed_difference: number | null; problems: string[];
      } } | null>(`/api/simulator/comparisons/${current.id}`),
    ]) : null;
    return {
      simulator_mode: simulatorMode,
      simulator_comparison: taskData?.[5]?.report ?? null,
      simulator_workflow: workflow ? {
        task_id: workflow.task_id, kind: workflow.kind, status: workflow.state,
        completed: workflow.completed, total: workflow.total, demos: workflow.demos,
      } : null,
      current_task: current ? { id: current.id, name: current.name, guidance: taskData?.[0],
        kept_demos: taskData?.[1].filter((demo) => demo.decision === 'keep').length,
        dataset_count: taskData?.[2].length, training_jobs: taskData?.[3].map((job) => ({ status: job.status, checkpoint: job.checkpoint })),
        evaluations: taskData?.[4].length } : null,
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
    };
  }

  async function turn(history: Message[], stage: 'introduction' | 'guide' = 'guide', taskId?: string) {
    setBusy(true); setError('');
    try {
      const state = stage === 'introduction' ? { introduction_only: true } : await workflowState(taskId);
      const transcript = history.slice(-24).map(({ role, content }) => ({ role, content }));
      const result = await api<Reply>('/api/assistant/chat', 'POST', { messages: transcript, state, stage });
      setReply(result);
      const asksForAnAnswer = stage === 'guide' && result.input_kind === 'text'
        && !result.task_draft && !result.setup_help && !result.suggested_screen
        && !simulatorHelpPattern.test(result.message)
        && /\?["'’”*_\x60)\s]*$/.test(result.message);
      setMessages([...history, {
        role: 'assistant',
        content: result.message,
        answerOptions: asksForAnAnswer ? result.suggestions : undefined,
      }]);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'The coach could not reply.'); }
    finally { setBusy(false); }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const input = text.trim();
    if (!input || busy) return;
    if (/\b(?:dl_live_|sk-)[A-Za-z0-9_-]{12,}/.test(input)) { setError('Enter API keys in the masked key field, not the chat.'); return; }
    setText('');
    clearDemoApproval();
    setComparisonReady(null);
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

  async function createHostedWorkspace(event: React.FormEvent) {
    event.preventDefault();
    const key = secret.trim();
    if (!key || busy) return;
    setBusy(true);
    setError('');
    try {
      await api<{ ready: boolean }>('/hosted/workspace', 'POST', { api_key: key });
      setSecret('');
      setMessages([
        { role: 'assistant', content: hostedIntroduction },
        { role: 'assistant', content: 'Your Dream Labs account is connected. Choose a YAM workflow below to start recording or review the example demonstrations.' },
      ]);
      setShowSimulator(true);
      onHostedConnection();
      await workflowState();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not connect Dream Labs.');
    } finally {
      setBusy(false);
    }
  }

  async function saveTask(draft: TaskDraft) {
    setBusy(true); setError('');
    try {
      const preflight = await api<{ models: { id: string; servable: boolean }[] }>('/api/preflight');
      const checkpoint = preflight.models.find((model) => model.servable)?.id || 'dreamlabs/dream-1';
      const task = await api<Task>('/api/tasks', 'POST', { ...draft, baseline_checkpoint: checkpoint });
      selectTask(task.id);
      const history: Message[] = [...messages, { role: 'user', content: `I confirmed and saved the task “${draft.name}”.` }];
      setMessages(history); setReply(null);
      await turn(history, 'guide', task.id);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not save task.'); setBusy(false); }
  }

  async function prepareSimulator() {
    setError('');
    try {
      const status = await api<Simulator>('/api/simulator/prepare', 'POST');
      setSimulator(status);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not prepare the simulator.'); }
  }

  async function runYamAction(path: string, body?: unknown) {
    setError('');
    try {
      const job = await api<YamJob | null>(path, 'POST', body);
      setYamJob(job);
      if (job) {
        clearDemoApproval();
        setComparisonReady(null);
        chooseSimulatorMode('apple');
        selectTask(job.task_id);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not run the simulator action.');
    }
  }

  function openWork(kind: WorkSurface['kind'], taskId = activeTaskId || workflowTask?.id || '') {
    if (!taskId) {
      setError('Save a task in chat before reviewing demos or training.');
      return;
    }
    if (taskId !== activeTaskId) selectTask(taskId);
    setError('');
    clearDemoApproval();
    setComparisonReady(null);
    setWorkSurface({ kind, taskId });
  }

  function finishReview(receipt: DemoKeepReceipt) {
    setWorkSurface(null);
    setReply(null);
    setPipeline((current) => ({
      kept: receipt.kept,
      unreviewed: receipt.remaining,
      validated: current?.validated ?? false,
      job: current?.job,
    }));
    onDemoKept(receipt);
  }

  async function finishTraining(taskId: string, jobId: string) {
    const isApple = (task: Task) => task.name === 'Apple pickup · YAM simulator';
    const yam = yamJob?.task_id === taskId ? true : workflowTask?.id === taskId ? isApple(workflowTask) : null;
    setWorkSurface(null);
    setComparisonReady({ taskId, jobId, yam });
    if (yam !== null) return;
    try {
      const task = await api<Task>(`/api/tasks/${taskId}`);
      setComparisonReady((current) => current?.jobId === jobId ? { ...current, yam: isApple(task) } : current);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not check this task’s evaluation options.');
      setComparisonReady((current) => current?.jobId === jobId ? { ...current, yam: false } : current);
    }
  }

  async function compareReadyCheckpoint(taskId: string, jobId: string) {
    if (comparisonStarting) return;
    setComparisonStarting(true);
    try {
      await runYamAction('/api/simulator/compare', { task_id: taskId, job_id: jobId, pairs: 4 });
    } finally {
      setComparisonStarting(false);
    }
  }

  function beginConversation() {
    if (needsHostedConnection) {
      setBegun(true);
      return;
    }
    if (hosted && !ai?.configured) {
      setBegun(true);
      setShowSimulator(true);
      void workflowState().catch((caught: Error) => setError(caught.message));
      return;
    }
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
    setShowSimulator(false);
    setWorkSurface(null);
    clearDemoApproval();
    setComparisonReady(null);
    if (!hosted && ai?.configured) void turn([], 'introduction');
  }

  async function enableHostedAi(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const status = await api<Status>('/api/assistant/connect', 'POST', { api_key: hostedAiKey.trim() });
      setHostedAiKey('');
      setAi(status);
      started.current = true;
      const history: Message[] = [...messages, {
        role: 'user', content: 'Continue guiding my hosted YAM simulator workspace.',
      }];
      setMessages(history);
      await turn(history);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not enable AI chat.');
    } finally {
      setBusy(false);
    }
  }

  const hostedGuide = hosted && !ai?.configured;
  const currentYamTask = yamJob?.task_id && yamJob.task_id === activeTaskId;
  const simulatorRequested = begun && !needsHostedConnection && (hostedGuide || showSimulator || currentYamTask || simulatorMode !== 'apple'
    || reply?.setup_help === 'simulator' || simulatorHelpPattern.test(reply?.message ?? ''));
  const existingCheckpoint = exampleCheckpoints.find((checkpoint) =>
    workspace?.models.some((model) => model.id === checkpoint && model.status === 'servable'));
  const needsDreamKey = !hosted && begun && account && (!account.configured || dreamAccess === 'blocked' || dreamAccess === 'unavailable');
  const latestMessage = messages[messages.length - 1];
  const replySuggestions = begun && ai?.configured && !busy && !simulatorRequested && !needsDreamKey
    && !workSurface && !demoApproval && !comparisonReady
    && latestMessage?.role === 'assistant' && Array.isArray(latestMessage.answerOptions)
    ? latestMessage.answerOptions.filter((suggestion) => typeof suggestion === 'string' && suggestion.trim())
    : [];

  return <main className="page chat-page">
    <header className="header"><div><h1>DreamCoach</h1><p className="subtitle">Fine-tune Dream-1 for a task and measure how it performs.</p></div></header>
    {error && !needsHostedConnection && <div className="alert" role="alert">{error}</div>}
    <div className={`chat-layout${needsHostedConnection ? ' chat-layout-onboarding' : ''}`}>
    <section className="card chat-shell" aria-label="Fine-tuning coach conversation">
      <div className={`chat-landscape${hosted ? ' hosted-landscape' : ''}`} aria-hidden="true">{!hosted && <video autoPlay loop muted playsInline poster="/dream/sunrise-hd-poster.webp"><source src="/dream/sunrise-hd.mp4" type="video/mp4" /></video>}<span className="chat-spark chat-spark-one">✦</span><span className="chat-spark chat-spark-two">✦</span></div>
      <div className="chat-panel-top">
        <span className="chat-landscape-title">Conversation</span>
        {begun && !workSurface && <button type="button" className="chat-reset" disabled={busy} onClick={startOver}>Start over</button>}
      </div>
      <div className={`chat-thread${workSurface ? ' chat-thread-workspace' : ''}`} ref={thread}
        aria-live={workSurface ? undefined : 'polite'} tabIndex={workSurface ? -1 : undefined}>
      {workSurface ? (workSurface.kind === 'demos'
        ? <ChatDemoReview key={workSurface.taskId} taskId={workSurface.taskId} onClose={() => setWorkSurface(null)} onKeep={finishReview} />
        : <ChatTraining key={workSurface.taskId} taskId={workSurface.taskId} onClose={() => setWorkSurface(null)}
          onCheckpointReady={(jobId) => void finishTraining(workSurface.taskId, jobId)} />) : <>
        {hosted && messages.length === 0 && <div className="chat-bubble chat-assistant"><span>DreamCoach</span><p>{hostedIntroduction}</p></div>}
        {!hosted && ai && !ai.configured && <div className="chat-bubble chat-assistant"><span>DreamCoach</span><p>The AI coach is unavailable on this server. Ask the operator to configure its AI credential, then refresh this page.</p></div>}
        {messages.map((item, index) => <div key={index} className={`chat-bubble chat-${item.role}`}><span>{item.role === 'assistant' ? 'DreamCoach' : 'You'}</span><p>{item.content}</p></div>)}
        {busy && !needsHostedConnection && <div className="chat-bubble chat-assistant"><span>DreamCoach</span><p>Thinking through your next step…</p></div>}
      {needsHostedConnection && begun && <div className="chat-bubble chat-assistant">
        <span>DreamCoach</span>
        <p>Let’s connect your Dream Labs account. Enter your API key below and I’ll check access before we start the simulator.</p>
        <form onSubmit={(event) => void createHostedWorkspace(event)} className="chat-secret">
          <input aria-label="Dream Labs API key" type="password" autoComplete="off" autoFocus
            maxLength={300} value={secret} onChange={(event) => setSecret(event.target.value)}
            placeholder="Dream Labs API key" />
          <button type="submit" disabled={busy || !secret.trim()}>{busy ? 'Checking…' : 'Connect Dream Labs'}</button>
        </form>
        <p className="hint">DreamCoach stores your key in your private workspace, separate from the conversation.</p>
        <a href="https://platform.dreamlabs.ai/api-keys" target="_blank" rel="noreferrer">Create a Dream Labs API key</a>
        {error && <p className="alert" role="alert">{error}</p>}
      </div>}
      {needsDreamKey && <div className="chat-action"><p><a href={account.dashboard_url} target="_blank" rel="noreferrer">Open Dream Labs API keys</a>, sign in, and create a key. Paste it in this private field when you have it. The key is not saved in this chat. This checks API access on this machine, not your browser’s Dream website login.</p><form onSubmit={(event) => void connectDream(event)} className="chat-secret"><input aria-label="Dream API key" type="password" autoComplete="off" value={secret} onChange={(event) => setSecret(event.target.value)} placeholder="Dream API key" /><button disabled={busy || !secret.trim()}>Connect Dream</button></form></div>}
      {begun && workspace?.state === 'ready' && <details className="chat-inventory">
        <summary>Dream account data · {workspace.datasets.length} datasets · {workspace.fine_tuning_jobs.length} jobs</summary>
        <div>
          <p>{hosted ? 'Read from the Dream Labs account you connected.' : 'Read from Dream’s API with the locally configured key.'}</p>
          <h3>Datasets</h3>
          <ul>{workspace.datasets.map((item) => <li key={item.id}>{item.name} · {item.status}</li>)}</ul>
          <h3>Fine-tuning jobs</h3>
          <ul>{workspace.fine_tuning_jobs.map((item) => <li key={item.id}>{item.name} · {item.status}</li>)}</ul>
          <div className="chat-inventory-links">
            {!hosted && <>
              <a href="/api/docs/apple-training" target="_blank" rel="noreferrer">Committed apple dataset and training record</a>
              <a href="/api/docs/apple-evaluation" target="_blank" rel="noreferrer">Measured 500-step comparison</a>
            </>}
            <button className="secondary" onClick={() => open('statistical')}>Open existing apple audit</button>
          </div>
        </div>
      </details>}
      {begun && reply?.setup_help === 'robot' && <div className="chat-action chat-setup-help"><strong>Robot setup</strong><p>Connect the arms and cameras, then run Preflight to confirm fresh camera frames before a baseline trial.</p><button className="secondary" onClick={() => open('preflight')}>Check arms and cameras</button><a href="https://platform.dreamlabs.ai/setup" target="_blank" rel="noreferrer">Dream robot setup guide</a></div>}
      {simulatorRequested && <YamChatWorkflow
        setup={simulator} dreamReady={dreamAccess === 'ready'} job={yamJob}
        pipeline={currentYamTask || simulatorMode !== 'apple' ? pipeline : null}
        existingCheckpoint={existingCheckpoint}
        mode={simulatorMode}
        setMode={chooseSimulatorMode}
        openRecorder={openRecorder}
        prepare={prepareSimulator}
        collect={(scenes) => runYamAction('/api/simulator/collect', { scenes })}
        reuseDemos={() => runYamAction('/api/simulator/collect', { source: 'bundled' })}
        compare={(jobId) => runYamAction('/api/simulator/compare', { task_id: activeTaskId, job_id: jobId, pairs: 4 })}
        compareExisting={(checkpoint) => runYamAction('/api/simulator/compare-existing', { checkpoint })}
        stop={() => runYamAction('/api/simulator/workflow/stop')}
        review={() => openWork('demos', simulatorMode === 'apple' ? yamJob?.task_id || activeTaskId : activeTaskId)}
        training={() => openWork('training')}
        explainComparison={hostedGuide ? undefined : () => {
          if (busy) return;
          const history: Message[] = [...messages, { role: 'user', content: 'Explain this simulator comparison and suggest what to do next.' }];
          setMessages(history);
          void turn(history);
        }}
      />}
      {begun && reply?.task_draft && reply.setup_help !== 'simulator' && <div className="chat-action"><strong>Ready to save this task?</strong><p>{reply.task_draft.name} · {reply.task_draft.prompt}<br />Success: {reply.task_draft.success_rule}</p><button disabled={busy} onClick={() => void saveTask(reply.task_draft!)}>Confirm and save task</button></div>}
      {begun && reply?.suggested_screen && reply.suggested_screen !== 'tasks' && !(simulatorRequested
        && (['demos', 'training'].includes(reply.suggested_screen) || (simulatorMode === 'apple' && reply.suggested_screen === 'evaluation')))
        && <div className="chat-action"><button className="secondary" onClick={() => {
          const target = reply.suggested_screen;
          if (target === 'demos' || target === 'training') openWork(target);
          else if (target) open(target);
        }}>{reply.suggested_screen === 'demos' ? 'Review demos' : reply.suggested_screen === 'training'
          ? 'Open fine-tuning' : `Open ${reply.suggested_screen}`}</button></div>}
      {begun && !needsHostedConnection && !simulatorRequested && <button type="button" className="chat-simulator-link" onClick={() => setShowSimulator(true)}>Use the YAM simulator</button>}
      {begun && !needsHostedConnection && hostedGuide && <details className="chat-inventory">
        <summary>Enable optional AI chat</summary>
        <p>Use your own OpenAI API key for conversational guidance.</p>
        <form className="chat-secret" onSubmit={(event) => void enableHostedAi(event)}>
          <input aria-label="OpenAI API key" placeholder="OpenAI API key" type="password" autoComplete="off" maxLength={300}
            value={hostedAiKey} onChange={(event) => setHostedAiKey(event.target.value)} />
          <button type="submit" disabled={busy || !hostedAiKey.trim()}>Enable chat</button>
        </form>
      </details>}
      {demoApproval && <section className="chat-action chat-workspace-return" aria-label="Demo saved">
        <div role="status"><strong>Demo kept</strong><p>{demoApproval.remaining
          ? `${demoApproval.kept} kept · ${demoApproval.remaining} still to review.`
          : `${demoApproval.kept} kept. Next, validate a dataset for fine-tuning.`}</p></div>
        <div className="chat-workspace-actions">
          {demoApproval.remaining > 0 && <button type="button" className="secondary" onClick={() => openWork('demos', demoApproval.taskId)}>Review next demo</button>}
          <button type="button" onClick={() => openWork('training', demoApproval.taskId)}>Open fine-tuning</button>
        </div>
      </section>}
      {comparisonReady && <section className="chat-action chat-workspace-return" aria-label="Checkpoint ready">
        <div role="status"><strong>Fine-tune ready</strong><p>{comparisonReady.yam === null ? 'Checking evaluation options…' : comparisonReady.yam
          ? 'Compare the base and fine-tuned models on the same four simulator scenes. This may use Dream credits.'
          : 'Compare your new checkpoint with the base model on held-out scenes.'}</p></div>
        {comparisonReady.yam !== null && (comparisonReady.yam
          ? <button type="button" disabled={comparisonStarting} onClick={() => void compareReadyCheckpoint(comparisonReady.taskId, comparisonReady.jobId)}>
            {comparisonStarting ? 'Starting comparison…' : 'Run simulator comparison'}
          </button>
          : <button type="button" onClick={() => openEvaluation(comparisonReady.taskId)}>Plan evaluation</button>)}
      </section>}
      </>}
      </div>
      {replySuggestions.length > 0 && <div className="chat-suggestions" role="group" aria-label="Suggested replies">
        <span>Suggested replies</span>
        <div>{replySuggestions.map((prompt, index) => (
          <button type="button" className="secondary" key={`${prompt}-${index}`}
            aria-pressed={text === prompt}
            onClick={() => { setText(prompt); composer.current?.focus(); }}>
            {prompt}
          </button>
        ))}</div>
      </div>}
      {!workSurface && !begun && (hosted || (ai?.configured && messages.length > 0)) && <div className="chat-begin">
        <p id="chat-begin-description">First, we’ll check Dream Labs access.</p>
        <button type="button" aria-describedby="chat-begin-description" disabled={busy} onClick={beginConversation}>
          Begin<span className="chat-begin-arrow" aria-hidden="true">→</span>
        </button>
      </div>}
      {!workSurface && begun && !hostedGuide && <form onSubmit={(event) => void submit(event)} className="chat-composer"><textarea ref={composer} aria-label="Message to coach" disabled={!ai?.configured} value={text} maxLength={2000} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit(event); } }} placeholder="Tell me about your robot or ask what to do next…" /><button disabled={!ai?.configured || busy || !text.trim()}>Send</button></form>}
    </section>
    {!needsHostedConnection && <LiveEvaluation taskId={activeTaskId} simulatorActive={!!simulatorRequested && simulatorMode === 'apple'} onOpen={openEvaluation} onOpenAudit={() => open('statistical')} />}
    </div>
  </main>;
}
