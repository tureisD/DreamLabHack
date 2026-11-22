import { useCallback, useEffect, useState } from 'react';
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
import type { DemoKeepReceipt } from './ChatDemoReview';
import type { SimulatorMode } from './YamChatWorkflow';
import type { ScenePreset } from './SceneTask';

type Check = { state: 'ready' | 'blocked' | 'unavailable'; message: string };
type Model = {
  id: string;
  owner: string;
  embodiment: string | null;
  servable: boolean;
  cameras: string[] | null;
};
type Station = {
  state: string;
  checkpoint: string | null;
  prompt: string | null;
  arms: Record<string, boolean>;
  cameras_age_s: Record<string, number | null>;
  last_error: Record<string, unknown> | null;
};
type Preflight = {
  station: Check;
  dream: Check;
  station_status: Station | null;
  models: Model[];
};

function StateBadge({ state }: { state: Check['state'] }) {
  return <span className={`state state-${state}`}>{state}</span>;
}

function Preflight() {
  const [data, setData] = useState<Preflight | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/preflight');
      if (!response.ok) throw new Error(`Preflight request failed (${response.status})`);
      setData((await response.json()) as Preflight);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load preflight results.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <main className="page">
      <header className="header">
        <div>
          <p className="eyebrow">DreamCoach</p>
          <h1>Preflight</h1>
          <p className="subtitle">Check the robot station and Dream account before starting a task.</p>
        </div>
        <button type="button" onClick={() => void refresh()} disabled={loading}>
          {loading ? 'Checking…' : 'Refresh checks'}
        </button>
      </header>

      {error && <div className="alert" role="alert">{error}</div>}

      <section className="checks" aria-label="Connection checks">
        <article className="card">
          <div className="card-heading"><h2>Robot station</h2>{data && <StateBadge state={data.station.state} />}</div>
          <p>{data?.station.message ?? 'Checking the local station…'}</p>
          {data?.station_status && (
            <dl className="details">
              <div><dt>State</dt><dd>{data.station_status.state}</dd></div>
              <div><dt>Checkpoint</dt><dd>{data.station_status.checkpoint ?? 'None selected'}</dd></div>
              <div><dt>Arms</dt><dd>{Object.entries(data.station_status.arms).map(([name, ok]) => `${name}: ${ok ? 'ready' : 'unavailable'}`).join(' · ') || 'Not reported'}</dd></div>
              <div><dt>Cameras</dt><dd>{Object.entries(data.station_status.cameras_age_s).map(([name, age]) => `${name}: ${age === null ? 'no frame' : `${age.toFixed(1)}s old`}`).join(' · ') || 'Not reported'}</dd></div>
            </dl>
          )}
        </article>

        <article className="card">
          <div className="card-heading"><h2>Dream account</h2>{data && <StateBadge state={data.dream.state} />}</div>
          <p>{data?.dream.message ?? 'Checking model access…'}</p>
          <p className="hint">Uses your existing Dream credentials. No key is sent to this page.</p>
        </article>
      </section>

      <section className="card models">
        <div className="card-heading"><h2>Accessible checkpoints</h2><span className="count">{data?.models.length ?? 0}</span></div>
        {data?.models.length ? (
          <div className="model-list">
            {data.models.map((model) => (
              <div className="model" key={model.id}>
                <div><strong>{model.id}</strong><small>{model.owner} · {model.embodiment ?? 'embodiment unknown'}</small></div>
                <span className={model.servable ? 'model-ready' : 'model-pending'}>{model.servable ? 'servable' : 'not servable'}</span>
              </div>
            ))}
          </div>
        ) : <p className="empty">No checkpoints to show yet.</p>}
      </section>

      <p className="footnote">Read-only preflight. This screen does not move the robot, upload data, or start training.</p>
    </main>
  );
}

export default function App() {
  const [screen, setScreen] = useState<'start' | 'guide' | 'repair' | 'preflight' | 'runs' | 'tasks' | 'demos' | 'training' | 'evaluation' | 'statistical' | 'effect'>('start');
  const [evaluationSelection, setEvaluationSelection] = useState<{ taskId?: string; evaluationId?: string }>({});
  const [activeTaskId, setActiveTaskId] = useState(() => sessionStorage.getItem('coach-active-task') ?? '');
  const [showSimulator, setShowSimulator] = useState(false);
  const [demoApproval, setDemoApproval] = useState<DemoKeepReceipt | null>(null);
  const [simulatorMode, setSimulatorMode] = useState<SimulatorMode>(() => {
    const mode = sessionStorage.getItem('coach-simulator-mode');
    return mode === 'scene' || mode === 'fruit' ? mode : 'apple';
  });
  const [recorderFocus, setRecorderFocus] = useState<'fruit' | 'scene' | null>(null);
  const [scenePreset, setScenePreset] = useState<ScenePreset>();

  function chooseSimulatorMode(mode: SimulatorMode) {
    setSimulatorMode(mode);
    sessionStorage.setItem('coach-simulator-mode', mode);
  }

  function selectTask(taskId: string) {
    setActiveTaskId(taskId);
    setDemoApproval((current) => current?.taskId === taskId ? current : null);
    sessionStorage.setItem('coach-active-task', taskId);
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
      <nav className={`top-nav${screen === 'start' ? ' chat-nav' : ''}`} aria-label="Coach sections">
        <span className="brand">DreamCoach</span>
        <button className={screen === 'start' ? 'nav-active' : ''} onClick={() => { setShowSimulator(false); setScreen('start'); }}>Start here</button>
        <button className={screen === 'guide' ? 'nav-active' : ''} onClick={() => setScreen('guide')}>Guide</button>
        <button className={screen === 'repair' ? 'nav-active' : ''} onClick={() => setScreen('repair')}>Repair first</button>
        <button className={screen === 'preflight' ? 'nav-active' : ''} onClick={() => setScreen('preflight')}>Preflight</button>
        <button className={screen === 'runs' ? 'nav-active' : ''} onClick={() => setScreen('runs')}>Run review</button>
        <button className={screen === 'demos' ? 'nav-active' : ''} onClick={() => { setRecorderFocus(null); setScreen('demos'); }}>Demos</button>
        <button className={screen === 'training' ? 'nav-active' : ''} onClick={() => setScreen('training')}>Training</button>
        <button className={screen === 'evaluation' ? 'nav-active' : ''} onClick={() => { if (screen !== 'evaluation') openEvaluation(); }}>Evaluation</button>
        <button className={screen === 'statistical' ? 'nav-active' : ''} onClick={() => setScreen('statistical')}>Statistical audit</button>
        <button className={screen === 'effect' ? 'nav-active' : ''} onClick={() => setScreen('effect')}>Coach effect</button>
      </nav>
      {screen === 'start' && <CoachChat
        open={(next) => {
          if (next === 'evaluation') openEvaluation(activeTaskId);
          else {
            setRecorderFocus(null);
            setScreen(next);
          }
        }}
        openEvaluation={openEvaluation}
        activeTaskId={activeTaskId}
        selectTask={selectTask}
        demoApproval={demoApproval}
        clearDemoApproval={() => setDemoApproval(null)}
        onDemoKept={returnWithDemoApproval}
        showSimulatorOnOpen={showSimulator}
        simulatorMode={simulatorMode}
        chooseSimulatorMode={chooseSimulatorMode}
        openRecorder={(mode, preset) => {
          chooseSimulatorMode(mode);
          setRecorderFocus(mode);
          setScenePreset(preset);
          setScreen('demos');
        }}
      />}
      {screen === 'guide' && <Guide onRepair={() => setScreen('repair')} />}
      {screen === 'repair' && <Repair onDemos={() => setScreen('demos')} onTraining={() => setScreen('training')} />}
      {screen === 'preflight' && <Preflight />}
      {screen === 'tasks' && <Tasks />}
      {screen === 'demos' && <Demos initialTaskId={activeTaskId} onKeep={returnWithDemoApproval}
        recorderFocus={recorderFocus} onTaskSelected={selectTask}
        initialScenePreset={recorderFocus === 'scene' ? scenePreset : undefined}
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
