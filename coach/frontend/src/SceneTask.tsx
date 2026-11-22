import { useEffect, useState } from 'react';

type Shape = 'box' | 'sphere' | 'cylinder';
type Form = {
  prompt: string; objectLabel: string; shape: Shape; objectColor: string;
  startX: number; startY: number; targetLabel: string; targetColor: string;
  targetX: number; targetY: number; radius: number;
};
type Preview = { image: string; width: number; height: number; markers: Record<string, [number, number]> };
type Status = { state: string; task_id?: string; result?: { frames: number; demo_id: string }; error?: string };

const initial: Form = {
  prompt: 'place the red block on the blue pad', objectLabel: 'red block', shape: 'box',
  objectColor: '#d91a1a', startX: 0.15, startY: 0.10,
  targetLabel: 'blue pad', targetColor: '#1a40cc', targetX: 0.15, targetY: -0.10, radius: 0.06,
};
const newSeed = () => Math.floor(Math.random() * 2 ** 32);

function rgba(hex: string): number[] {
  return [1, 3, 5].map((index) => Number.parseInt(hex.slice(index, index + 2), 16) / 255).concat(1);
}

function specification(form: Form) {
  return {
    prompt: form.prompt.trim(),
    object: { label: form.objectLabel.trim(), shape: form.shape,
      size: form.shape === 'box' ? [0.025, 0.025, 0.025] : form.shape === 'sphere' ? [0.027] : [0.025, 0.03],
      mass: 0.07, color: rgba(form.objectColor), start_xy: [form.startX, form.startY] },
    target: { label: form.targetLabel.trim(), xy: [form.targetX, form.targetY],
      radius: form.radius, color: rgba(form.targetColor) },
    goal: { type: 'place_on_target' },
  };
}

async function post<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) });
  const value = await response.json();
  if (!response.ok) throw new Error(value.detail ?? `Request failed (${response.status})`);
  return value as T;
}

export default function SceneTask({ taskId, taskPrompt, onComplete }: {
  taskId: string; taskPrompt: string; onComplete: () => void;
}) {
  const [form, setForm] = useState<Form>(initial);
  const [seed, setSeed] = useState(newSeed);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const currentStatus = status?.task_id === taskId ? status : null;
  const matchesTask = form.prompt.trim() === taskPrompt;

  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const response = await fetch('/api/sim-correction/status');
        if (response.ok && active) setStatus(await response.json() as Status);
      } catch { /* Keep the last status until the local server responds. */ }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2500);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (currentStatus?.state === 'complete' && currentStatus.result?.demo_id) onComplete();
  }, [currentStatus?.result?.demo_id]);

  function update<K extends keyof Form>(field: K, value: Form[K]) {
    setForm((old) => ({ ...old, [field]: value }));
    setPreview(null);
  }

  async function previewScene() {
    setBusy(true); setError('');
    try { setPreview(await post<Preview>('/api/scene-task/preview',
      { spec: specification(form), seed })); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not preview scene.'); }
    finally { setBusy(false); }
  }

  async function record() {
    setBusy(true); setError('');
    try { setStatus(await post<Status>(`/api/tasks/${taskId}/scene-task`,
      { spec: specification(form), seed })); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not record scene.'); }
    finally { setBusy(false); }
  }

  return <section className="card sim-correct">
    <h2>Create a new pick-and-place scene</h2>
    <p>Describe a new object and target. The same simulator planner and physical goal check work across these scene files. This proof of concept supports one rigid box, ball, or cylinder and one marked tabletop target.</p>
    <div className="training-controls">
      <label>Task instruction<input value={form.prompt} onChange={(event) => update('prompt', event.target.value)} /></label>
      <label>Object name<input value={form.objectLabel} onChange={(event) => update('objectLabel', event.target.value)} /></label>
      <label>Shape<select value={form.shape} onChange={(event) => update('shape', event.target.value as Shape)}><option value="box">Box</option><option value="sphere">Ball</option><option value="cylinder">Cylinder</option></select></label>
      <label>Object color<input type="color" value={form.objectColor} onChange={(event) => update('objectColor', event.target.value)} /></label>
      <label>Start X (m)<input type="number" step="0.01" value={form.startX} onChange={(event) => update('startX', Number(event.target.value))} /></label>
      <label>Start Y (m)<input type="number" step="0.01" value={form.startY} onChange={(event) => update('startY', Number(event.target.value))} /></label>
      <label>Target name<input value={form.targetLabel} onChange={(event) => update('targetLabel', event.target.value)} /></label>
      <label>Target color<input type="color" value={form.targetColor} onChange={(event) => update('targetColor', event.target.value)} /></label>
      <label>Target X (m)<input type="number" step="0.01" value={form.targetX} onChange={(event) => update('targetX', Number(event.target.value))} /></label>
      <label>Target Y (m)<input type="number" step="0.01" value={form.targetY} onChange={(event) => update('targetY', Number(event.target.value))} /></label>
      <label>Target radius (m)<input type="number" min="0.04" max="0.09" step="0.01" value={form.radius} onChange={(event) => update('radius', Number(event.target.value))} /></label>
      <label>Scene seed<input type="number" min="0" max="4294967295" value={seed} onChange={(event) => { setSeed(Number(event.target.value)); setPreview(null); }} /></label>
      <button className="secondary" disabled={busy || status?.state === 'recording'} onClick={() => { setSeed(newSeed()); setPreview(null); }}>New seed</button>
      <button className="secondary" disabled={busy || status?.state === 'recording'} onClick={() => void previewScene()}>Preview scene</button>
    </div>
    {!matchesTask && <p className="hint">Create or select a local task with this exact instruction: <strong>{form.prompt.trim()}</strong></p>}
    {preview && <div className="sim-image-wrap"><img src={preview.image} width={preview.width} height={preview.height} alt="YAM simulator scene with the new object and target" />
      {Object.entries(preview.markers).map(([name, [x, y]]) => <span key={name} className="sim-marker" style={{ left: `${x / preview.width * 100}%`, top: `${y / preview.height * 100}%` }}>{name}</span>)}
    </div>}
    <button disabled={!matchesTask || !preview || busy || status?.state === 'recording'} onClick={() => void record()}>Record this new task</button>
    {currentStatus?.state === 'recording' && <p role="status">Recording and validating the new scene…</p>}
    {currentStatus?.state === 'complete' && currentStatus.result && <p className="notice" role="status">Exported {currentStatus.result.frames} verified frames. Review the demo below before keeping it.</p>}
    {(error || currentStatus?.state === 'failed') && <p className="alert" role="alert">{error || currentStatus?.error}</p>}
  </section>;
}
