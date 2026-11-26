import { useEffect, useRef, useState } from 'react';

type Demo = {
  id: string;
  decision: 'keep' | 'redo' | 'unreviewed';
  camera_keys: string[];
  findings: { severity: string }[];
};
type Embodiment = { name: string; video_roles: string[] };
type Dataset = {
  id: string;
  embodiment_name: string;
  demo_ids: string[];
  status: 'pending_validation' | 'validated' | 'failed';
  remote_id: string | null;
  validation_report: { episodes?: number } | null;
  error: string | null;
};
type TrainingStatus = 'pending_upload' | 'processing' | 'pending_training' | 'training' | 'succeeded' | 'failed'
  | 'retry_requested' | 'retry_reconcile' | 'submit_reconcile';
type Job = {
  id: string;
  dataset_version_id: string;
  status: TrainingStatus;
  remote_status: string | null;
  remote_job_id: string | null;
  failure_phase: string | null;
  retry_used?: boolean;
  checkpoint: string | null;
  error: string | null;
  steps: number;
};
type Snapshot = { taskId: string; demos: Demo[]; datasets: Dataset[]; jobs: Job[] };
type Settings = { steps: number; lr_schedule: 'cosine' | 'constant'; base_share: 0 | 0.5 };
type Approval = { datasetId: string; settings: Settings };

const statusText: Record<TrainingStatus, string> = {
  pending_upload: 'Waiting to upload the validated dataset.',
  processing: 'Dream Labs is processing the dataset.',
  pending_training: 'Dataset processed. Waiting to submit the fine-tune.',
  retry_requested: 'Waiting to retry Dream dataset processing.',
  retry_reconcile: 'Checking the status of the dataset processing retry.',
  submit_reconcile: 'Checking whether Dream accepted the training submission.',
  training: 'Fine-tuning on Dream Labs.',
  succeeded: 'Fine-tuning finished.',
  failed: 'The fine-tune stopped before completion.',
};

async function request<T>(url: string, { body, signal }: { body?: object; signal?: AbortSignal } = {}): Promise<T> {
  const response = await fetch(url, body === undefined ? { signal } : {
    signal,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const { detail } = await response.json().catch(() => ({})) as { detail?: unknown };
    throw new Error(typeof detail === 'string' ? detail : `DreamCoach request failed (${response.status}).`);
  }
  return response.json() as Promise<T>;
}

export default function ChatTraining({ taskId, onClose, onCheckpointReady }: {
  taskId: string;
  onClose: () => void;
  onCheckpointReady?: (jobId: string) => void;
}) {
  const root = `/api/tasks/${encodeURIComponent(taskId)}`;
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [embodiments, setEmbodiments] = useState<Embodiment[] | null>(null);
  const [selectedBody, setSelectedBody] = useState('');
  const [bodyReload, setBodyReload] = useState(0);
  const [bodyError, setBodyError] = useState('');
  const [statusError, setStatusError] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [prepareNew, setPrepareNew] = useState(false);
  const [steps, setSteps] = useState('500');
  const [schedule, setSchedule] = useState<Settings['lr_schedule']>('cosine');
  const [baseShare, setBaseShare] = useState<Settings['base_share']>(0.5);
  const [approval, setApproval] = useState<Approval | null>(null);
  const writeInProgress = useRef(false);
  const statusEpoch = useRef(0);

  const current = snapshot?.taskId === taskId ? snapshot : null;
  const keptDemos = current?.demos.filter((demo) => demo.decision === 'keep'
    && !demo.findings.some((finding) => finding.severity === 'error')) ?? [];
  const cameraRoles = [...new Set(keptDemos.flatMap((demo) => demo.camera_keys.map((role) => role.replace(/^observation\.images\./, ''))))];
  const matchingBodies = embodiments?.filter((body) => cameraRoles.length > 0
    && body.video_roles.length === cameraRoles.length && cameraRoles.every((role) => body.video_roles.includes(role)));
  const embodiment = selectedBody || (matchingBodies?.length === 1 ? matchingBodies[0].name : '');
  const activeJob = current?.jobs.find((item) => item.status !== 'succeeded' && item.status !== 'failed');
  const dataset = activeJob
    ? current?.datasets.find((item) => item.id === activeJob.dataset_version_id)
    : current?.datasets[0];
  const job = activeJob ?? current?.jobs.find((item) => item.dataset_version_id === dataset?.id);
  const showPreparation = Boolean(current && !activeJob && (prepareNew || !dataset));
  const pendingApproval = approval?.datasetId === dataset?.id && dataset?.status === 'validated' && !job ? approval : null;
  const keptIds = new Set(keptDemos.map((demo) => demo.id));
  const datasetMatchesReview = Boolean(dataset && dataset.demo_ids.length === keptIds.size
    && dataset.demo_ids.every((id) => keptIds.has(id)));
  const demoCount = dataset?.validation_report?.episodes ?? dataset?.demo_ids.length ?? 0;
  const validSteps = Number.isInteger(Number(steps)) && Number(steps) >= 500 && Number(steps) <= 10000 && Number(steps) % 100 === 0;

  useEffect(() => {
    if (!taskId) return;
    const controller = new AbortController();
    let timer: number;
    const { signal } = controller;
    setStatusError('');
    setError('');
    setSelectedBody('');
    setEmbodiments(null);
    setPrepareNew(false);
    setApproval(null);

    const refresh = async () => {
      const epoch = statusEpoch.current;
      try {
        if (writeInProgress.current) return;
        const [demos, datasets, jobs] = await Promise.all([
          request<Demo[]>(`${root}/demos`, { signal }),
          request<Dataset[]>(`${root}/datasets`, { signal }),
          request<Job[]>(`${root}/finetunes`, { signal }),
        ]);
        if (!signal.aborted && epoch === statusEpoch.current) {
          setSnapshot({ taskId, demos, datasets, jobs });
          setStatusError('');
        }
      } catch (caught) {
        if (!signal.aborted && epoch === statusEpoch.current) {
          setStatusError(caught instanceof Error ? caught.message : 'Could not check training status.');
        }
      } finally {
        if (!signal.aborted) timer = window.setTimeout(refresh, 4000);
      }
    };
    void refresh();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [root, taskId]);

  useEffect(() => {
    if (!showPreparation) return;
    const controller = new AbortController();
    const { signal } = controller;
    setBodyError('');
    void request<Embodiment[]>('/api/embodiments', { signal }).then((items) => {
      if (!signal.aborted) setEmbodiments(items);
    }).catch((caught: unknown) => {
      if (!signal.aborted) setBodyError(caught instanceof Error ? caught.message : 'Could not load Dream embodiments.');
    });
    return () => controller.abort();
  }, [bodyReload, root, showPreparation]);

  async function write<T>(action: () => Promise<T>, onSaved: (value: T) => void) {
    if (writeInProgress.current) return;
    writeInProgress.current = true;
    statusEpoch.current += 1;
    setBusy(true);
    setError('');
    try { onSaved(await action()); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not save this training step.'); }
    finally { writeInProgress.current = false; setBusy(false); }
  }

  function validateDataset() {
    if (!embodiment || !keptDemos.length) return;
    void write(() => request<Dataset>(`${root}/datasets`, { body: { embodiment_name: embodiment } }), (version) => {
      setSnapshot((previous) => previous?.taskId === taskId
        ? { ...previous, datasets: [version, ...previous.datasets.filter((item) => item.id !== version.id)] } : previous);
      setPrepareNew(false);
    });
  }

  function showJob(saved: Job) {
    setSnapshot((previous) => previous?.taskId === taskId
      ? { ...previous, jobs: [saved, ...previous.jobs.filter((item) => item.id !== saved.id)] } : previous);
  }

  function submitTraining() {
    if (!pendingApproval || !datasetMatchesReview) return;
    void write(() => request<Job>(`/api/datasets/${encodeURIComponent(pendingApproval.datasetId)}/finetunes`, {
      body: { ...pendingApproval.settings, use_eef: false },
    }), (saved) => {
      showJob(saved);
      setApproval(null);
    });
  }

  return <section className="chat-training chat-action" aria-labelledby="chat-training-title">
    <div className="chat-training-header">
      <h2 id="chat-training-title">Fine-tune with Dream Labs</h2>
      <button type="button" className="secondary" disabled={busy} onClick={onClose}>Back to chat</button>
    </div>
    {error && <p className="trial-error" role="alert">{error}</p>}
    {statusError && <p className="trial-error" role="alert">{statusError} Retrying status checks.</p>}
    {!current && !statusError && <p role="status">Checking your demonstrations and training status…</p>}
    {showPreparation && <>
      <p>{keptDemos.length ? `${keptDemos.length} kept ${keptDemos.length === 1 ? 'demonstration is' : 'demonstrations are'} available. Validate a saved copy before training.` : 'Keep at least one valid demonstration before validating a dataset.'}</p>
      {bodyError ? <>
        <p className="trial-error" role="alert">{bodyError}</p>
        <button type="button" className="secondary" onClick={() => setBodyReload((value) => value + 1)}>Retry robot lookup</button>
      </> : <div className="chat-training-form training-controls">
        <label>Registered robot setup<select value={embodiment} disabled={!embodiments?.length || busy} onChange={(event) => setSelectedBody(event.target.value)}>
          <option value="" disabled>{embodiments ? 'Choose a robot setup' : 'Checking Dream Labs setups…'}</option>
          {embodiments?.map((body) => <option key={body.name} value={body.name}>{body.name}{body.video_roles.length ? ` · ${body.video_roles.join(', ')}` : ''}</option>)}
        </select></label>
        <button type="button" disabled={!embodiment || !keptDemos.length || busy} onClick={validateDataset}>Validate dataset</button>
      </div>}
      {embodiments && cameraRoles.length > 0 && !matchingBodies?.length && <div className="chat-workspace-actions">
        <p>Register a setup with these camera roles in your Dream Labs account: {cameraRoles.join(', ')}.</p>
        <button type="button" className="secondary" onClick={() => setBodyReload((value) => value + 1)}>Refresh setups</button>
      </div>}
    </>}
    {!showPreparation && dataset?.status === 'pending_validation' && !job && <p className="chat-training-status" role="status">
      Validating {dataset.demo_ids.length} {dataset.demo_ids.length === 1 ? 'demonstration' : 'demonstrations'} in the background.
      {dataset.error && ` ${dataset.error}`}
    </p>}
    {!showPreparation && dataset?.status === 'failed' && !job && <>
      <p className="chat-training-status" role="status">Dataset validation failed. {dataset.error}</p>
      <button type="button" className="secondary" onClick={() => setPrepareNew(true)}>Prepare a new dataset</button>
    </>}
    {!showPreparation && dataset?.status === 'validated' && !job && <>
      <p className="chat-training-status" role="status">Dataset passed validation with {demoCount} {demoCount === 1 ? 'demonstration' : 'demonstrations'}.</p>
      {!datasetMatchesReview ? <>
        <p>Your kept demos changed after validation. Validate a new dataset with your current selection.</p>
        <button type="button" className="secondary" onClick={() => { setApproval(null); setPrepareNew(true); }}>Prepare updated dataset</button>
      </> : pendingApproval ? <div className="chat-training-approval">
        <h3>Confirm paid training</h3>
        <p>Submit {pendingApproval.settings.steps.toLocaleString()} training steps using this validated dataset? Dream Labs charges by step.</p>
        <div className="chat-workspace-actions">
          <button type="button" disabled={busy} onClick={submitTraining}>Approve and submit</button>
          <button type="button" className="secondary" disabled={busy} onClick={() => setApproval(null)}>Cancel</button>
        </div>
      </div> : <>
        <div className="chat-training-form training-controls">
          <label>Training steps<input type="number" min={500} max={10000} step={100} value={steps} aria-invalid={!validSteps} onChange={(event) => setSteps(event.target.value)} /></label>
          <button type="button" disabled={!validSteps || busy} onClick={() => setApproval({
            datasetId: dataset.id,
            settings: { steps: Number(steps), lr_schedule: schedule, base_share: baseShare },
          })}>Review fine-tune</button>
        </div>
        {!validSteps && <p>Enter a multiple of 100 from 500 to 10,000.</p>}
        <details className="chat-inventory">
          <summary>Training settings</summary>
          <div className="chat-training-form training-controls">
            <label>Learning-rate schedule<select value={schedule} onChange={(event) => setSchedule(event.target.value === 'constant' ? 'constant' : 'cosine')}>
              <option value="cosine">Cosine · specialize for this task</option><option value="constant">Constant · supports later resume</option>
            </select></label>
            <label>Training data<select value={baseShare} onChange={(event) => setBaseShare(event.target.value === '0' ? 0 : 0.5)}>
              <option value={0.5}>Mix in Dream Labs data</option><option value={0}>My demos only</option>
            </select></label>
          </div>
        </details>
        <p>Start with 500 steps for a pilot. Dream Labs charges by step. Check your account for pricing before approving.</p>
      </>}
    </>}
    {!showPreparation && job && <>
      <p className="chat-training-status" role="status">
        {job.status === 'training' && job.remote_status === 'succeeded'
          ? 'Training finished. Waiting for Dream Labs to publish the checkpoint.'
          : statusText[job.status]}
        {(job.status === 'processing' || (job.status === 'training' && job.remote_status !== 'succeeded')) && job.remote_status
          ? ` Status: ${job.remote_status}.` : ''}
      </p>
      {job.error && <p className="trial-error" role={job.status === 'failed' ? 'alert' : 'status'}>{job.error}</p>}
      {job.status === 'failed' && <>
        {job.failure_phase === 'dataset_processing' && job.remote_status === 'failed' && !job.retry_used && !job.remote_job_id && dataset?.remote_id && <button className="secondary" type="button" disabled={busy} onClick={() => void write(
          () => request<Job>(`/api/finetunes/${encodeURIComponent(job.id)}/retry-processing`, { body: {} }), showJob,
        )}>Retry dataset processing</button>}
        <button type="button" className="secondary" onClick={() => setPrepareNew(true)}>Prepare a new dataset</button>
      </>}
      {job.status === 'succeeded' && job.checkpoint && <>
        <div className="chat-training-next">
          <p>Checkpoint ready: <code>{job.checkpoint}</code></p>
          {onCheckpointReady && <button type="button" onClick={() => onCheckpointReady(job.id)}>Continue to evaluation</button>}
        </div>
        {!datasetMatchesReview && keptDemos.length > 0 && <button type="button" className="secondary" onClick={() => setPrepareNew(true)}>Prepare updated dataset</button>}
      </>}
    </>}
  </section>;
}
