import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, Check, ChevronLeft, CircleAlert, Film, RefreshCw } from 'lucide-react';
import { screenHref } from './workspaceRoute';
import './offline-review.css';

type Attempt = {
  episode_id: string; role: 'baseline' | 'candidate'; checkpoint: string; status: string; seed: number;
  source: string; action_rows: number | null; action_budget: number | null; request_count: number | null;
  rule: string | null; evidence: { observation: string; detail: string; first_contact_s: number | null; evidence_s: number | null; peak_lift_m: number | null; longest_hold_s: number | null } | null;
  outcome: boolean | null; failure_stage: string | null; note: string | null; review_revision: number;
  videos: Record<string, string>; video_roles: string[];
};
type Scene = { scene_id: string; seed: number; baseline: Attempt | null; candidate: Attempt | null; comparable: boolean; human_reviewed: boolean; exclusion: string | null };
type Demo = { id: string; origin: string; decision: string; valid: boolean; source_episode_id: string | null; start_cell: number | null; frames: number; fps: number; camera_keys: string[] };
type Review = { task_id: string; label: string; protocol: string; protocol_sha256: string; scenes: Scene[]; planned_scenes: number; comparable_pairs: number; human_reviewed_pairs: number; demos: Demo[] };

const human = (v: boolean | null) => v === null ? 'Not reviewed' : v ? 'Operator: pickup' : 'Operator: no pickup';
const cameraName: Record<string, string> = { overhead: 'Overhead', wrist_l: 'Left wrist', wrist_r: 'Right wrist' };
async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(detail.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function PairVideos({ scene }: { scene: Scene }) {
  const [camera, setCamera] = useState('overhead');
  const lock = useRef(false);
  const refs = useRef<Record<string, HTMLVideoElement | null>>({});
  const roles = ['baseline', 'candidate'] as const;
  const available = new Set(roles.flatMap(role => scene[role]?.video_roles ?? []));
  const jump = (source: 'baseline' | 'candidate', time: number) => {
    lock.current = true;
    for (const role of roles) { const video = refs.current[role]; if (video && role !== source) video.currentTime = time; }
    window.setTimeout(() => { lock.current = false; }, 50);
  };
  return <>
    <div className="offline-camera-tabs" role="group" aria-label={`Scene ${scene.seed} camera`}>
      {['overhead', 'wrist_l', 'wrist_r'].filter(role => available.has(role)).map(role => <button type="button" key={role} aria-pressed={camera === role} onClick={() => setCamera(role)}>{cameraName[role]}</button>)}
    </div>
    <div className="offline-pair-videos">
      {roles.map(role => {
        const attempt = scene[role];
        const src = attempt?.videos[camera];
        return <section key={role} aria-label={`${role} video`}>
          <h3>{role === 'baseline' ? 'Control fixture' : 'Pickup fixture'} <span>{role === 'baseline' ? 'no-op controller' : 'scripted controller'}</span></h3>
          {src ? <video ref={el => { refs.current[role] = el; }} controls playsInline preload="metadata" src={`/api/episodes/${attempt!.episode_id}/video/${camera}`} onSeeked={event => { if (!lock.current) jump(role, event.currentTarget.currentTime); }} /> : <div className="offline-video-missing"><Film size={20}/><span>Side not recorded</span></div>}
          <p>{attempt ? `${attempt.status} · ${attempt.action_rows ?? '—'} executed rows · ${human(attempt.outcome)}` : 'No attempt recorded'}</p>
        </section>;
      })}
    </div>
    <p className="offline-hint">When you seek either video, the other view follows to the same timestamp. The fixture control is scripted and is not a Dream‑1 result.</p>
  </>;
}

function ReviewLabel({ attempt, taskId, refresh }: { attempt: Attempt; taskId: string; refresh: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [note, setNote] = useState(attempt.note ?? '');
  async function save(outcome: boolean | null) {
    setBusy(true); setError('');
    try {
      await json(`/api/episodes/${attempt.episode_id}/label`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: attempt.review_revision, success: outcome, failure_stage: outcome === false ? 'grasp' : null, note: note.trim() || null }) });
      refresh();
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Review could not be saved.'); }
    finally { setBusy(false); }
  }
  return <div className="offline-label" aria-label={`${attempt.role} operator review`}>
    <strong>{human(attempt.outcome)}</strong>{attempt.failure_stage && <span> · {attempt.failure_stage}</span>}
    <label>What did you see?<textarea maxLength={2000} value={note} onChange={event => setNote(event.target.value)} placeholder="Optional: describe the visible behavior, not a guess about its cause." /></label>
    <div><button type="button" disabled={busy} onClick={() => void save(true)}>Label pickup</button><button type="button" className="secondary" disabled={busy} onClick={() => void save(false)}>Label no pickup</button><button type="button" className="secondary" disabled={busy} onClick={() => void save(null)}>Clear label</button></div>
    {error && <p role="alert">{error}</p>}
    <small>Human review only; automatic measurements above remain unchanged.</small>
  </div>;
}

export default function OfflineReview({ taskId }: { taskId: string }) {
  const [review, setReview] = useState<Review | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [demoMessage, setDemoMessage] = useState('');
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoCamera, setDemoCamera] = useState('overhead');
  const refresh = useCallback(() => setReload(value => value + 1), []);
  useEffect(() => {
    if (!taskId) {
      setReview(null); setError('Choose an offline walkthrough task from the Tasks screen or run the dedicated offline-demo command.'); setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true); setError('');
    json<Review>(`/api/offline-review/${encodeURIComponent(taskId)}`, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setReview(value); })
      .catch(caught => { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Could not load offline review.'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [taskId, reload]);

  async function reviewReference(demo: Demo, decision: 'keep' | 'redo') {
    setDemoBusy(true); setDemoMessage(''); setError('');
    try {
      await json(`/api/demos/${demo.id}/decision`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, start_cell: decision === 'keep' ? 4 : null, note: `Offline walkthrough reference only; source run ${demo.source_episode_id ?? 'not linked'}.` }) });
      setDemoMessage(decision === 'keep' ? 'Reference marked Keep for this isolated walkthrough. It is excluded from training.' : 'Reference marked Redo. No dataset or model was changed.');
      refresh();
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Reference review failed.'); }
    finally { setDemoBusy(false); }
  }

  if (loading) return <main className="page"><p role="status">Loading offline walkthrough…</p></main>;
  if (error && !review) return <main className="page"><header className="work-head"><div><h1>Offline walkthrough</h1></div><a href={screenHref('runs', { task: taskId })}>Back to Run review</a></header><p role="alert" className="alert">{error}</p></main>;
  if (!review) return null;
  const demo = review.demos[0];
  return <main className="page offline-review-page">
    <header className="work-head"><div><div className="crumb">Workspace <ChevronRightIcon/> Offline walkthrough</div><p className="eyebrow">Local fixture · no external services</p><h1>See the attempt. Compare the evidence. Decide what to teach.</h1><p className="subtitle">Every controller here is scripted. Nothing on this page is a Dream‑1 or robot result.</p></div><a className="offline-back" href={screenHref('runs', { task: taskId })}><ChevronLeft size={16}/> Run review</a></header>
    {error && <p className="alert" role="alert">{error}</p>}
    <section className="offline-banner"><strong>{review.label}</strong><span> Protocol {review.protocol} · SHA-256 {review.protocol_sha256.slice(0, 12)}…</span></section>
    <section className="offline-summary" aria-label="Walkthrough summary">
      <div><strong>{review.planned_scenes}</strong><span>planned scenes</span></div>
      <div><strong>{review.comparable_pairs}/{review.planned_scenes}</strong><span>complete fixture pairs</span></div>
      <div><strong>{review.human_reviewed_pairs}</strong><span>human-reviewed pairs</span></div>
      <p>These counts describe the built-in fixture only. They are not model success rates.</p>
    </section>
    <section className="offline-flow" aria-label="Review steps"><span className="active">1 · Inspect</span><ArrowRight size={14}/><span>2 · Review labels</span><ArrowRight size={14}/><span>3 · Choose a reference</span><ArrowRight size={14}/><span>4 · Return to the task guide</span></section>
    {review.scenes.map(scene => <article className="offline-scene" key={scene.scene_id}>
      <header><div><p className="eyebrow">Seed {scene.seed} · {scene.scene_id}</p><h2>{scene.comparable ? 'Both fixture recordings are present' : 'Incomplete pair · do not compare outcomes'}</h2></div><span className={`offline-status ${scene.comparable ? 'ok' : 'missing'}`}>{scene.comparable ? 'Fixture complete' : 'Missing evidence'}</span></header>
      {scene.exclusion && <p className="offline-exclusion"><CircleAlert size={16}/>{scene.exclusion}</p>}
      <PairVideos scene={scene}/>
      <div className="offline-evidence-grid">{(['baseline', 'candidate'] as const).map(role => {
        const attempt = scene[role];
        return <section key={role}><h3>{role === 'baseline' ? 'Control observations' : 'Scripted pickup observations'}</h3>{attempt?.evidence ? <><strong>{attempt.evidence.observation.replaceAll('_', ' ')}</strong><p>{attempt.evidence.detail}</p><dl><div><dt>First contact</dt><dd>{attempt.evidence.first_contact_s == null ? 'Not observed' : `${attempt.evidence.first_contact_s.toFixed(2)} s`}</dd></div><div><dt>Peak lift</dt><dd>{attempt.evidence.peak_lift_m == null ? 'Not assessed' : `${(attempt.evidence.peak_lift_m * 100).toFixed(1)} cm`}</dd></div><div><dt>Longest hold</dt><dd>{attempt.evidence.longest_hold_s == null ? 'Not assessed' : `${attempt.evidence.longest_hold_s.toFixed(2)} s`}</dd></div></dl>{attempt.outcome === null && attempt.status === 'complete' && <ReviewLabel attempt={attempt} taskId={taskId} refresh={refresh}/>}</> : <p>No automatic measurement available. Review the video manually.</p>}</section>;
      })}</div>
      <small>Shared rule: {scene.baseline?.rule ?? scene.candidate?.rule ?? 'yam-apple-v1'} · source: offline scripted fixture · operator labels do not change measurements.</small>
    </article>)}
    <section className="offline-demo card"><div><p className="eyebrow">Next · choose a teaching reference</p><h2>Review the scripted demonstration</h2><p>A successful scripted reference can help exercise the review flow. It is not a human correction, a Dream‑1 success, or evidence that training improved a model.</p></div>
      {demo ? <><div className="offline-demo-meta"><span>{demo.origin.replaceAll('_', ' ')}</span><span>{demo.frames} frames · {demo.fps} Hz</span><span>{demo.camera_keys.length} camera views</span><span>{demo.valid ? 'Media checks passed' : 'Media needs review'}</span><span>Decision: {demo.decision}</span></div><div className="role-tabs">{demo.camera_keys.map(key => { const camera = key.replace('observation.images.', ''); return <button key={key} className={camera === demoCamera ? 'role-active' : ''} onClick={() => setDemoCamera(camera)}>{cameraName[camera] || camera}</button>; })}</div><video className="offline-reference-video" controls playsInline preload="metadata" src={`/api/demos/${demo.id}/video/${encodeURIComponent(demoCamera)}`} /><div className="offline-demo-actions"><button type="button" disabled={demoBusy || !demo.valid} onClick={() => void reviewReference(demo, 'keep')}>Keep reference</button><button type="button" className="secondary" disabled={demoBusy} onClick={() => void reviewReference(demo, 'redo')}>Redo</button><small>Local walkthrough only; this fixture is never eligible for training.</small></div></> : <p>No scripted reference was indexed.</p>}
      {demoMessage && <p role="status"><Check size={15}/>{demoMessage}</p>}
    </section>
    <section className="offline-next card"><h2>What should happen next?</h2><div><div><strong>If the video is missing or stops early</strong><p>Inspect capture quality first. Leave the model outcome unlabelled.</p></div><div><strong>If a real attempt touched but did not lift</strong><p>Review a task-matched kept demo; do not infer root cause from contact alone.</p></div><div><strong>To test a real candidate</strong><p>Use the separate predeclared held-out evaluation after a checkpoint exists.</p></div></div><a href={screenHref('guide', { task: taskId })}>Return to this task’s guide <ArrowRight size={15}/></a></section>
    <footer className="offline-footer"><RefreshCw size={14}/> Refresh review to see labels saved by another browser tab. Fixture recordings and operator notes stay local.</footer>
  </main>;
}

function ChevronRightIcon() { return <span aria-hidden="true">›</span>; }
