import { useEffect, useState } from 'react';

type Task = { id: string; name: string };
type Embodiment = { name: string; id: string | null; video_roles: string[] };
type Report = { ok?: boolean; episodes?: number; frames?: number; bytes?: number; error?: string | null };
type Dataset = {
  id: string; task_id: string; embodiment_name: string; demo_ids: string[];
  status: string; validation_report: Report | null; error: string | null;
  remote_id: string | null; remote_name: string | null; created_at: string;
};
type Job = {
  id: string; dataset_version_id: string; steps: number; lr_schedule: string; base_share: number;
  use_eef: boolean; status: string; remote_job_id: string | null;
  remote_status: string | null;
  failure_phase: string | null;
  checkpoint: string | null; error: string | null;
  resume_from: string | null;
};

async function json<T>(url: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail ?? `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export default function Training({ onEvaluate }: { onEvaluate?: () => void }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskId, setTaskId] = useState('');
  const [bodies, setBodies] = useState<Embodiment[]>([]);
  const [embodiment, setEmbodiment] = useState('');
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [steps, setSteps] = useState(1000);
  const [schedule, setSchedule] = useState<'cosine' | 'constant'>('cosine');
  const [baseShare, setBaseShare] = useState<0 | 0.5>(0.5);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const selectedTask = tasks.find((task) => task.id === taskId);
  const readyDataset = datasets.find((version) => version.status === 'validated');
  const readyJob = jobs.find((job) => job.status === 'succeeded' && job.checkpoint);
  const activeJob = jobs.find((job) => ['pending_upload', 'processing', 'pending_training', 'training'].includes(job.status));

  useEffect(() => {
    void json<Task[]>('/api/tasks').then((values) => { setTasks(values); if (values.length) setTaskId(values[0].id); }).catch((caught: Error) => setError(caught.message));
    void json<Embodiment[]>('/api/embodiments').then((values) => { setBodies(values); if (values.length) setEmbodiment(values[0].name); }).catch((caught: Error) => setError(caught.message));
  }, []);

  useEffect(() => {
    if (!taskId) return;
    let active = true;
    const refresh = async () => {
      try {
        const [versions, work] = await Promise.all([
          json<Dataset[]>(`/api/tasks/${taskId}/datasets`),
          json<Job[]>(`/api/tasks/${taskId}/finetunes`),
        ]);
        if (active) { setDatasets(versions); setJobs(work); }
      } catch (caught) { if (active) setError(caught instanceof Error ? caught.message : 'Could not load training jobs.'); }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10000);
    return () => { active = false; window.clearInterval(timer); };
  }, [taskId]);

  async function createDataset() {
    if (!embodiment || !taskId) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const version = await json<Dataset>(`/api/tasks/${taskId}/datasets`, 'POST', { embodiment_name: embodiment });
      setDatasets(await json<Dataset[]>(`/api/tasks/${taskId}/datasets`));
      setMessage(`Dataset version ${version.id.slice(0, 8)} queued for local validation. The worker will copy kept demos.`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not create dataset.'); }
    finally { setBusy(false); }
  }

  async function submit(version: Dataset) {
    if (!Number.isInteger(steps) || steps < 500 || steps > 10000 || steps % 100 !== 0) { setError('Steps must be a multiple of 100 from 500 to 10,000.'); return; }
    if (!window.confirm(`Submit a paid Dream Labs fine-tune for ${version.demo_ids.length} demos and ${steps} training steps? FaaS charges by step. Continue?`)) return;
    setBusy(true); setError(''); setMessage('');
    try {
      await json<Job>(`/api/datasets/${version.id}/finetunes`, 'POST', {
        steps, lr_schedule: schedule, base_share: baseShare, use_eef: false,
      });
      setJobs(await json<Job[]>(`/api/tasks/${taskId}/finetunes`));
      setMessage('Training request queued. The worker will upload the dataset, wait for processing, then submit FaaS.');
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not queue fine-tune.'); }
    finally { setBusy(false); }
  }

  async function continueJob(job: Job) {
    if (!job.checkpoint || !window.confirm(`Submit another paid 500-step FaaS job from ${job.checkpoint}? The paired evaluation must show a positive but inconclusive gain.`)) return;
    setBusy(true); setError(''); setMessage('');
    try {
      await json<Job>(`/api/datasets/${job.dataset_version_id}/finetunes`, 'POST', {
        steps: 500, lr_schedule: 'constant', base_share: job.base_share,
        use_eef: job.use_eef, resume_from: job.checkpoint,
      });
      setJobs(await json<Job[]>(`/api/tasks/${taskId}/finetunes`));
      setMessage('A 500-step continuation was queued. The worker reconciles it by its unique suffix.');
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not queue continuation.'); }
    finally { setBusy(false); }
  }

  async function retryProcessing(job: Job) {
    setBusy(true); setError(''); setMessage('');
    try {
      await json<Job>(`/api/finetunes/${job.id}/retry-processing`, 'POST');
      setJobs(await json<Job[]>(`/api/tasks/${taskId}/finetunes`));
      setMessage('Dream dataset processing is retrying. The worker will continue when it is processed.');
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not retry processing.'); }
    finally { setBusy(false); }
  }

  return <main className="page">
    <header className="header"><div><p className="eyebrow">Dream Labs FaaS</p><h1>Fine-tune workspace</h1><p className="subtitle">Collect reviewed demos, freeze a dataset, train through FaaS, then compare the candidate on held-out scenes.</p></div></header>
    {error && <div className="alert" role="alert">{error}</div>}
    {message && <div className="notice" role="status">{message}</div>}
    <section className="card pipeline-steps" aria-label="Fine-tuning steps">
      <div className={taskId ? 'pipeline-done' : ''}><span>1</span><strong>Define task</strong><small>{selectedTask?.name ?? 'Choose a task'}</small></div>
      <div className={readyDataset ? 'pipeline-done' : ''}><span>2</span><strong>Validate demos</strong><small>{readyDataset ? `${readyDataset.demo_ids.length} demos frozen` : 'Create a dataset version'}</small></div>
      <div className={readyJob ? 'pipeline-done' : activeJob ? 'pipeline-active' : ''}><span>3</span><strong>Fine-tune</strong><small>{readyJob ? 'Checkpoint ready' : activeJob ? `Job ${activeJob.status.replaceAll('_', ' ')}` : 'Submit FaaS job'}</small></div>
      <div><span>4</span><strong>Evaluate</strong><small>Matched held-out scenes</small></div>
    </section>
    {readyJob && <section className="card training-next"><div><h2>Candidate checkpoint ready</h2><p>{readyJob.checkpoint} can now be compared with the task baseline. Plan the evaluation before running either model.</p></div><button type="button" onClick={onEvaluate} disabled={!onEvaluate}>Plan evaluation</button></section>}
    <div className="training-controls card">
      <label>Task<select value={taskId} onChange={(event) => setTaskId(event.target.value)}>{tasks.map((task) => <option key={task.id} value={task.id}>{task.name}</option>)}</select></label>
      <label>Registered embodiment<select value={embodiment} onChange={(event) => setEmbodiment(event.target.value)}>{bodies.map((body) => <option key={body.name} value={body.name}>{body.name} · {body.video_roles.join(', ')}</option>)}</select></label>
      <button disabled={busy || !taskId || !embodiment} onClick={() => void createDataset()}>Create dataset version</button>
    </div>
    <p className="hint">Run <code>teach-task-coach worker</code> alongside the API. Statuses update here every 10 seconds. Your Dream credentials stay in the backend.</p>
    <div className="training-controls card">
      <label>Steps<input type="number" min={500} max={10000} step={100} value={steps} onChange={(event) => setSteps(Number(event.target.value))} /></label>
      <label>Learning-rate schedule<select value={schedule} onChange={(event) => setSchedule(event.target.value as 'cosine' | 'constant')}><option value="cosine">Cosine · single-task specialization</option><option value="constant">Constant · supports later resume</option></select></label>
      <label>Training data<select value={baseShare} onChange={(event) => setBaseShare(Number(event.target.value) as 0 | 0.5)}><option value={0.5}>Mix in Dream Labs data (0.5)</option><option value={0}>My demos only (0.0)</option></select></label>
    </div>
    <p className="hint">Dream charges by training step; this app has no price quote API. Confirm the charge in your Dream account before submitting. Record the dataset and settings so later evaluations can identify the checkpoint. The initial recipe is 1,000 steps, cosine, and a 0.5 data mix.</p>
    <section className="card training-list"><h2>Dataset versions</h2>
      {datasets.length === 0 && <p>No versions yet. Keep at least one valid demo, then create a version.</p>}
      {datasets.map((version) => <div className="training-row" key={version.id}>
        <div><strong>Version {version.id.slice(0, 8)}</strong><small>{version.demo_ids.length} demos · {version.embodiment_name}</small><small>Status: {version.status}{version.remote_id ? ` · ${version.remote_id}` : ''}</small>{version.validation_report && <small>Validation: {version.validation_report.episodes ?? '—'} episodes, {version.validation_report.frames ?? '—'} frames</small>}{version.error && <small className="trial-error">{version.error}</small>}</div>
        {version.status === 'validated' && !jobs.some((job) => job.dataset_version_id === version.id) && <button disabled={busy} onClick={() => void submit(version)}>Submit fine-tune</button>}
      </div>)}
    </section>
    <section className="card training-list"><h2>Fine-tune jobs</h2>
      {jobs.length === 0 && <p>No jobs submitted.</p>}
      {jobs.map((job) => <div className="training-row" key={job.id}><div><strong>Job {job.id.slice(0, 8)}</strong><small>{job.steps} steps · {job.lr_schedule} · base share {job.base_share}{job.resume_from ? ` · resumed from ${job.resume_from}` : ''}</small><small>Status: {job.status === 'training' ? (job.remote_status ?? 'submitted to Dream') : job.status === 'processing' ? `dataset ${job.remote_status ?? 'processing'}` : job.status}{job.remote_job_id ? ` · ${job.remote_job_id}` : ''}</small>{job.checkpoint && <small className="model-ready">Checkpoint: {job.checkpoint}</small>}{job.error && <small className="trial-error">{job.error}</small>}</div>{job.status === 'failed' && job.failure_phase === 'dataset_processing' && (job.remote_status === 'failed' || job.remote_status === null) && !job.remote_job_id && datasets.some((version) => version.id === job.dataset_version_id && version.remote_id) && <button className="secondary" disabled={busy} onClick={() => void retryProcessing(job)}>Retry dataset processing</button>}{job.status === 'succeeded' && job.lr_schedule === 'constant' && job.checkpoint && !jobs.some((other) => other.resume_from === job.checkpoint) && <button className="secondary" disabled={busy} onClick={() => void continueJob(job)}>Continue 500 steps</button>}</div>)}
    </section>
  </main>;
}
