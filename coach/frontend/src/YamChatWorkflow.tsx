import { useState } from 'react';

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
  openRecorder: (mode: 'fruit' | 'scene') => void;
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
  const running = job?.state === 'running' || job?.state === 'stopping';
  const checkpoint = pipeline?.job?.status === 'succeeded' ? pipeline.job : null;
  const canStart = !running && (pipeline ? !pipeline.kept && !pipeline.unreviewed && !checkpoint : !job?.demos);

  async function act(action: () => Promise<void>) {
    setBusy(true);
    try { await action(); }
    finally { setBusy(false); }
  }

  return <section className="chat-action yam-chat-workflow" aria-label="YAM simulator workflow">
    <div className="yam-chat-heading">
      <h2>YAM simulator</h2>
      <span>{setup?.state === 'ready' ? 'Ready' : setup?.state === 'preparing' ? 'Preparing' : 'Setup'}</span>
    </div>
    <label className="yam-scene-count">Robot-free workflow
      <select value={mode} onChange={(event) => setMode(event.target.value as SimulatorMode)}>
        <option value="apple">Guided apple pickup</option>
        <option value="fruit">Click to correct a fruit task</option>
        <option value="scene">Build a pick-and-place scene</option>
      </select>
    </label>
    {setup?.state !== 'ready' && <>
      <p role="status">{setup?.message ?? 'Checking the local simulator…'}</p>
      <button type="button" disabled={!setup || busy || setup.state === 'preparing'} onClick={() => void act(prepare)}>
        {setup?.state === 'preparing' ? 'Preparing YAM…' : 'Prepare YAM simulator'}
      </button>
    </>}
    {mode !== 'apple' && <>
      {mode === 'fruit'
        ? <p>Choose an apple or banana lift, or an apple placement in a bowl. Set up the local task, load a scene, then click the fruit and the bowl if needed. Record and review a verified demo.</p>
        : <p>Start with a red block or yellow ball preset, or set your own object and target. Set up the matching local task, preview the scene, then record and review a verified demo.</p>}
      <p>Both recorders run locally. After keeping demos, you can use them in Training.</p>
      <button type="button" disabled={setup?.state !== 'ready'} onClick={() => openRecorder(mode)}>
        {mode === 'fruit' ? 'Open click-to-correct setup' : 'Open scene setup'}
      </button>
      {!!pipeline?.kept && <button type="button" className="secondary" onClick={training}>Open training for this task</button>}
    </>}
    {mode === 'apple' && <>
    <p>Apple pickup · Lift the apple at least 8 cm and hold it for two seconds.</p>
    {canStart && <button type="button" className="secondary" disabled={busy} onClick={() => void act(reuseDemos)}>Use the 24 bundled apple demos</button>}
    {setup?.state === 'ready' && canStart && <>
      {existingCheckpoint && dreamReady && <>
        <p>The account can run a published apple checkpoint. Compare it on four fresh matched scenes using Dream inference credits.</p>
        <button type="button" className="secondary" disabled={busy} onClick={() => void act(() => compareExisting(existingCheckpoint))}>
          Evaluate existing apple checkpoint
        </button>
      </>}
      <p>DreamCoach runs Dream-1 on fresh training scenes and records verified corrections for failures. The batch uses up to 12 action chunks per scene and may use Dream credits.</p>
      {!dreamReady && <p>Connect Dream Labs in chat to enable demo collection.</p>}
      <label className="yam-scene-count">Training scenes
        <select value={scenes} onChange={(event) => setScenes(Number(event.target.value))}>
          {[1, 2, 4, 8].map((count) => <option key={count} value={count}>{count}</option>)}
        </select>
      </label>
      <button type="button" disabled={busy || !dreamReady} onClick={() => void act(() => collect(scenes))}>
        Run and collect demos
      </button>
    </>}
    {job && <div className="yam-chat-status" role="status">
      <p>{job.message}</p>
      {job.kind !== 'import' && (running || job.completed > 0) && <>
        <progress value={job.completed} max={job.total} aria-label={job.kind === 'collection' ? 'Completed training scenes' : 'Completed evaluation pairs'} />
        <small>{job.completed}/{job.total} {job.kind === 'collection' ? 'training scenes' : 'matched pairs'}</small>
      </>}
    </div>}
    {running && <button type="button" className="secondary" disabled={busy || job.state === 'stopping'} onClick={() => void act(stop)}>Stop after this rollout</button>}
    {!running && (pipeline ? pipeline.unreviewed : job?.demos) ? <button type="button" className="secondary" onClick={review}>Review demos</button> : null}
    {!running && !!pipeline?.kept && !checkpoint && <>
      <p>{pipeline.job
        ? `Fine-tune status: ${pipeline.job.status.replaceAll('_', ' ')}.`
        : pipeline.validated
          ? 'Your dataset passed validation. Review the settings and approve training.'
          : `${pipeline.kept} kept demos. Create a dataset version and validate it in Training.`}</p>
      <button type="button" className="secondary" onClick={training}>Open training for this task</button>
    </>}
    {!running && checkpoint && <>
      <p>The fine-tune is ready. Run both models on four matching held-out scenes. This uses Dream inference credits and updates the evaluation sidebar.</p>
      <button type="button" disabled={busy || !dreamReady || setup?.state !== 'ready'} onClick={() => void act(() => compare(checkpoint.id))}>
        {job?.kind === 'comparison' && job.state === 'completed' ? 'Run comparison again' : 'Run simulator comparison'}
      </button>
    </>}
    </>}
    {job?.kind === 'comparison' && job.state === 'completed' && <button type="button" className="secondary" onClick={explainComparison}>
      Explain comparison results
    </button>}
  </section>;
}
