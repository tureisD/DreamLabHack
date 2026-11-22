import { useEffect, useState } from 'react';
import SimCorrect from './SimCorrect';

type Task = { id: string; name: string; prompt: string };
type Finding = { code: string; severity: 'error' | 'review'; message: string };
type Demo = {
  id: string; task_id: string; source_path: string; task_text: string; codebase_version: string;
  frames: number; fps: number; camera_keys: string[]; state_dim: number | null; action_dim: number | null;
  findings: Finding[]; decision: 'unreviewed' | 'keep' | 'redo'; start_cell: number | null; note: string | null;
};
type Cell = { cell: number; baseline_runs: number; baseline_failures: number; kept_demos: number; priority: number };
type Plan = { cells: Cell[]; next_cell: number | null; reason: string; observed_failure_cells_covered: boolean };
type ImportResult = { imported: number; skipped: string[] };
type TeleopStatus = { state: string; session_path: string | null; exit_code: number | null; log_tail: string | null };

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

export default function Demos() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskId, setTaskId] = useState('');
  const [demos, setDemos] = useState<Demo[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [role, setRole] = useState('');
  const [cell, setCell] = useState(0);
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [followerPort, setFollowerPort] = useState('');
  const [leaderPort, setLeaderPort] = useState('');
  const [followerId, setFollowerId] = useState('so101_follower');
  const [leaderId, setLeaderId] = useState('so101_leader');
  const [cameraIndex, setCameraIndex] = useState(0);
  const [teleop, setTeleop] = useState<TeleopStatus | null>(null);
  const selected = demos.find((demo) => demo.id === selectedId);

  useEffect(() => {
    void json<Task[]>('/api/tasks').then((values) => {
      setTasks(values);
      if (values.length) setTaskId(values[0].id);
    }).catch((caught: Error) => setError(caught.message));
  }, []);

  useEffect(() => {
    if (!taskId) return;
    let active = true;
    const refresh = async () => {
      try {
        await json<ImportResult>(`/api/tasks/${taskId}/demos/import`, 'POST');
        const [values, coverage] = await Promise.all([
          json<Demo[]>(`/api/tasks/${taskId}/demos`),
          json<Plan>(`/api/tasks/${taskId}/demo-plan`),
        ]);
        if (active) { setDemos(values); setPlan(coverage); }
        const state = await json<TeleopStatus>('/api/teleop/status');
        if (active) setTeleop(state);
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : 'Could not scan demos.');
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [taskId]);

  async function scan() {
    if (!taskId) return;
    setBusy(true); setError('');
    try {
      const result = await json<ImportResult>(`/api/tasks/${taskId}/demos/import`, 'POST');
      setDemos(await json<Demo[]>(`/api/tasks/${taskId}/demos`));
      setPlan(await json<Plan>(`/api/tasks/${taskId}/demo-plan`));
      setMessage(`Indexed ${result.imported} sessions.${result.skipped.length ? ` Skipped: ${result.skipped.join('; ')}` : ''}`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not scan demos.'); }
    finally { setBusy(false); }
  }

  async function record() {
    if (!taskId || !window.confirm('The Dream station process must be stopped and the SO-101 workspace clear. Begin one supervised leader/follower recording?')) return;
    setBusy(true); setError('');
    try {
      const status = await json<TeleopStatus>(`/api/tasks/${taskId}/teleop/start`, 'POST', {
        follower_port: followerPort, leader_port: leaderPort, follower_id: followerId,
        leader_id: leaderId, camera_index: cameraIndex, seconds: 30,
      });
      setTeleop(status); setMessage('LeRobot recording launched. Stay with the arms; the session ends after one episode.');
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not start recorder.'); }
    finally { setBusy(false); }
  }

  async function stopRecording() {
    setBusy(true); setError('');
    try {
      setTeleop(await json<TeleopStatus>('/api/teleop/stop', 'POST'));
      setMessage('Stopping the recorder. This episode will need review before it can be kept.');
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not stop recorder.'); }
    finally { setBusy(false); }
  }

  async function decide(decision: 'keep' | 'redo') {
    if (!selected) return;
    setBusy(true); setError('');
    try {
      await json<Demo>(`/api/demos/${selected.id}/decision`, 'POST', {
        decision, start_cell: decision === 'keep' ? cell : null, note: note.trim() || null,
      });
      setDemos(await json<Demo[]>(`/api/tasks/${taskId}/demos`));
      setPlan(await json<Plan>(`/api/tasks/${taskId}/demo-plan`));
      setMessage(`Demo marked ${decision}.`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not save decision.'); }
    finally { setBusy(false); }
  }

  function choose(demo: Demo) {
    setSelectedId(demo.id);
    setRole(demo.camera_keys[0]?.replace('observation.images.', '') ?? '');
    setCell(demo.start_cell ?? 0);
    setNote(demo.note ?? '');
  }

  return <main className="page">
    <header className="header"><div><p className="eyebrow">Record what matters</p><h1>Demonstrations</h1><p className="subtitle">Completed LeRobot episodes appear here shortly after the recorder saves them.</p></div><button onClick={() => void scan()} disabled={busy || !taskId}>Scan now</button></header>
    {error && <div className="alert" role="alert">{error}</div>}
    {message && <div className="notice" role="status">{message}</div>}
    <div className="demo-task-select"><label>Task <select value={taskId} onChange={(event) => { setTaskId(event.target.value); setSelectedId(''); }}>{tasks.map((task) => <option value={task.id} key={task.id}>{task.name}</option>)}</select></label></div>
    <section className="card teleop-controls"><h2>SO-101 leader/follower recording</h2><p>Stop the Dream station process before using the same arm with LeRobot. This records one local episode and does not upload it to Hugging Face.</p><div className="training-controls"><label>Follower port<input value={followerPort} onChange={(event) => setFollowerPort(event.target.value)} placeholder="/dev/ttyACM0" /></label><label>Leader port<input value={leaderPort} onChange={(event) => setLeaderPort(event.target.value)} placeholder="/dev/ttyACM1" /></label><label>Follower ID<input value={followerId} onChange={(event) => setFollowerId(event.target.value)} /></label><label>Leader ID<input value={leaderId} onChange={(event) => setLeaderId(event.target.value)} /></label><label>Camera index<input type="number" min={0} value={cameraIndex} onChange={(event) => setCameraIndex(Number(event.target.value))} /></label><button disabled={busy || !taskId || !followerPort || !leaderPort || teleop?.state === 'recording' || teleop?.state === 'stopping'} onClick={() => void record()}>Record one demo</button>{teleop?.state === 'recording' && <button className="secondary" disabled={busy} onClick={() => void stopRecording()}>Stop recording</button>}</div><p className="hint">Recorder: {teleop?.state ?? 'idle'}{teleop?.session_path ? ` · ${teleop.session_path}` : ''}. Restart the station after the recording exits, then review the new demo below.</p>{teleop?.state === 'failed' && teleop.log_tail && <pre className="trial-error">{teleop.log_tail}</pre>}</section>
    <SimCorrect taskId={taskId} taskPrompt={tasks.find((task) => task.id === taskId)?.prompt ?? ''} onComplete={() => void scan()} />
    <section className="card"><h2>Collect without a robot: failed-scene replay</h2><p>For the YAM apple task, record model runs on fresh simulator seeds, then generate corrective trajectories only for failed scenes. The collector diversifies failure modes and apple positions, excludes reserved evaluation and prior training seeds, audits the physics replay, and exports Dream-validated LeRobot episodes. Review each demo here before keeping it.</p><pre className="hint">uv run --locked python experiments/yam_sim_faas/collect_failure_demos.py --model-rollouts PATH_TO_FRESH_MODEL_RUNS --max-demos 8</pre><p className="hint">This local command uses no robot or paid training job. The prerequisite model rollouts use Dream inference; their API cost and simulator limits still apply. This collector currently supports the YAM apple scene only.</p></section>
    {plan && <section className="card coverage">
      <div className="card-heading"><h2>What to record next</h2><span className="count">{plan.observed_failure_cells_covered ? 'Observed failure cells covered' : 'Coverage in progress'}</span></div>
      <p>{plan.reason}</p>
      <div className="coverage-grid">{plan.cells.map((item) => <div key={item.cell} className={`coverage-cell ${plan.next_cell === item.cell ? 'coverage-next' : ''}`}><strong>Cell {item.cell + 1}</strong><span>{item.baseline_failures}/{item.baseline_runs} baseline failures</span><span>{item.kept_demos} kept demos</span></div>)}</div>
      <p className="hint">Coverage is a collection guide, not a claim that the model will succeed. Placement cell is labelled by the operator.</p>
    </section>}
    <div className="runs-layout demo-layout">
      <section className="card runs-list"><div className="card-heading"><h2>Recorded demos</h2><span className="count">{demos.length}</span></div>{demos.length === 0 && <p>No matching one-episode sessions found. Set COACH_DEMOS_DIR to the recorder output directory and use the task instruction as the dataset task text.</p>}{demos.map((demo) => <button className={`run-row ${selectedId === demo.id ? 'selected' : ''}`} key={demo.id} onClick={() => choose(demo)}><strong>{demo.source_path.split(/[\\/]/).pop()}</strong><span>{demo.frames} frames · {demo.fps} fps</span><small>{demo.decision} · {demo.findings.length} QC findings</small></button>)}</section>
      <section className="card review">{!selected ? <p>Select a demo to inspect it and decide whether to keep it.</p> : <>
        <div className="card-heading"><h2>{selected.source_path.split(/[\\/]/).pop()}</h2><span className="count">{selected.decision}</span></div>
        <p className="muted">{selected.task_text} · LeRobot {selected.codebase_version}</p>
        <div className="role-tabs">{selected.camera_keys.map((key) => { const name = key.replace('observation.images.', ''); return <button key={key} className={role === name ? 'role-active' : ''} onClick={() => setRole(name)}>{name}</button>; })}</div>
        {role && <video key={`${selected.id}-${role}`} controls preload="metadata" src={`/api/demos/${selected.id}/video/${encodeURIComponent(role)}`} />}
        <dl className="details"><div><dt>Frames</dt><dd>{selected.frames}</dd></div><div><dt>Rate</dt><dd>{selected.fps} fps</dd></div><div><dt>State / action</dt><dd>{selected.state_dim ?? '—'} / {selected.action_dim ?? '—'} values</dd></div></dl>
        <h3>Quality checks</h3>
        {selected.findings.length ? selected.findings.map((finding) => <div key={finding.code} className={`finding ${finding.severity === 'error' ? 'finding-problem' : 'finding-warning'}`}><strong>{finding.message}</strong><small>{finding.severity === 'error' ? 'Must fix before keeping' : 'Review before keeping'}</small></div>) : <p className="muted">No structural or idle-action issues found. Camera visibility and motion smoothness are not assessed yet.</p>}
        <div className="label-form"><label>Object start cell<select value={cell} onChange={(event) => setCell(Number(event.target.value))}>{Array.from({ length: 9 }, (_, index) => <option key={index} value={index}>Cell {index + 1}</option>)}</select></label><label>Note<textarea maxLength={2000} value={note} onChange={(event) => setNote(event.target.value)} /></label><div className="decision-actions"><button onClick={() => void decide('keep')} disabled={busy || selected.findings.some((finding) => finding.severity === 'error')}>Keep demo</button><button className="secondary" onClick={() => void decide('redo')} disabled={busy}>Redo</button></div></div>
      </>}</section>
    </div>
  </main>;
}
