import { useEffect, useRef, useState } from 'react';
import LiveEvaluation, { useLiveEvaluation } from './LiveEvaluation';
import ChatDemoReview, { type DemoKeepReceipt } from './ChatDemoReview';
import ChatTraining from './ChatTraining';
import ChatCheckpointPicker from './ChatCheckpointPicker';
import ChatResumePicker from './ChatResumePicker';
import ChatToolPanel, { type ChatTool } from './ChatToolPanel';
import SceneTask, { type ScenePreset } from './SceneTask';
import SimCorrect from './SimCorrect';
import type { PairedReport } from './StatisticalAudit';
import YamChatWorkflow, { simulatorWorkflows, type SimulatorMode, type TaskPipeline, type YamComparisonDiagnostics, type YamGoal, type YamJob } from './YamChatWorkflow';
import { YamComparisonPlan, yamSuccessRule } from './YamComparisonExplanation';

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
  | { kind: 'checkpoints'; goal: YamGoal; preferredCheckpoint?: string }
  | { kind: 'resume' }
  | { kind: 'tool'; tool: ChatTool };
const hosted = Boolean(document.querySelector('meta[name="dreamcoach-mode"][content="hosted"]'));
const hostedIntroduction = document.querySelector<HTMLMetaElement>('meta[name="dreamcoach-introduction"]')
  ?.content.replace('Watch results in the sidebar', 'Open Evaluation results after connecting')
  ?? 'Hi, I’m DreamCoach. I’ll help you record YAM demos, fine-tune Dream-1, and evaluate the result. Press Begin to get started.';

const simulatorHelpPattern = /simulator screen|set up the YAM simulator/i;
const trialExplanationPattern = /diagnos|what went wrong|(?:why|explain).*(?:run|trial|comparison|pick|scene|grasp|fail|result|miss|robot)/i;

function taskSimulatorMode(task: Task | undefined): SimulatorMode | undefined {
  if (task?.name === 'Apple pickup · YAM simulator') return 'apple';
  if (task?.name.endsWith(' · click to correct')) return 'fruit';
  if (task?.name.endsWith(' · YAM scene')) return 'scene';
}

function taskComparisonGoal(task: Task | undefined): YamGoal | undefined {
  if (taskSimulatorMode(task) === 'apple') return 'pickup';
  if (task?.prompt.trim().toLowerCase() === 'put the apple in the bowl'
    && task.success_rule === 'Lift the apple, release it into the bowl, and leave it resting inside.') return 'bowl';
}

async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(path, { method, cache: 'no-store', headers: body === undefined ? undefined : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!response.ok) {
    const { detail } = await response.json().catch(() => ({})) as { detail?: unknown };
    const validationErrors = Array.isArray(detail)
      ? detail.flatMap((item) => typeof item?.msg === 'string' ? [item.msg] : []).join(' ')
      : '';
    throw new Error(typeof detail === 'string' && detail ? detail : validationErrors || `Request failed (${response.status})`);
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
  resetSession, onEvidence, activeTaskId, selectTask, showSimulatorOnOpen,
  simulatorMode, chooseSimulatorMode, demoApproval, clearDemoApproval, onDemoKept,
  needsHostedConnection, onHostedConnection,
}: {
  resetSession: () => void;
  onEvidence: () => void;
  activeTaskId: string;
  selectTask: (taskId: string) => void;
  showSimulatorOnOpen: boolean;
  simulatorMode: SimulatorMode;
  chooseSimulatorMode: (mode: SimulatorMode) => void;
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
  const [simulator, setSimulator] = useState<Simulator | null>(null);
  const [yamJob, setYamJob] = useState<YamJob | null>(null);
  const [pipeline, setPipeline] = useState<(TaskPipeline & { taskId: string }) | null>(null);
  const [workflowTask, setWorkflowTask] = useState<Task>();
  const [workSurface, setWorkSurface] = useState<WorkSurface | null>(null);
  const [comparisonReady, setComparisonReady] = useState<{ taskId: string; jobId: string; goal: YamGoal | 'physical' | null } | null>(null);
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
  const [begun, setBegun] = useState(() => !needsHostedConnection && sessionStorage.getItem('coach-begun-v3') === 'yes');
  const evaluationTaskId = begun && !needsHostedConnection ? activeTaskId : '';
  const currentYamJob = activeTaskId && yamJob?.task_id === activeTaskId ? yamJob : null;
  const comparisonId = currentYamJob?.kind === 'comparison' ? currentYamJob.id : undefined;
  const evaluation = useLiveEvaluation(evaluationTaskId, comparisonId);
  const thread = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const hostedStartMode = useRef<SimulatorMode | undefined>(undefined);
  const started = useRef(false);
  const sessionVersion = useRef(0);
  const yamActionVersion = useRef(0);

  useEffect(() => {
    sessionStorage.setItem('coach-chat-v3', JSON.stringify(messages.slice(-24)));
    const content = thread.current;
    if (!workSurface && content) content.scrollTo({ top: begun ? content.scrollHeight : 0 });
  }, [messages, workSurface, begun]);
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
    if (needsHostedConnection) return;
    void Promise.all([api<Status>('/api/assistant/status'), api<Account>('/api/account/status')])
      .then(([aiStatus, dreamStatus]) => { setAi(aiStatus); setAccount(dreamStatus); })
      .catch((caught: Error) => setError(caught.message));
    void api<Simulator>('/api/simulator/status').then(setSimulator).catch(() => undefined);
  }, [needsHostedConnection]);
  useEffect(() => {
    if (simulator?.state !== 'preparing') return;
    const timer = window.setInterval(() => { void api<Simulator>('/api/simulator/status').then(setSimulator).catch(() => undefined); }, 1500);
    return () => window.clearInterval(timer);
  }, [simulator?.state]);
  useEffect(() => {
    if (!begun || needsHostedConnection || !activeTaskId) return;
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
  }, [begun, activeTaskId, needsHostedConnection]);
  useEffect(() => {
    if (!hosted && !begun && !started.current) {
      started.current = true;
      void turn([], 'introduction');
    }
  // Refresh the local welcome for sessions that have not clicked Begin.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [begun]);
  useEffect(() => { if (messages.length > 0 && begun && !needsHostedConnection) void workflowState().catch(() => undefined);
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
    const comparisonQuery = workflow?.kind === 'comparison' ? `?evaluation_id=${encodeURIComponent(workflow.id)}` : '';
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
      api<{ report: PairedReport; goal?: YamGoal } | null>(`/api/simulator/comparisons/${current.id}${comparisonQuery}`),
    ]) : null;
    const savedReport = taskData?.[5]?.report ?? null;
    const report = workflow?.kind === 'comparison' && savedReport?.evaluation_id !== workflow.id ? null : savedReport;
    const diagnostics = includeTrialDiagnoses && current && report
      ? await api<YamComparisonDiagnostics | null>(`/api/simulator/comparisons/${current.id}/diagnostics?evaluation_id=${encodeURIComponent(report.evaluation_id)}`).catch(() => null)
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
        task: taskData?.[5]?.goal === 'bowl' ? 'apple into bowl' : 'apple pickup',
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
          success_rule: yamSuccessRule(workflow.goal),
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
      if (guidedMode) {
        await workflowState();
        return;
      }
      const history: Message[] = [...messages, { role: 'user', content: 'I connected my Dream Labs account successfully.' }];
      setMessages(history);
      await turn(history);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not connect Dream Labs.'); }
    finally { setBusy(false); }
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
      const mode = hostedStartMode.current ?? 'apple';
      hostedStartMode.current = undefined;
      setShowSimulator(true);
      onHostedConnection();
      chooseSimulatorMode(mode);
      await workflowState('', mode);
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
        chooseSimulatorMode(job.goal === 'bowl' ? 'fruit' : 'apple');
        setShowSimulator(true);
        selectTask(job.task_id);
        if (job.kind === 'comparison' && job.state === 'running') {
          setMessages((history) => [...history, {
            role: 'assistant',
            content: path.endsWith('/resume')
              ? 'I’ve resumed the comparison on its original held-out scenes. The evaluation keeps the valid results and continues with the remaining trials.'
              : `I’ve started the ${job.goal === 'bowl' ? 'apple-into-bowl' : 'apple pickup'} comparison. I’ll show each model’s result as its trial finishes, then summarize how they did on the same scenes.`,
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
    if (await runYamAction('/api/simulator/workflow/quit')) {
      setSimulatorNotice(currentYamJob?.kind === 'comparison'
        ? 'Comparison stopped. Its valid results are available under Resume a saved comparison.'
        : 'Simulator run stopped.');
    }
  }

  function resumeYam(taskId: string, comparisonId: string) {
    return runYamAction(`/api/simulator/comparisons/${encodeURIComponent(taskId)}/${encodeURIComponent(comparisonId)}/resume`);
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

  function switchSimulatorMode(mode: SimulatorMode) {
    if (mode === simulatorMode) return;
    clearDemoApproval();
    setComparisonReady(null);
    chooseSimulatorMode(mode);
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

  function openTool(tool: ChatTool) {
    setError('');
    setWorkSurface({ kind: 'tool', tool });
  }

  function selectToolTask(taskId: string) {
    selectTask(taskId);
    void workflowState(taskId).catch((caught: Error) => setError(caught.message));
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
    const goal = yamJob?.task_id === taskId ? yamJob.goal ?? 'pickup'
      : workflowTask?.id === taskId ? taskComparisonGoal(workflowTask) ?? 'physical' : null;
    setWorkSurface(null);
    setComparisonReady({ taskId, jobId, goal });
    if (goal !== null) return;
    try {
      const task = await api<Task>(`/api/tasks/${taskId}`);
      setComparisonReady((current) => current?.jobId === jobId ? { ...current, goal: taskComparisonGoal(task) ?? 'physical' } : current);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not check this task’s evaluation options.');
      setComparisonReady((current) => current?.jobId === jobId ? { ...current, goal: 'physical' } : current);
    }
  }

  function resetConversation() {
    sessionVersion.current += 1;
    hostedStartMode.current = undefined;
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

  async function beginConversation(mode?: SimulatorMode) {
    if (busy || !canBegin) return;
    const welcome = messages.length === 1 && messages[0].role === 'assistant' ? messages : [];
    resetConversation();
    setMessages(welcome);
    if (needsHostedConnection) {
      hostedStartMode.current = mode;
      setBegun(true);
      return;
    }
    setBusy(true);
    try {
      await api('/api/simulator/session/reset', 'POST');
      setBegun(true);
      if (guidedMode || mode) {
        const selectedMode = mode ?? 'apple';
        chooseSimulatorMode(selectedMode);
        setShowSimulator(true);
        await workflowState('', selectedMode);
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
    if (!hosted) void turn([], 'introduction');
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
        role: 'user', content: 'Continue guiding my YAM simulator workspace.',
      }];
      setMessages(history);
      await turn(history);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not enable AI chat.');
    } finally {
      setBusy(false);
    }
  }

  const guidedMode = ai?.configured === false || (hosted && !ai?.configured);
  const canBegin = hosted || ai !== null;
  const comparedCheckpoint = evaluation.simulation?.candidate;
  const currentTask = activeTaskId && workflowTask?.id === activeTaskId ? workflowTask : undefined;
  const comparisonGoal = currentYamJob ? currentYamJob.goal ?? 'pickup' : taskComparisonGoal(currentTask);
  const currentTaskMode = comparisonGoal === 'bowl' ? 'fruit' : currentYamJob ? 'apple' : taskSimulatorMode(currentTask);
  const currentPipeline = pipeline?.taskId === activeTaskId ? pipeline : null;
  const simulatorRequested = begun && !needsHostedConnection && (guidedMode || showSimulator || currentYamJob || simulatorMode !== 'apple'
    || reply?.setup_help === 'simulator' || simulatorHelpPattern.test(reply?.message ?? ''));
  const needsDreamKey = !hosted && begun && account && (!account.configured || dreamAccess === 'blocked' || dreamAccess === 'unavailable');
  const suggestedScreen = reply?.suggested_screen;
  const showSuggestedTool = begun && suggestedScreen && (!hosted || suggestedScreen !== 'tasks')
    && !(simulatorRequested && (['demos', 'training', 'tasks'].includes(suggestedScreen)
      || (simulatorMode === 'apple' && suggestedScreen === 'evaluation')));
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
        return <ChatToolPanel tool={surface.tool} onClose={closeWork} onOpen={openTool}
          onTaskSelected={selectToolTask} onWork={openWork} />;
      case 'checkpoints':
        return <ChatCheckpointPicker key={surface.goal} goal={surface.goal} onClose={closeWork} preferredCheckpoint={surface.preferredCheckpoint}
          onCompare={async (checkpoint) => {
            const started = await runYamAction('/api/simulator/compare-existing', { checkpoint, goal: surface.goal });
            if (started) closeWork();
            return started;
          }} />;
      case 'resume':
        return <ChatResumePicker onClose={closeWork} onResume={async (taskId, runId) => {
          const resumed = await resumeYam(taskId, runId);
          if (resumed) closeWork();
          return resumed;
        }} />;
      case 'scene':
      case 'fruit': {
        const simulatorTask = currentTaskMode === surface.kind ? currentTask : undefined;
        const props = {
          taskId: simulatorTask?.id ?? '',
          taskPrompt: simulatorTask?.prompt ?? '',
          taskSuccessRule: simulatorTask?.success_rule ?? '',
          onSetupTask: saveSimulatorTask,
          onComplete: (demoId: string) => {
            if (simulatorTask) openWork('demos', simulatorTask.id, demoId);
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
    <header className="header">
      <div className="coach-hero">
        <div className="coach-mark" aria-hidden="true">✦</div>
        <h1>DreamCoach</h1>
        <p className="subtitle">Teach Dream-1 a task and see how it performs.</p>
      </div>
    </header>
    {error && !needsHostedConnection && <div className="alert" role="alert">{error}</div>}
    <div className={`chat-layout${needsHostedConnection ? ' chat-layout-onboarding' : ''}`}>
    <section className="card chat-shell" aria-label="Fine-tuning coach conversation">
      <div className="chat-panel-top">
        <span className="chat-landscape-title"><span className="coach-panel-mark" aria-hidden="true">✦</span>Conversation</span>
        {begun && !workSurface && <button type="button" className="chat-reset" disabled={busy || yamActionPending} onClick={startOver}>Start over</button>}
      </div>
      <div className={`chat-thread${workSurface ? ' chat-thread-workspace' : ''}`} ref={thread}
        aria-live={workSurface ? undefined : 'polite'} tabIndex={workSurface ? -1 : undefined}>
      {workSurface ? renderWorkspace(workSurface) : <>
        {hosted && messages.length === 0 && <div className="chat-bubble chat-assistant"><span>DreamCoach</span><p>{hostedIntroduction}</p></div>}
        {messages.map((item, index) => <div key={index} className={`chat-bubble chat-${item.role}`}>
          <span>{item.role === 'assistant' ? 'DreamCoach' : 'You'}</span>
          <p>{item.role === 'assistant' ? item.content.replace('Watch results in the sidebar', 'Open Evaluation results below') : item.content}</p>
        </div>)}
        {busy && !needsHostedConnection && <div className="chat-bubble chat-assistant"><span>DreamCoach</span>
          <p>{!begun && messages.length ? 'Resetting the YAM simulator…' : 'Thinking through your next step…'}</p>
        </div>}
      {needsHostedConnection && begun && <div className="chat-bubble chat-assistant">
        <span>DreamCoach</span>
        <p>Connect your Dream Labs account before starting the simulator.</p>
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
        pipeline={currentTaskMode === simulatorMode ? currentPipeline : null}
        comparisonReport={evaluation.simulation?.report ?? null}
        comparisonGoal={comparisonGoal}
        findResumable={() => showWork({ kind: 'resume' })}
        resume={currentYamJob ? () => resumeYam(currentYamJob.task_id, currentYamJob.id) : undefined}
        openExistingCheckpoints={(goal) => showWork({ kind: 'checkpoints', goal })}
        mode={simulatorMode}
        setMode={switchSimulatorMode}
        openRecorder={openRecorder}
        prepare={prepareSimulator}
        collect={(scenes) => runYamAction('/api/simulator/collect', { scenes })}
        reuseDemos={() => runYamAction('/api/simulator/collect', { source: 'bundled' })}
        compare={(jobId) => runYamAction('/api/simulator/compare', { task_id: activeTaskId, job_id: jobId, pairs: 4 })}
        stop={quitYam}
        review={() => openWork('demos')}
        training={() => openWork('training')}
        planFreshComparison={comparedCheckpoint ? () => showWork({
          kind: 'checkpoints', goal: comparisonGoal ?? 'pickup', preferredCheckpoint: comparedCheckpoint,
        }) : undefined}
      />}
      {begun && reply?.task_draft && reply.setup_help !== 'simulator' && <div className="chat-action"><strong>Ready to save this task?</strong><p>{reply.task_draft.name} · {reply.task_draft.prompt}<br />Success: {reply.task_draft.success_rule}</p><button disabled={busy} onClick={() => void saveTask(reply.task_draft!)}>Confirm and save task</button></div>}
      {showSuggestedTool
        && <div className="chat-action"><button className="secondary" onClick={() => {
          const target = suggestedScreen;
          if (target === 'demos' || target === 'training') openWork(target);
          else if (target === 'evaluation') openEvaluation();
          else if (target === 'tasks') openTool({ kind: 'baseline', taskId: activeTaskId });
          else if (target === 'preflight' || target === 'statistical') openTool({ kind: target });
        }}>{suggestedScreen === 'demos' ? 'Review demos' : suggestedScreen === 'training'
          ? 'Open fine-tuning' : suggestedScreen === 'tasks' ? 'Plan supervised baseline' : `Open ${suggestedScreen}`}</button></div>}
      {begun && !needsHostedConnection && !simulatorRequested && <button type="button" className="chat-simulator-link" onClick={() => setShowSimulator(true)}>Use the YAM simulator</button>}
      {begun && !needsHostedConnection && <details className="chat-inventory">
        <summary>Tools</summary>
        <div className="chat-workspace-actions">
          {!hosted && <>
            <button type="button" className="secondary" onClick={() => openTool({ kind: 'preflight' })}>Check arms and cameras</button>
            <button type="button" className="secondary" onClick={() => openTool({ kind: 'baseline', taskId: activeTaskId })}>Supervised baseline trials</button>
            {activeTaskId && !currentTaskMode && <button type="button" className="secondary"
              onClick={() => openTool({ kind: 'repair', taskId: activeTaskId })}>Repair first</button>}
          </>}
          <button type="button" className="secondary" onClick={() => openTool({ kind: 'statistical' })}>Statistical audit</button>
        </div>
      </details>}
      {begun && !needsHostedConnection && guidedMode && <details className="chat-inventory">
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
          {comparisonReady.goal && comparisonReady.goal !== 'physical' ? <YamComparisonPlan pairs={4} goal={comparisonReady.goal} /> : <p>{comparisonReady.goal === null
            ? 'Checking evaluation options…'
            : currentTaskMode
              ? 'Automatic simulator comparison supports apple pickup and apple into bowl. This checkpoint can be evaluated with supervised physical trials.'
              : 'Compare your new checkpoint with the base model on held-out scenes.'}</p>}
        </div>
        {comparisonReady.goal !== null && (comparisonReady.goal !== 'physical'
          ? <button type="button" disabled={yamActionPending} onClick={() => void runYamAction('/api/simulator/compare', {
            task_id: comparisonReady.taskId, job_id: comparisonReady.jobId, pairs: 4,
          })}>
            {yamActionPending ? 'Starting comparison…' : 'Run simulator comparison'}
          </button>
          : !hosted && <button type="button" onClick={() => openEvaluation(comparisonReady.taskId)}>Plan physical evaluation</button>)}
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
      {!workSurface && !begun && <div className="chat-suggestions" role="group" aria-label="Quick starts">
        <span>Quick starts</span>
        <div>{simulatorWorkflows.map(({ id, title }) => (
          <button type="button" className="secondary" key={id} disabled={busy || !canBegin}
            onClick={() => void beginConversation(id)}>{title}</button>
        ))}</div>
      </div>}
      {!workSurface && !begun && <div className="chat-begin">
        <p id="chat-begin-description">{guidedMode && !needsHostedConnection ? 'Start with the guided simulator.' : 'First, we’ll check Dream Labs access.'}</p>
        <button type="button" aria-describedby="chat-begin-description" disabled={busy || !canBegin} onClick={() => void beginConversation()}>
          Begin<span className="chat-begin-arrow" aria-hidden="true">→</span>
        </button>
      </div>}
      {!workSurface && begun && !guidedMode && <form onSubmit={(event) => void submit(event)} className="chat-composer"><textarea ref={composer} aria-label="Message to coach" disabled={!ai?.configured} value={text} maxLength={2000} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit(event); } }} placeholder="Tell me about your robot or ask what to do next…" /><button disabled={!ai?.configured || busy || !text.trim()}>Send</button></form>}
    </section>
    {!needsHostedConnection && <details className="coach-evidence">
      <summary>Evaluation results</summary>
      <LiveEvaluation taskId={evaluationTaskId}
        simulatorMode={currentTaskMode}
        comparisonGoal={comparisonGoal}
        allowPhysicalPlanning={!hosted}
        onOpen={openEvaluation} onEvidence={onEvidence} evidence={evaluation} />
    </details>}
    </div>
  </main>;
}
