import { useState } from 'react';
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
import type { DemoKeepReceipt } from './ChatDemoReview';
import type { SimulatorMode } from './YamChatWorkflow';

export default function App() {
  const [needsHostedConnection, setNeedsHostedConnection] = useState(() =>
    document.querySelector('meta[name="dreamcoach-workspace"]')?.getAttribute('content') === 'required');
  const [screen, setScreen] = useState<'start' | 'guide' | 'repair' | 'preflight' | 'runs' | 'tasks' | 'demos' | 'training' | 'evaluation' | 'statistical' | 'effect'>('start');
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
        activeTaskId={activeTaskId}
        selectTask={selectTask}
        demoApproval={demoApproval}
        clearDemoApproval={() => setDemoApproval(null)}
        onDemoKept={returnWithDemoApproval}
        showSimulatorOnOpen={showSimulator}
        simulatorMode={simulatorMode}
        chooseSimulatorMode={chooseSimulatorMode}
      />}
      {screen === 'guide' && <Guide onRepair={() => setScreen('repair')} />}
      {screen === 'repair' && <Repair onDemos={() => setScreen('demos')} onTraining={() => setScreen('training')} />}
      {screen === 'preflight' && <Preflight />}
      {screen === 'tasks' && <Tasks />}
      {screen === 'demos' && <Demos initialTaskId={activeTaskId} onKeep={returnWithDemoApproval}
        onTaskSelected={selectTask}
        openSimulator={() => { setShowSimulator(true); setScreen('start'); }} />}
      {screen === 'training' && <Training initialTaskId={activeTaskId} onEvaluate={() => openEvaluation(activeTaskId)}
        onSimulatorEvaluate={(taskId) => { selectTask(taskId); chooseSimulatorMode('apple'); setShowSimulator(true); setScreen('start'); }} />}
      {screen === 'evaluation' && <EvaluationPage
        initialTaskId={evaluationSelection.taskId}
        initialEvaluationId={evaluationSelection.evaluationId}
      />}
      {screen === 'statistical' && <StatisticalAudit />}
      {screen === 'effect' && <CoachEffect />}
      {screen === 'runs' && <Runs />}
    </>
  );
}
