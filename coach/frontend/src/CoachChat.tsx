import { useEffect, useRef, useState } from 'react';
import LiveEvaluation, { useLiveEvaluation } from './LiveEvaluation';
import ChatDemoReview, { type DemoKeepReceipt } from './ChatDemoReview';
import ChatTraining from './ChatTraining';
import ChatCheckpointPicker from './ChatCheckpointPicker';
import ChatToolPanel, { type ChatTool } from './ChatToolPanel';
import SceneTask, { type ScenePreset } from './SceneTask';
import SimCorrect from './SimCorrect';
import type { PairedReport } from './StatisticalAudit';
import YamChatWorkflow, { type SimulatorMode, type TaskPipeline, type YamComparisonDiagnostics, type YamJob } from './YamChatWorkflow';
import { YamComparisonPlan } from './YamComparisonExplanation';

type Screen = 'preflight' | 'tasks' | 'demos' | 'training' | 'evaluation' | 'statistical';
type Message = { role: 'user' | 'assistant'; content: string; answerOptions?: string[] };
type TaskDraft = { name: string; prompt: string; success_rule: string };
type Reply = { message: string; input_kind: 'text' | 'dream_key'; suggested_screen: Screen | null; task_draft: TaskDraft | null; suggestions: string[]; setup_help: 'robot' | 'simulator' | null };
type Account = { configured: boolean; source: string; dashboard_url: string };
type Task = TaskDraft & { id: string; baseline_checkpoint: string };
type Status = { configured: boolean; source: string };
type Simulator = { state: string; message: string };
type WorkSurface =
  | { kind: 'demos'; taskId: string; demoId?: string }
  | { kind: 'training'; taskId: string }
  | { kind: 'scene'; preset?: ScenePreset }
  | { kind: 'fruit' }
  | { kind: 'checkpoints'; preferredCheckpoint?: string }
  | { kind: 'tool'; tool: ChatTool };
const hosted = Boolean(document.querySelector('meta[name="dreamcoach-mode"][content="hosted"]'));

const simulatorHelpPattern = /simulator screen|set up the YAM simulator/i;
const trialExplanationPattern = /diagnos|what went wrong|(?:why|explain).*(?:run|trial|comparison|pick|scene|grasp|fail|result|miss|robot)/i;

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
    const result: unknown = JSON.parse(sessionStorage.getItem('coach-chat-v3') || '[]');
    return Array.isArray(result) ? result.filter((item): item is Message => item && (item.role === 'user' || item.role === 'assistant') && typeof item.content === 'string').slice(-24) : [];
  } catch { return []; }
}

export default function CoachChat({
  resetSession, activeTaskId, selectTask, showSimulatorOnOpen,
  simulatorMode, chooseSimulatorMode, demoApproval, clearDemoApproval, onDemoKept,
}: {
  resetSession: () => void;
  activeTaskId: string;
  selectTask: (taskId: string) => void;
  showSimulatorOnOpen: boolean;
  simulatorMode: SimulatorMode;
  chooseSimulatorMode: (mode: SimulatorMode) => void;
  demoApproval: DemoKeepReceipt | null;
  clearDemoApproval: () => void;
  onDemoKept: (receipt: DemoKeepReceipt) => void;
}) {
  const [messages, setMessages] = useState<Message[]>(savedMessages);
  const [reply, setReply] = useState<Reply | null>(null);
  const [ai, setAi] = useState<Status | null>(null);
  const [account, setAccount] = useState<Account | null>(null);
  const [simulator, setSimulator] = useState<Simulator | null>(null);
  const [yamJob, setYamJob] = useState<YamJob | null>(null);
  const [pipeline, setPipeline] = useState<(TaskPipeline & { taskId: string }) | null>(null);
  const [workflowTask, setWorkflowTask] = useState<Task>();
  const [workSurface, setWorkSurface] = useState<WorkSurface | null>(null);
  const [comparisonReady, setComparisonReady] = useState<{ taskId: string; jobId: string; yam: boolean | null } | null>(null);
  const [yamActionPending, setYamActionPending] = useState(false);
  const [showSimulator, setShowSimulator] = useState(showSimulatorOnOpen);
  const [dreamAccess, setDreamAccess] = useState('unknown');
  const [text, setText] = useState('');
  const [secret, setSecret] = useState('');
  const [hostedAiKey, setHostedAiKey] = useState('');
  const [copiedAddress, setCopiedAddress] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [simulatorNotice, setSimulatorNotice] = useState('');
  const [begun, setBegun] = useState(sessionStorage.getItem('coach-begun-v3') === 'yes');
  const evaluationTaskId = begun ? activeTaskId : '';
  const currentYamJob = activeTaskId && yamJob?.task_id === activeTaskId ? yamJob : null;
  const comparisonId = currentYamJob?.kind === 'comparison' ? currentYamJob.id : undefined;
  const evaluation = useLiveEvaluation(evaluationTaskId, comparisonId);
  const thread = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const started = useRef(false);
  const sessionVersion = useRef(0);
  const yamActionVersion = useRef(0);

  useEffect(() => {
    sessionStorage.setItem('coach-chat-v3', JSON.stringify(messages.slice(-24)));
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
  useEffect(() => { sessionStorage.setItem('coach-begun-v3', begun ? 'yes' : 'no'); }, [begun]);
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
    if (!begun || !activeTaskId) return;
    let cancelled = false;
    let timer: number;
    async function poll() {
      const startingActionVersion = yamActionVersion.current;
      try {
        const root = `/api/tasks/${activeTaskId}`;
        const [next, demos, datasets, jobs] = await Promise.all([
          api<YamJob | null>('/api/simulator/workflow').catch(() => null),
          api<{ decision: string }[]>(`${root}/demos`),
          api<{ status: string }[]>(`${root}/datasets`),
          api<NonNullable<TaskPipeline['job']>[]>(`${root}/finetunes`),
        ]);
        if (cancelled) return;
        if (startingActionVersion === yamActionVersion.current) {
          setYamJob(next?.task_id === activeTaskId ? next : null);
        }
        setPipeline({
          taskId: activeTaskId,
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
  }, [begun, activeTaskId]);
  useEffect(() => {
    if (!begun && !started.current) {
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

  async function workflowState(taskId = activeTaskId, mode = simulatorMode, includeTrialDiagnoses = false) {
    const version = sessionVersion.current;
    const [dream, preflight, current, sim, latestWorkflow] = await Promise.all([
      api<Account>('/api/account/status'),
      api<{ dream: { state: string; message: string }; station: { state: string; message: string }; models: { id: string; servable: boolean }[] }>('/api/preflight'),
      taskId ? api<Task>(`/api/tasks/${taskId}`) : null,
      api<Simulator>('/api/simulator/status'),
      taskId ? api<YamJob | null>('/api/simulator/workflow') : null,
    ]);
    const workflow = latestWorkflow?.task_id === taskId ? latestWorkflow : null;
    const models = preflight.models.filter((model) => model.servable).map((model) => model.id);
    if (version === sessionVersion.current) {
      setAccount(dream);
      setSimulator(sim);
      setDreamAccess(preflight.dream.state);
      setWorkflowTask(current ?? undefined);
    }
    const taskData = current ? await Promise.all([
      api<{ phase: string; next_action: string; evidence: string[] }>(`/api/tasks/${current.id}/guidance`),
      api<{ decision: string }[]>(`/api/tasks/${current.id}/demos`),
      api<{ status: string }[]>(`/api/tasks/${current.id}/datasets`),
      api<{ status: string; checkpoint: string | null }[]>(`/api/tasks/${current.id}/finetunes`),
      api<unknown[]>(`/api/tasks/${current.id}/evaluations`),
      api<{ report: PairedReport } | null>(`/api/simulator/comparisons/${current.id}`),
    ]) : null;
    const savedReport = taskData?.[5]?.report ?? null;
    const report = workflow?.kind === 'comparison' && savedReport?.evaluation_id !== workflow.id ? null : savedReport;
    const diagnostics = includeTrialDiagnoses && current && report
      ? await api<YamComparisonDiagnostics | null>(`/api/simulator/comparisons/${current.id}/diagnostics`).catch(() => null)
      : null;
    const pairedDiagnoses = report && diagnostics?.evaluation_id === report.evaluation_id
      ? report.pairs.flatMap((pair, index) => (['baseline', 'candidate'] as const).flatMap((model) => {
        const attempt = pair[model];
        if (!attempt) return [];
        const diagnosis = diagnostics.trials[attempt.trial_id];
        return diagnosis ? [{ scene: index + 1, model, outcome: attempt.outcome, diagnosis }] : [];
      }))
      : [];
    const trialDiagnoses = includeTrialDiagnoses ? [
      ...pairedDiagnoses,
      ...(workflow?.training_trial_diagnostics ?? []).map(({ scene, diagnosis }) => ({
        scene, model: 'baseline', outcome: undefined, diagnosis,
      })),
    ].slice(0, 8).map(({ diagnosis, ...trial }) => ({
      ...trial, ...diagnosis, evidence: diagnosis.evidence.slice(0, 2),
    })) : [];
    return {
      simulator_mode: mode,
      simulator_trial_diagnostics: trialDiagnoses,
      simulator_comparison: report ? {
        decision: report.decision,
        baseline_successes: report.baseline_successes, baseline_attempted: report.baseline_attempted,
        candidate_successes: report.candidate_successes, candidate_attempted: report.candidate_attempted,
        usable_pairs: report.usable_pairs, planned_pairs: report.planned_pairs,
        observed_difference: report.observed_difference, problems: report.problems,
      } : null,
      simulator_workflow: workflow ? {
        task_id: workflow.task_id, kind: workflow.kind, status: workflow.state,
        completed: workflow.completed, total: workflow.total, demos: workflow.demos,
        activity: workflow.message,
        comparison_protocol: workflow.kind === 'comparison' ? {
          models: 'base Dream-1 and the selected fine-tune',
          trials: workflow.total * 2,
          pair: 'One attempt per model from the same simulator starting state on a scene held out from training.',
          progress: 'A pair counts after both attempts finish, whether they succeed or fail.',
          success_rule: 'Lift the apple at least 8 cm above its starting height and hold it there for two continuous seconds.',
        } : undefined,
      } : null,
      current_task: current ? { id: current.id, name: current.name, guidance: taskData?.[0],
        kept_demos: taskData?.[1].filter((demo) => demo.decision === 'keep').length,
        dataset_count: taskData?.[2].length, training_jobs: taskData?.[3].map((job) => ({ status: job.status, checkpoint: job.checkpoint })),
        evaluations: taskData?.[4].length } : null,
      dream_connected: preflight.dream.state === 'ready', dream_api_ready: preflight.dream.state === 'ready',
      local_api_key_configured: dream.configured, browser_login_checked: false,
      dream_preflight: preflight.dream,
      bundled_example: { task: 'YAM apple pickup', simulator_status: sim.state,
        new_failure_conditioned_sim_collection_available: true },
      robot_station: preflight.station, available_models: models.filter((id) => id.startsWith('dreamlabs/')).slice(0, 8),
      tasks: current ? [{ id: current.id, name: current.name, baseline_checkpoint: current.baseline_checkpoint }] : [],
    };
  }

  async function turn(history: Message[], stage: 'introduction' | 'guide' = 'guide', taskId?: string, mode?: SimulatorMode) {
    const version = sessionVersion.current;
    setBusy(true); setError('');
    try {
      const lastMessage = history[history.length - 1];
      const state = stage === 'introduction' ? { introduction_only: true } : await workflowState(
        taskId, mode, lastMessage?.role === 'user' && trialExplanationPattern.test(lastMessage.content),
      );
      if (version !== sessionVersion.current) return;
      const transcript = history.slice(-24).map(({ role, content }) => ({ role, content }));
      const result = await api<Reply>('/api/assistant/chat', 'POST', { messages: transcript, state, stage });
      if (version !== sessionVersion.current) return;
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
    } catch (caught) {
      if (version === sessionVersion.current) setError(caught instanceof Error ? caught.message : 'The coach could not reply.');
    } finally {
      if (version === sessionVersion.current) setBusy(false);
    }
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

  async function saveTask(draft: TaskDraft) {
    setBusy(true); setError('');
    try {
      const preflight = await api<{ models: { id: string; servable: boolean }[] }>('/api/preflight');
      const checkpoint = preflight.models.find((model) => model.servable && model.id.startsWith('dreamlabs/'))?.id
        || 'dreamlabs/dream-1';
      const task = await api<Task>('/api/tasks', 'POST', { ...draft, baseline_checkpoint: checkpoint });
      selectTask(task.id);
      setWorkflowTask(task);
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
    if (yamActionPending) return false;
    const version = sessionVersion.current;
    yamActionVersion.current += 1;
    setYamActionPending(true);
    setError('');
    setSimulatorNotice('');
    try {
      const job = await api<YamJob | null>(path, 'POST', body);
      if (version !== sessionVersion.current) return false;
      setYamJob(job);
      if (job) {
        clearDemoApproval();
        setComparisonReady(null);
        chooseSimulatorMode('apple');
        selectTask(job.task_id);
        if (job.kind === 'comparison' && job.state === 'running') {
          setMessages((history) => [...history, {
            role: 'assistant',
            content: 'I’ve started the YAM comparison. I’ll show each model’s result as its trial finishes, then summarize how they did on the same scenes.',
          }]);
        }
      }
      return true;
    } catch (caught) {
      if (version === sessionVersion.current) setError(caught instanceof Error ? caught.message : 'Could not run the simulator action.');
      return false;
    } finally {
      yamActionVersion.current += 1;
      if (version === sessionVersion.current) setYamActionPending(false);
    }
  }

  async function quitYam() {
    if (await runYamAction('/api/simulator/workflow/quit')) setSimulatorNotice('Simulator run stopped.');
  }

  function showWork(surface: WorkSurface) {
    setError('');
    clearDemoApproval();
    setComparisonReady(null);
    setWorkSurface(surface);
  }

  function openWork(kind: 'demos' | 'training', taskId = activeTaskId, demoId?: string) {
    if (!taskId) {
      setError('Save a task in chat before reviewing demos or training.');
      return;
    }
    if (taskId !== activeTaskId) selectTask(taskId);
    showWork(kind === 'demos' ? { kind, taskId, demoId } : { kind, taskId });
  }

  function openRecorder(kind: 'fruit' | 'scene', preset?: ScenePreset) {
    chooseSimulatorMode(kind);
    showWork(kind === 'scene' ? { kind, preset } : { kind });
  }

  async function saveSimulatorTask(draft: TaskDraft) {
    const version = sessionVersion.current;
    const task = await api<Task>('/api/tasks', 'POST', { ...draft, baseline_checkpoint: 'dreamlabs/dream-1-beta' });
    if (version !== sessionVersion.current) return;
    selectTask(task.id);
    setWorkflowTask(task);
  }

  function closeWork() {
    setWorkSurface(null);
  }

  function openEvaluation(taskId = activeTaskId, evaluationId?: string) {
    showWork({ kind: 'tool', tool: { kind: 'evaluation', taskId, evaluationId } });
  }

  async function copyAddress(address: string) {
    try {
      await navigator.clipboard.writeText(address);
      setCopiedAddress(address);
    } catch {
      setError('Copy the address shown in chat.');
    }
  }

  function finishReview(receipt: DemoKeepReceipt) {
    setWorkSurface(null);
    setReply(null);
    setPipeline((current) => ({
      taskId: receipt.taskId,
      kept: receipt.kept,
      unreviewed: receipt.remaining,
      validated: current?.taskId === receipt.taskId && current.validated,
      job: current?.taskId === receipt.taskId ? current.job : undefined,
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

  function resetConversation() {
    sessionVersion.current += 1;
    resetSession();
    setReply(null);
    setText('');
    setSecret('');
    setHostedAiKey('');
    setCopiedAddress('');
    setError('');
    setShowSimulator(false);
    setWorkSurface(null);
    setYamJob(null);
    setPipeline(null);
    setWorkflowTask(undefined);
    setComparisonReady(null);
    setYamActionPending(false);
    setDreamAccess('unknown');
    setSimulatorNotice('');
    for (const key of ['coach-chat-v2', 'coach-begun-v2', 'coach-active-task', 'coach-simulator-mode']) {
      sessionStorage.removeItem(key);
    }
    for (const key of Object.keys(sessionStorage)) {
      if (key.startsWith('dreamcoach-simulator-recording:')) sessionStorage.removeItem(key);
    }
  }

  async function beginConversation() {
    if (busy) return;
    const welcome = messages.length === 1 && messages[0].role === 'assistant' ? messages : [];
    resetConversation();
    setMessages(welcome);
    setBusy(true);
    try {
      await api('/api/simulator/session/reset', 'POST');
      setBegun(true);
      if (hosted && !ai?.configured) {
        setShowSimulator(true);
        await workflowState('', 'apple');
        return;
      }
      const history: Message[] = [...welcome, {
        role: 'user',
        content: 'Begin. Please check my Dream Labs connection and guide me one step at a time.',
      }];
      setMessages(history);
      await turn(history, 'guide', '', 'apple');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not start a fresh simulator session.');
    } finally {
      setBusy(false);
    }
  }

  function startOver() {
    if (yamActionPending) return;
    started.current = true;
    resetConversation();
    setBegun(false);
    setMessages([]);
    if (ai?.configured) void turn([], 'introduction');
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

  const hostedGuide = hosted && ai?.configured === false;
  const comparedCheckpoint = evaluation.simulation?.candidate;
  const currentTask = activeTaskId && workflowTask?.id === activeTaskId ? workflowTask : undefined;
  const currentPipeline = pipeline?.taskId === activeTaskId ? pipeline : null;
  const simulatorRequested = begun && (hostedGuide || showSimulator || currentYamJob || simulatorMode !== 'apple'
    || reply?.setup_help === 'simulator' || simulatorHelpPattern.test(reply?.message ?? ''));
  const needsDreamKey = begun && account && (!account.configured || dreamAccess === 'blocked' || dreamAccess === 'unavailable');
  const latestMessage = messages[messages.length - 1];
  const replySuggestions = begun && ai?.configured && !busy && !simulatorRequested && !needsDreamKey
    && !workSurface && !demoApproval && !comparisonReady
    && latestMessage?.role === 'assistant' && Array.isArray(latestMessage.answerOptions)
    ? latestMessage.answerOptions.filter((suggestion) => typeof suggestion === 'string' && suggestion.trim())
    : [];

  function renderWorkspace(surface: WorkSurface) {
    switch (surface.kind) {
      case 'demos':
        return <ChatDemoReview key={surface.demoId ?? surface.taskId} taskId={surface.taskId}
          initialDemoId={surface.demoId} onClose={closeWork} onKeep={finishReview} />;
      case 'training':
        return <ChatTraining key={surface.taskId} taskId={surface.taskId} onClose={closeWork}
          onCheckpointReady={(jobId) => void finishTraining(surface.taskId, jobId)} />;
      case 'tool':
        return <ChatToolPanel tool={surface.tool} onClose={closeWork} />;
      case 'checkpoints':
        return <ChatCheckpointPicker onClose={closeWork} preferredCheckpoint={surface.preferredCheckpoint}
          onCompare={async (checkpoint) => {
            const started = await runYamAction('/api/simulator/compare-existing', { checkpoint });
            if (started) closeWork();
            return started;
          }} />;
      case 'scene':
      case 'fruit': {
        const props = {
          taskId: currentTask?.id ?? '',
          taskPrompt: currentTask?.prompt ?? '',
          taskSuccessRule: currentTask?.success_rule ?? '',
          onSetupTask: saveSimulatorTask,
          onComplete: (demoId: string) => {
            if (currentTask) openWork('demos', currentTask.id, demoId);
          },
          inline: true,
        };
        return <section className="chat-inline-workspace chat-recorder" aria-label="Simulator recorder">
          <header className="chat-workspace-header">
            <h2>{surface.kind === 'scene' ? 'Scene setup' : 'Fruit correction'}</h2>
            <button type="button" className="secondary" onClick={closeWork}>Back to chat</button>
          </header>
          {surface.kind === 'scene' ? <SceneTask {...props} initialPreset={surface.preset} /> : <SimCorrect {...props} />}
        </section>;
      }
    }
  }

  return <main className="page chat-page">
    <header className="header"><div><h1>DreamCoach</h1><p className="subtitle">Fine-tune Dream-1 for a task and measure how it performs.</p></div></header>
    {error && <div className="alert" role="alert">{error}</div>}
    <div className="chat-layout">
    <section className="card chat-shell" aria-label="Fine-tuning coach conversation">
      <div className={`chat-landscape${hosted ? ' hosted-landscape' : ''}`} aria-hidden="true">{!hosted && <video autoPlay loop muted playsInline poster="/dream/sunrise-hd-poster.webp"><source src="/dream/sunrise-hd.mp4" type="video/mp4" /></video>}<span className="chat-spark chat-spark-one">✦</span><span className="chat-spark chat-spark-two">✦</span></div>
      <div className="chat-panel-top">
        <span className="chat-landscape-title">Conversation</span>
        {begun && !workSurface && <button type="button" className="chat-reset" disabled={busy || yamActionPending} onClick={startOver}>Start over</button>}
      </div>
      <div className={`chat-thread${workSurface ? ' chat-thread-workspace' : ''}`} ref={thread}
        aria-live={workSurface ? undefined : 'polite'} tabIndex={workSurface ? -1 : undefined}>
      {workSurface ? renderWorkspace(workSurface) : <>
        {hostedGuide && !begun && <div className="chat-bubble chat-assistant"><span>DreamCoach</span><p>I’ll guide you from YAM demos to a fine-tune and a measured comparison. Press Begin to choose a simulator workflow.</p></div>}
        {!hosted && ai && !ai.configured && <div className="chat-bubble chat-assistant"><span>DreamCoach</span><p>The AI coach is unavailable on this server. Ask the operator to configure its AI credential, then refresh this page.</p></div>}
        {messages.map((item, index) => <div key={index} className={`chat-bubble chat-${item.role}`}><span>{item.role === 'assistant' ? 'DreamCoach' : 'You'}</span><p>{item.content}</p></div>)}
        {busy && <div className="chat-bubble chat-assistant"><span>DreamCoach</span>
          <p>{!begun && messages.length ? 'Resetting the YAM simulator…' : 'Thinking through your next step…'}</p>
        </div>}
      {needsDreamKey && <div className="chat-action">
        <p>Create a key in your Dream Labs account at <code>{account.dashboard_url}</code>. Paste it into the private field below. The key stays out of your conversation.</p>
        <button type="button" className="secondary" onClick={() => void copyAddress(account.dashboard_url)}>
          {copiedAddress === account.dashboard_url ? 'Address copied' : 'Copy Dream API keys address'}
        </button>
        <form onSubmit={(event) => void connectDream(event)} className="chat-secret">
          <input aria-label="Dream API key" type="password" autoComplete="off" value={secret}
            onChange={(event) => setSecret(event.target.value)} placeholder="Dream API key" />
          <button disabled={busy || !secret.trim()}>Connect Dream</button>
        </form>
      </div>}
      {begun && reply?.setup_help === 'robot' && <div className="chat-action chat-setup-help">
        <strong>Robot setup</strong>
        <p>Connect the arms and cameras, then check for fresh camera frames before a baseline trial.</p>
        <button className="secondary" onClick={() => showWork({ kind: 'tool', tool: { kind: 'preflight' } })}>Check arms and cameras</button>
      </div>}
      {simulatorNotice && <p className="notice" role="status">{simulatorNotice}</p>}
      {simulatorRequested && <YamChatWorkflow
        setup={simulator} dreamReady={dreamAccess === 'ready'} job={currentYamJob}
        pipeline={currentYamJob || simulatorMode !== 'apple' ? currentPipeline : null}
        comparisonReport={evaluation.simulation?.report ?? null}
        openExistingCheckpoints={() => showWork({ kind: 'checkpoints' })}
        mode={simulatorMode}
        setMode={chooseSimulatorMode}
        openRecorder={openRecorder}
        prepare={prepareSimulator}
        collect={(scenes) => runYamAction('/api/simulator/collect', { scenes })}
        reuseDemos={() => runYamAction('/api/simulator/collect', { source: 'bundled' })}
        compare={(jobId) => runYamAction('/api/simulator/compare', { task_id: activeTaskId, job_id: jobId, pairs: 4 })}
        stop={quitYam}
        review={() => openWork('demos')}
        training={() => openWork('training')}
        planFreshComparison={comparedCheckpoint ? () => showWork({
          kind: 'checkpoints', preferredCheckpoint: comparedCheckpoint,
        }) : undefined}
      />}
      {begun && reply?.task_draft && reply.setup_help !== 'simulator' && <div className="chat-action"><strong>Ready to save this task?</strong><p>{reply.task_draft.name} · {reply.task_draft.prompt}<br />Success: {reply.task_draft.success_rule}</p><button disabled={busy} onClick={() => void saveTask(reply.task_draft!)}>Confirm and save task</button></div>}
      {begun && reply?.suggested_screen && reply.suggested_screen !== 'tasks' && !(simulatorRequested
        && (['demos', 'training'].includes(reply.suggested_screen) || (simulatorMode === 'apple' && reply.suggested_screen === 'evaluation')))
        && <div className="chat-action"><button className="secondary" onClick={() => {
          const target = reply.suggested_screen;
          if (target === 'demos' || target === 'training') openWork(target);
          else if (target === 'evaluation') openEvaluation();
          else if (target === 'preflight' || target === 'statistical') showWork({ kind: 'tool', tool: { kind: target } });
        }}>{reply.suggested_screen === 'demos' ? 'Review demos' : reply.suggested_screen === 'training'
          ? 'Open fine-tuning' : `Open ${reply.suggested_screen}`}</button></div>}
      {begun && !simulatorRequested && <button type="button" className="chat-simulator-link" onClick={() => setShowSimulator(true)}>Use the YAM simulator</button>}
      {begun && hostedGuide && <details className="chat-inventory">
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
        <div role="status"><strong>Fine-tune ready</strong>
          {comparisonReady.yam ? <YamComparisonPlan pairs={4} /> : <p>{comparisonReady.yam === null
            ? 'Checking evaluation options…'
            : 'Compare your new checkpoint with the base model on held-out scenes.'}</p>}
        </div>
        {comparisonReady.yam !== null && (comparisonReady.yam
          ? <button type="button" disabled={yamActionPending} onClick={() => void runYamAction('/api/simulator/compare', {
            task_id: comparisonReady.taskId, job_id: comparisonReady.jobId, pairs: 4,
          })}>
            {yamActionPending ? 'Starting comparison…' : 'Run simulator comparison'}
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
      {!workSurface && !begun && (hostedGuide || (ai?.configured && messages.length > 0)) && <div className="chat-begin">
        <p id="chat-begin-description">First, we’ll check Dream Labs access.</p>
        <button type="button" aria-describedby="chat-begin-description" disabled={busy} onClick={() => void beginConversation()}>
          Begin<span className="chat-begin-arrow" aria-hidden="true">→</span>
        </button>
      </div>}
      {!workSurface && begun && !hostedGuide && <form onSubmit={(event) => void submit(event)} className="chat-composer"><textarea ref={composer} aria-label="Message to coach" disabled={!ai?.configured} value={text} maxLength={2000} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit(event); } }} placeholder="Tell me about your robot or ask what to do next…" /><button disabled={!ai?.configured || busy || !text.trim()}>Send</button></form>}
    </section>
    <LiveEvaluation taskId={evaluationTaskId} simulatorActive={!!simulatorRequested && simulatorMode === 'apple'}
      onOpen={openEvaluation} evidence={evaluation} />
    </div>
  </main>;
}
