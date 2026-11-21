import { useCallback, useEffect, useState } from 'react';
import Runs from './Runs';
import Tasks from './Tasks';
import Demos from './Demos';
import Training from './Training';
import EvaluationPage from './Evaluation';
import Guide from './Guide';

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
          <p className="eyebrow">Dream-1 task coach</p>
          <h1>Teach it a task</h1>
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
  const [screen, setScreen] = useState<'guide' | 'preflight' | 'runs' | 'tasks' | 'demos' | 'training' | 'evaluation'>('guide');
  return (
    <>
      <nav className="top-nav" aria-label="Coach sections">
        <span className="brand">Teach it a task</span>
        <button className={screen === 'guide' ? 'nav-active' : ''} onClick={() => setScreen('guide')}>Guide</button>
        <button className={screen === 'preflight' ? 'nav-active' : ''} onClick={() => setScreen('preflight')}>Preflight</button>
        <button className={screen === 'tasks' ? 'nav-active' : ''} onClick={() => setScreen('tasks')}>Tasks</button>
        <button className={screen === 'runs' ? 'nav-active' : ''} onClick={() => setScreen('runs')}>Run review</button>
        <button className={screen === 'demos' ? 'nav-active' : ''} onClick={() => setScreen('demos')}>Demos</button>
        <button className={screen === 'training' ? 'nav-active' : ''} onClick={() => setScreen('training')}>Training</button>
        <button className={screen === 'evaluation' ? 'nav-active' : ''} onClick={() => setScreen('evaluation')}>Evaluation</button>
      </nav>
      {screen === 'guide' ? <Guide /> : screen === 'preflight' ? <Preflight /> : screen === 'tasks' ? <Tasks /> : screen === 'demos' ? <Demos /> : screen === 'training' ? <Training /> : screen === 'evaluation' ? <EvaluationPage /> : <Runs />}
    </>
  );
}
