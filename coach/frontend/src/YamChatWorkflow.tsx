import { useEffect, useRef, useState } from 'react';
import type { ScenePreset } from './SceneTask';

export type YamJob = {
  id: string;
  kind: 'collection' | 'import' | 'comparison';
  task_id: string;
  total: number;
  completed: number;
  demos: number;
  state: 'running' | 'stopping' | 'completed' | 'cancelled' | 'failed';
  message: string;
};

export type TaskPipeline = {
  kept: number;
  unreviewed: number;
  validated: boolean;
  job: { id: string; status: string; checkpoint: string | null } | undefined;
};

export type SimulatorMode = 'apple' | 'fruit' | 'scene';

const workflows: { id: SimulatorMode; title: string; description: string; icon: string }[] = [
  { id: 'apple', title: 'Apple pickup', description: 'Run the fine-tuning loop', icon: '◎' },
  { id: 'fruit', title: 'Fruit correction', description: 'Click to teach a motion', icon: '↖' },
  { id: 'scene', title: 'Build a scene', description: 'Pick an object and target', icon: '◇' },
];

const sceneChoices: { id: ScenePreset; title: string; target: string }[] = [
  { id: 'block', title: 'Red block', target: 'Blue pad' },
  { id: 'ball', title: 'Yellow ball', target: 'Green pad' },
  { id: 'custom', title: 'Custom scene', target: 'Your object and target' },
];

export default function YamChatWorkflow({
  setup, dreamReady, job, pipeline, existingCheckpoint, mode, setMode, openRecorder,
  prepare, collect, reuseDemos, compare, compareExisting, stop, review, training, explainComparison,
}: {
  setup: { state: string; message: string } | null;
  dreamReady: boolean;
  job: YamJob | null;
  pipeline: TaskPipeline | null;
  existingCheckpoint: string | undefined;
  mode: SimulatorMode;
  setMode: (mode: SimulatorMode) => void;
  openRecorder: (mode: 'fruit' | 'scene', preset?: ScenePreset) => void;
  prepare: () => Promise<void>;
  collect: (scenes: number) => Promise<void>;
  reuseDemos: () => Promise<void>;
  compare: (jobId: string) => Promise<void>;
  compareExisting: (checkpoint: string) => Promise<void>;
  stop: () => Promise<void>;
  review: () => void;
  training: () => void;
  explainComparison: () => void;
}) {
  const [scenes, setScenes] = useState(4);
  const [busy, setBusy] = useState(false);
  const [preset, setPreset] = useState<ScenePreset>('block');
  const panel = useRef<HTMLElement>(null);
  const running = job?.state === 'running' || job?.state === 'stopping';
  const ready = setup?.state === 'ready';
  const preparing = setup?.state === 'preparing';
  const checkpoint = pipeline?.job?.status === 'succeeded' ? pipeline.job : null;
  const canStart = !running && (pipeline ? !pipeline.kept && !pipeline.unreviewed && !checkpoint : !job?.demos);

  useEffect(() => {
    panel.current?.scrollIntoView({ block: 'nearest' });
  }, []);

  async function act(action: () => Promise<void>) {
    setBusy(true);
    try { await action(); }
    finally { setBusy(false); }
  }

  return <section ref={panel} className="yam-chat-workflow" aria-label="YAM simulator workflow">
    <header className="yam-chat-heading">
      <div><h2>YAM simulator</h2><p>Record demos without a physical robot.</p></div>
      <span className="yam-ready" data-ready={ready}>{ready ? 'Ready' : preparing ? 'Preparing' : setup ? 'Setup needed' : 'Checking…'}</span>
    </header>

    <div className="yam-workflow-options" role="group" aria-label="Robot-free workflow">
      {workflows.map(({ id, title, description, icon }) => (
        <button type="button" className="yam-choice" key={id} aria-pressed={mode === id} onClick={() => setMode(id)}>
          <span className="yam-choice-icon" aria-hidden="true">{icon}</span>
          <strong>{title}</strong>
          <small>{description}</small>
        </button>
      ))}
    </div>

    {!ready && <div className="yam-setup">
      <p role="status">{setup?.message ?? 'Checking the local simulator…'}</p>
      <button type="button" className="yam-primary" disabled={!setup || busy || preparing} onClick={() => void act(prepare)}>
        {preparing ? 'Preparing YAM…' : 'Prepare YAM simulator'}
      </button>
    </div>}

    {job && (running || mode === 'apple') && <div className="yam-job" data-state={job.state}>
      <div role="status">
        <strong>{running ? (job.kind === 'comparison' ? 'Comparing checkpoints' : job.kind === 'import' ? 'Importing demos' : 'Collecting demos')
          : job.state === 'failed' ? 'Run stopped' : job.state === 'cancelled' ? 'Run stopped by you' : 'Run complete'}</strong>
        <p>{job.message}</p>
        {job.kind !== 'import' && (running || job.completed > 0) && <div className="yam-job-progress">
          <progress value={job.completed} max={job.total} aria-label={job.kind === 'collection' ? 'Completed training scenes' : 'Completed evaluation pairs'} />
          <small>{job.completed}/{job.total} {job.kind === 'collection' ? 'scenes' : 'pairs'}</small>
        </div>}
      </div>
      {running && <button type="button" className="yam-secondary" disabled={busy || job.state === 'stopping'} onClick={() => void act(stop)}>Stop after this rollout</button>}
    </div>}

    {mode === 'scene' && <div className="yam-panel">
      <div className="yam-panel-heading"><h3>Choose a scene</h3><p>You can adjust the object and target before recording.</p></div>
      <div className="yam-presets" role="group" aria-label="Scene preset">
        {sceneChoices.map(({ id, title, target }) => (
          <button type="button" className="yam-choice yam-preset" key={id} aria-pressed={preset === id} onClick={() => setPreset(id)}>
            <span className={`yam-preset-mark yam-preset-${id}`} aria-hidden="true" />
            <strong>{title}</strong>
            <small>{target}</small>
          </button>
        ))}
      </div>
      <div className="yam-next">
        <small>Preview, record, then review your demo.</small>
        <button type="button" className="yam-primary" disabled={!ready} onClick={() => openRecorder('scene', preset)}>Open scene setup <span aria-hidden="true">→</span></button>
      </div>
    </div>}

    {mode === 'fruit' && <div className="yam-panel">
      <div className="yam-panel-heading"><h3>Teach a fruit task</h3><p>Lift an apple or banana, or place an apple in a bowl.</p></div>
      <div className="yam-next">
        <small>Load a scene and click the fruit. For placement, click the bowl too.</small>
        <button type="button" className="yam-primary" disabled={!ready} onClick={() => openRecorder('fruit')}>Open fruit setup <span aria-hidden="true">→</span></button>
      </div>
    </div>}

    {mode !== 'apple' && (Boolean(pipeline?.unreviewed) || Boolean(pipeline?.kept)) && <div className="yam-buttons">
      {!!pipeline?.unreviewed && <button type="button" className="yam-primary" onClick={review}>Review demos <span aria-hidden="true">→</span></button>}
      {!!pipeline?.kept && <button type="button" className="yam-secondary" onClick={training}>Open fine-tuning</button>}
    </div>}

    {mode === 'apple' && <div className="yam-panel">
      <div className="yam-panel-heading"><h3>Teach apple pickup</h3><p>Lift the apple at least 8 cm and hold it for two seconds.</p></div>
      {canStart && <>
        <div className="yam-buttons">
          <button type="button" className="yam-primary" disabled={busy} onClick={() => void act(reuseDemos)}>Use 24 bundled demos</button>
          {ready && dreamReady && existingCheckpoint && <button type="button" className="yam-secondary" disabled={busy} onClick={() => void act(() => compareExisting(existingCheckpoint))}>
            Evaluate existing checkpoint
          </button>}
        </div>
        {ready && <div className="yam-next">
          <label className="yam-scene-count">Fresh scenes
            <select value={scenes} onChange={(event) => setScenes(Number(event.target.value))}>
              {[1, 2, 4, 8].map((count) => <option key={count} value={count}>{count}</option>)}
            </select>
          </label>
          <button type="button" className="yam-secondary" disabled={busy || !dreamReady} onClick={() => void act(() => collect(scenes))}>Run and collect demos</button>
          <small>{dreamReady ? 'Fresh collection and checkpoint evaluation may use Dream credits.' : 'Connect Dream Labs to record fresh demos.'}</small>
        </div>}
      </>}
      {!running && (pipeline ? pipeline.unreviewed : job?.demos) ? <button type="button" className="yam-primary" onClick={review}>Review demos <span aria-hidden="true">→</span></button> : null}
      {!running && !!pipeline?.kept && !checkpoint && <div className="yam-next">
        <small>{pipeline.job
          ? `Fine-tune status: ${pipeline.job.status.replaceAll('_', ' ')}.`
          : pipeline.validated ? 'Dataset validated.' : `${pipeline.kept} demos ready for validation.`}</small>
        <button type="button" className="yam-secondary" onClick={training}>Open fine-tuning</button>
      </div>}
      {!running && checkpoint && <div className="yam-next">
        <small>Compare both checkpoints on four held-out scenes. This may use Dream credits.</small>
        <button type="button" className="yam-primary" disabled={busy || !dreamReady || !ready} onClick={() => void act(() => compare(checkpoint.id))}>
          {job?.kind === 'comparison' && job.state === 'completed' ? 'Run comparison again' : 'Run simulator comparison'}
        </button>
      </div>}
      {job?.kind === 'comparison' && job.state === 'completed' && <button type="button" className="yam-secondary" onClick={explainComparison}>
        Explain comparison results
      </button>}
    </div>}
  </section>;
}
