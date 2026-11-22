import { useEffect, useState } from 'react';

type Preview = {
  image: string; width: number; height: number;
  markers: Record<string, [number, number]>;
  supported: Record<string, string[]>;
};
type Status = {
  state: 'idle' | 'recording' | 'complete' | 'failed';
  task_id?: string;
  result: { session_path: string; frames: number; demo_id: string; physics: { passed: boolean } } | null;
  error: string | null;
};

const newSeed = () => Math.floor(Math.random() * 2 ** 32);

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail ?? `Request failed (${response.status})`);
  return data as T;
}

export default function SimCorrect({ taskId, taskPrompt, onComplete, onSetupTask }: {
  taskId: string; taskPrompt: string; onComplete: () => void;
  onSetupTask: (draft: { name: string; prompt: string; success_rule: string }) => Promise<void>;
}) {
  const [kind, setKind] = useState<'lift' | 'bowl'>('lift');
  const [fruit, setFruit] = useState<'apple' | 'banana'>('apple');
  const [seed, setSeed] = useState(newSeed);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [objectPixel, setObjectPixel] = useState<[number, number] | null>(null);
  const [targetPixel, setTargetPixel] = useState<[number, number] | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const expectedPrompt = kind === 'lift' ? `pick up the ${fruit}` : 'put the apple in the bowl';
  const ready = taskPrompt === expectedPrompt;
  const currentStatus = status?.task_id === taskId ? status : null;

  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const state = await request<Status>('/api/sim-correction/status');
        if (active) setStatus(state);
      } catch { /* The next poll can recover after a local server restart. */ }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2500);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (currentStatus?.state === 'complete' && currentStatus.result?.demo_id) onComplete();
  // The completion marker changes once per job. Refreshing the same result is harmless.
  }, [currentStatus?.result?.demo_id]);

  async function loadScene(nextSeed = seed, nextFruit = fruit) {
    setLoading(true); setError(''); setObjectPixel(null); setTargetPixel(null); setPreview(null);
    try {
      setPreview(await request<Preview>(`/api/sim-correction/scene?fruit=${nextFruit}&seed=${nextSeed}`));
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not render scene.'); }
    finally { setLoading(false); }
  }

  function choosePixel(event: React.MouseEvent<HTMLImageElement>) {
    if (!preview || status?.state === 'recording') return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const pixel: [number, number] = [
      (event.clientX - bounds.left) * preview.width / bounds.width,
      (event.clientY - bounds.top) * preview.height / bounds.height,
    ];
    if (!objectPixel || (kind === 'bowl' && targetPixel)) {
      setObjectPixel(pixel); setTargetPixel(null);
    } else if (kind === 'bowl') setTargetPixel(pixel);
    else setObjectPixel(pixel);
  }

  async function record() {
    if (!taskId || !objectPixel || (kind === 'bowl' && !targetPixel)) return;
    setLoading(true); setError('');
    try {
      setStatus(await request<Status>(`/api/tasks/${taskId}/sim-correction`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind, fruit, seed, object_pixel: objectPixel,
          target_pixel: kind === 'bowl' ? targetPixel : null }),
      }));
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Recording failed to start.'); }
    finally { setLoading(false); }
  }

  async function setupTask() {
    setLoading(true); setError('');
    try {
      await onSetupTask({
        name: kind === 'bowl' ? 'Apple placement · click to correct' : `${fruit} lift · click to correct`,
        prompt: expectedPrompt,
        success_rule: kind === 'bowl'
          ? 'Lift the apple, release it into the bowl, and leave it resting inside.'
          : `Lift the ${fruit} at least 8 cm, then lower and release it.`,
      });
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not set up the local task.'); }
    finally { setLoading(false); }
  }

  return <section className="card sim-correct">
    <h2>Click to correct in YAM simulation</h2>
    <p>Choose a supported task, click the fruit, then click the bowl for placement. The simulator plans the arm motion, checks the physical result, and exports a demo for review. No physical robot, Dream API call, or training job starts here.</p>
    <div className="training-controls">
      <label>Goal<select value={kind} onChange={(event) => { const next = event.target.value as 'lift' | 'bowl'; setKind(next); if (next === 'bowl') setFruit('apple'); setPreview(null); setObjectPixel(null); setTargetPixel(null); }}><option value="lift">Lift fruit</option><option value="bowl">Put fruit in bowl</option></select></label>
      <label>Object<select value={fruit} onChange={(event) => { const next = event.target.value as 'apple' | 'banana'; setFruit(next); setPreview(null); setObjectPixel(null); }}><option value="apple">Apple</option>{kind === 'lift' && <option value="banana">Banana</option>}</select></label>
      <label>Scene seed<input type="number" min="0" max="4294967295" value={seed} onChange={(event) => { setSeed(Number(event.target.value)); setPreview(null); }} /></label>
      <button className="secondary" disabled={loading || status?.state === 'recording'} onClick={() => { const next = newSeed(); setSeed(next); void loadScene(next); }}>New scene</button>
      <button className="secondary" disabled={loading || status?.state === 'recording'} onClick={() => void loadScene()}>Load scene</button>
    </div>
    {!ready && <p className="hint">Set up the local task for <strong>{expectedPrompt}</strong> before recording.</p>}
    {!ready && <button className="secondary" disabled={loading || status?.state === 'recording'} onClick={() => void setupTask()}>Set up this fruit task</button>}
    {preview && <div className="sim-image-wrap"><img src={preview.image} width={preview.width} height={preview.height} alt="YAM overhead simulator scene; click a fruit and optional bowl target" onClick={choosePixel} />
      {Object.entries(preview.markers).map(([name, [x, y]]) => <span key={name} className="sim-marker" style={{ left: `${x / preview.width * 100}%`, top: `${y / preview.height * 100}%` }} title={name}>{name}</span>)}
      {objectPixel && <span className="sim-click" style={{ left: `${objectPixel[0] / preview.width * 100}%`, top: `${objectPixel[1] / preview.height * 100}%` }}>1</span>}
      {targetPixel && <span className="sim-click" style={{ left: `${targetPixel[0] / preview.width * 100}%`, top: `${targetPixel[1] / preview.height * 100}%` }}>2</span>}
    </div>}
    {preview && <p className="hint">{!objectPixel ? 'Click the selected fruit.' : kind === 'bowl' && !targetPixel ? 'Now click inside the bowl.' : 'Review the two clicks, then record.'} Unsupported tasks need their own motion and success-check adapter.</p>}
    <button disabled={!ready || !preview || !objectPixel || (kind === 'bowl' && !targetPixel) || loading || status?.state === 'recording'} onClick={() => void record()}>Record and verify demo</button>
    {currentStatus?.state === 'recording' && <p role="status">Recording three camera videos and validating the result…</p>}
    {currentStatus?.state === 'complete' && currentStatus.result && <p className="notice" role="status">Physical goal passed. Exported {currentStatus.result.frames} frames. Review this demo below before keeping it.</p>}
    {(error || currentStatus?.state === 'failed') && <p className="alert" role="alert">{error || currentStatus?.error}</p>}
  </section>;
}
