import { useEffect, useState } from 'react';
import Runs from './Runs';
import Tasks from './Tasks';
import Demos from './Demos';
import Training from './Training';
import EvaluationPage from './Evaluation';
import StatisticalAudit from './StatisticalAudit';
import Guide from './Guide';
import Repair from './Repair';
import CoachEffect from './CoachEffect';
import CoachChat from './CoachChat';
import Preflight from './Preflight';
import OfflineReview from './OfflineReview';
import { readRoute, screenHref } from './workspaceRoute';
import type { DemoKeepReceipt } from './ChatDemoReview';
import type { SimulatorMode } from './YamChatWorkflow';

export default function App() {
  const [needsHostedConnection, setNeedsHostedConnection] = useState(() =>
    document.querySelector('meta[name="dreamcoach-workspace"]')?.getAttribute('content') === 'required');
  const [screen, setScreen] = useState<'start' | 'guide' | 'repair' | 'preflight' | 'runs' | 'tasks' | 'demos' | 'training' | 'evaluation' | 'statistical' | 'effect'>('start');
  const [hash, setHash] = useState(() => window.location.hash);
  const [mode, setMode] = useState<'loading' | 'offline' | 'live' | 'unavailable'>('loading');
  const route = readRoute(hash);
  const offlineRequested = /^#\/offline(?:\?|$)/.test(hash);
  const routeTask = route.query.get('task') ?? '';
  const initialRun = route.screen === 'runs' ? route.query.get('run') ?? '' : '';
  const runPrompt = route.screen === 'runs' ? route.query.get('prompt') ?? '' : '';
  const [evaluationSelection, setEvaluationSelection] = useState<{ taskId?: string; evaluationId?: string }>({});
  const [activeTaskId, setActiveTaskId] = useState(() =>
    needsHostedConnection ? '' : sessionStorage.getItem('coach-active-task-v3') ?? '');
  const [showSimulator, setShowSimulator] = useState(false);
  const [demoApproval, setDemoApproval] = useState<DemoKeepReceipt | null>(null);
  const [simulatorMode, setSimulatorMode] = useState<SimulatorMode>(() => {
    if (needsHostedConnection) return 'apple';
    const mode = sessionStorage.getItem('coach-simulator-mode-v3');
    return mode === 'scene' || mode === 'fruit' ? mode : 'apple';
  });

  useEffect(() => {
    const onHashChange = () => setHash(window.location.hash);
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    if (needsHostedConnection) return;
    const controller = new AbortController();
    void fetch('/api/mode', { signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error('Could not identify the workspace.');
      const { offline_only } = await response.json() as { offline_only: boolean };
      if (!controller.signal.aborted) setMode(offline_only ? 'offline' : 'live');
    }).catch(() => {
      if (!controller.signal.aborted) setMode('unavailable');
    });
    return () => controller.abort();
  }, [needsHostedConnection]);

  useEffect(() => {
    if (needsHostedConnection || mode === 'offline') return;
    const path = /^#\/(runs|guide|tasks)(?:\?|$)/.exec(hash)?.[1];
    if (path === 'runs' || path === 'guide' || path === 'tasks') setScreen(path);
  }, [hash, needsHostedConnection, mode]);
  function chooseSimulatorMode(mode: SimulatorMode) {
    setSimulatorMode(mode);
    sessionStorage.setItem('coach-simulator-mode-v3', mode);
  }

  function selectTask(taskId: string) {
    setActiveTaskId(taskId);
    setDemoApproval((current) => current?.taskId === taskId ? current : null);
    if (taskId) sessionStorage.setItem('coach-active-task-v3', taskId);
    else sessionStorage.removeItem('coach-active-task-v3');
  }

  function resetChatSession() {
    selectTask('');
    chooseSimulatorMode('apple');
    setShowSimulator(false);
    setDemoApproval(null);
  }

  function returnWithDemoApproval(receipt: DemoKeepReceipt) {
    selectTask(receipt.taskId);
    setDemoApproval(receipt);
    setScreen('start');
  }

  function openEvaluation(taskId?: string, evaluationId?: string) {
    setEvaluationSelection({ taskId, evaluationId });
    setScreen('evaluation');
  }

  if (!needsHostedConnection && (mode === 'offline' || offlineRequested)) {
    if (mode === 'loading') return <main className="page"><p role="status">Opening the local walkthrough…</p></main>;
    if (mode !== 'offline') return <main className="page">
      <h1>Offline walkthrough</h1>
      <p role="alert">Open the local address printed by <code>teach-task-coach offline-demo</code> to use this walkthrough.</p>
      <a href="#">Return to DreamCoach</a>
    </main>;
    if (route.screen === 'guide') return <main className="page">
      <h1>Offline task guide</h1>
      <ol>
        <li>Compare the control and scripted pickup videos from the same scene.</li>
        <li>Record what you can see and leave incomplete attempts unlabelled.</li>
        <li>Review the scripted reference and choose Keep or Redo.</li>
      </ol>
      <a href={screenHref('offline', { task: routeTask })}>Return to the offline walkthrough</a>
    </main>;
    if (/^#\/runs(?:\?|$)/.test(hash)) return <>
      <nav className="top-nav" aria-label="Offline walkthrough">
        <span className="brand">DreamCoach</span>
        <a href={screenHref('offline', { task: routeTask })}>Return to the offline walkthrough</a>
      </nav>
      <Runs key={initialRun} initialEpisodeId={initialRun} offline />
    </>;
    return <OfflineReview key={routeTask} taskId={routeTask} />;
  }

  return (
    <>
      {!needsHostedConnection && <nav className={`top-nav${screen === 'start' ? ' chat-nav' : ''}`} aria-label="Coach sections">
        <span className="brand">DreamCoach</span>
        <button className={screen === 'start' ? 'nav-active' : ''} onClick={() => { setShowSimulator(false); setScreen('start'); }}>Start here</button>
        <button className={screen === 'guide' ? 'nav-active' : ''} onClick={() => setScreen('guide')}>Guide</button>
        <button className={screen === 'repair' ? 'nav-active' : ''} onClick={() => setScreen('repair')}>Repair first</button>
        <button className={screen === 'preflight' ? 'nav-active' : ''} onClick={() => setScreen('preflight')}>Preflight</button>
        <button className={screen === 'runs' ? 'nav-active' : ''} onClick={() => setScreen('runs')}>Run review</button>
        <button className={screen === 'demos' ? 'nav-active' : ''} onClick={() => setScreen('demos')}>Demos</button>
        <button className={screen === 'training' ? 'nav-active' : ''} onClick={() => setScreen('training')}>Training</button>
        <button className={screen === 'evaluation' ? 'nav-active' : ''} onClick={() => { if (screen !== 'evaluation') openEvaluation(); }}>Evaluation</button>
        <button className={screen === 'statistical' ? 'nav-active' : ''} onClick={() => setScreen('statistical')}>Statistical audit</button>
        <button className={screen === 'effect' ? 'nav-active' : ''} onClick={() => setScreen('effect')}>Coach effect</button>
      </nav>}
      {screen === 'start' && <CoachChat
        needsHostedConnection={needsHostedConnection}
        onHostedConnection={() => {
          resetChatSession();
          setNeedsHostedConnection(false);
        }}
        resetSession={resetChatSession}
        onEvidence={() => setScreen('effect')}
        activeTaskId={activeTaskId}
        selectTask={selectTask}
        demoApproval={demoApproval}
        clearDemoApproval={() => setDemoApproval(null)}
        onDemoKept={returnWithDemoApproval}
        showSimulatorOnOpen={showSimulator}
        simulatorMode={simulatorMode}
        chooseSimulatorMode={chooseSimulatorMode}
      />}
      {screen === 'guide' && <Guide initialTaskId={route.screen === 'guide' ? routeTask : activeTaskId}
        onRepair={() => setScreen('repair')} />}
      {screen === 'repair' && <Repair onDemos={() => setScreen('demos')} onTraining={() => setScreen('training')} />}
      {screen === 'preflight' && <Preflight />}
      {screen === 'tasks' && <Tasks />}
      {screen === 'demos' && <Demos initialTaskId={activeTaskId} onKeep={returnWithDemoApproval}
        onTaskSelected={selectTask}
        openSimulator={() => { setShowSimulator(true); setScreen('start'); }} />}
      {screen === 'training' && <Training initialTaskId={activeTaskId} onEvaluate={openEvaluation}
        onSimulatorEvaluate={(taskId) => { selectTask(taskId); chooseSimulatorMode('apple'); setShowSimulator(true); setScreen('start'); }} />}
      {screen === 'evaluation' && <EvaluationPage
        initialTaskId={evaluationSelection.taskId}
        initialEvaluationId={evaluationSelection.evaluationId}
      />}
      {screen === 'statistical' && <StatisticalAudit />}
      {screen === 'effect' && <CoachEffect />}
      {screen === 'runs' && <Runs key={`${initialRun}:${runPrompt}`} initialEpisodeId={initialRun} initialPrompt={runPrompt} />}
    </>
  );
}
