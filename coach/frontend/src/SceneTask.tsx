import { useState } from 'react';
import { simulatorRequest, useSimulatorRecording, type SimulatorTaskDraft } from './useSimulatorRecording';

type Shape = 'box' | 'sphere' | 'cylinder';
export type ScenePreset = 'block' | 'ball' | 'custom';
type Form = {
  prompt: string; objectLabel: string; shape: Shape; objectColor: string;
  sizeX: number; sizeY: number; sizeZ: number; mass: number;
  startX: number; startY: number; targetLabel: string; targetColor: string;
  targetX: number; targetY: number; radius: number;
};
type Preview = { image: string; width: number; height: number; markers: Record<string, [number, number]> };

const initial: Form = {
  prompt: 'place the red block on the blue pad', objectLabel: 'red block', shape: 'box',
  objectColor: '#d91a1a', sizeX: 0.025, sizeY: 0.025, sizeZ: 0.025,
  mass: 0.07, startX: 0.15, startY: 0.10,
  targetLabel: 'blue pad', targetColor: '#1a40cc', targetX: 0.15, targetY: -0.10, radius: 0.06,
};
const ballPreset: Form = {
  ...initial, prompt: 'move the yellow ball onto the green pad', objectLabel: 'yellow ball',
  shape: 'sphere', objectColor: '#ebbf1a', sizeX: 0.027, mass: 0.06, startX: 0.18, startY: 0.08,
  targetLabel: 'green pad', targetColor: '#1fa633', targetX: 0.12, targetY: -0.07,
};
const customDefaults: Form = { ...initial, prompt: '', objectLabel: '', targetLabel: '' };
const newSeed = () => Math.floor(Math.random() * 2 ** 32);

function rgba(hex: string): number[] {
  return [1, 3, 5].map((index) => Number.parseInt(hex.slice(index, index + 2), 16) / 255).concat(1);
}

function specification(form: Form) {
  return {
    prompt: form.prompt.trim(),
    object: { label: form.objectLabel.trim(), shape: form.shape,
      size: form.shape === 'box' ? [form.sizeX, form.sizeY, form.sizeZ] :
        form.shape === 'sphere' ? [form.sizeX] : [form.sizeX, form.sizeZ],
      mass: form.mass, color: rgba(form.objectColor), start_xy: [form.startX, form.startY] },
    target: { label: form.targetLabel.trim(), xy: [form.targetX, form.targetY],
      radius: form.radius, color: rgba(form.targetColor) },
    goal: { type: 'place_on_target' },
  };
}

export default function SceneTask({
  taskId, taskPrompt, taskSuccessRule, onComplete, onSetupTask, initialPreset = 'block', inline = false,
}: {
  taskId: string; taskPrompt: string; taskSuccessRule?: string;
  onComplete: (demoId: string) => void;
  onSetupTask: (draft: SimulatorTaskDraft) => Promise<void>;
  initialPreset?: ScenePreset;
  inline?: boolean;
}) {
  const [form, setForm] = useState<Form>(() => {
    if (initialPreset === 'ball') return ballPreset;
    if (initialPreset === 'custom') return customDefaults;
    return initial;
  });
  const [preset, setPreset] = useState(initialPreset);
  const [seed, setSeed] = useState(newSeed);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const { currentStatus, recording, start } = useSimulatorRecording('scene', taskId, inline, onComplete);
  const object = form.objectLabel.trim();
  const target = form.targetLabel.trim();
  const sceneName = Array.from(`${object} to ${target}`).slice(0, 108).join('').trimEnd();
  const draft: SimulatorTaskDraft = {
    name: `${sceneName} · YAM scene`,
    prompt: form.prompt.trim(),
    success_rule: `Lift the ${object} and release it so it rests on the ${target}.`,
  };
  const matchesTask = Boolean(taskId) && draft.prompt === taskPrompt && (!inline || draft.success_rule === taskSuccessRule);
  const hasSceneDetails = Boolean(draft.prompt && object && target);
  const locked = busy || recording;

  function update<K extends keyof Form>(field: K, value: Form[K]) {
    setPreset('custom');
    setForm((old) => ({ ...old, [field]: value }));
    setPreview(null);
  }

  async function previewScene() {
    setBusy(true); setError('');
    try {
      setPreview(await simulatorRequest<Preview>('/api/scene-task/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ spec: specification(form), seed }),
      }));
    }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not preview scene.'); }
    finally { setBusy(false); }
  }

  async function record() {
    setBusy(true); setError('');
    try { await start({ spec: specification(form), seed }); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not record scene.'); }
    finally { setBusy(false); }
  }

  async function setupTask() {
    setBusy(true); setError('');
    try { await onSetupTask(draft); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not set up the local scene task.'); }
    finally { setBusy(false); }
  }

  const sceneDimensions = <div className="training-controls">
      <label>{form.shape === 'box' ? 'Half width (m)' : 'Radius (m)'}<input type="number" min="0.015" max="0.05" step="0.005" value={form.sizeX} onChange={(event) => update('sizeX', Number(event.target.value))} /></label>
      {form.shape === 'box' && <label>Half depth (m)<input type="number" min="0.015" max="0.05" step="0.005" value={form.sizeY} onChange={(event) => update('sizeY', Number(event.target.value))} /></label>}
      {form.shape !== 'sphere' && <label>Half height (m)<input type="number" min="0.015" max="0.05" step="0.005" value={form.sizeZ} onChange={(event) => update('sizeZ', Number(event.target.value))} /></label>}
      <label>Object mass (kg)<input type="number" min="0.02" max="0.25" step="0.01" value={form.mass} onChange={(event) => update('mass', Number(event.target.value))} /></label>
      <label>Start X (m)<input type="number" step="0.01" value={form.startX} onChange={(event) => update('startX', Number(event.target.value))} /></label>
      <label>Start Y (m)<input type="number" step="0.01" value={form.startY} onChange={(event) => update('startY', Number(event.target.value))} /></label>
      <label>Target X (m)<input type="number" step="0.01" value={form.targetX} onChange={(event) => update('targetX', Number(event.target.value))} /></label>
      <label>Target Y (m)<input type="number" step="0.01" value={form.targetY} onChange={(event) => update('targetY', Number(event.target.value))} /></label>
      <label>Target radius (m)<input type="number" min="0.04" max="0.09" step="0.01" value={form.radius} onChange={(event) => update('radius', Number(event.target.value))} /></label>
      <label>Scene seed<input type="number" min="0" max="4294967295" value={seed} onChange={(event) => { setSeed(Number(event.target.value)); setPreview(null); }} /></label>
      <button type="button" className="secondary" onClick={() => { setSeed(newSeed()); setPreview(null); }}>New seed</button>
  </div>;

  return <section className={inline ? 'sim-correct' : 'card sim-correct'}>
    <h2>Create a new pick-and-place scene</h2>
    <p>Choose an object and a tabletop target, preview the scene, and approve the task before recording.</p>
    <fieldset className="sim-recorder-fields" disabled={locked} aria-label="Scene configuration">
      <div className="training-controls">
        <label>Scene preset<select value={preset} onChange={(event) => {
          const next = event.target.value as typeof preset;
          setPreset(next);
          if (next !== 'custom') setForm(next === 'ball' ? ballPreset : initial);
          setPreview(null);
        }}><option value="block">Red block → blue pad</option><option value="ball">Yellow ball → green pad</option><option value="custom">Custom scene</option></select></label>
        <label>Task instruction<input value={form.prompt} maxLength={200} placeholder="Place the block on the pad" onChange={(event) => update('prompt', event.target.value)} /></label>
        <label>Object name<input value={form.objectLabel} maxLength={60} placeholder="Red block" onChange={(event) => update('objectLabel', event.target.value)} /></label>
        <label>Shape<select value={form.shape} onChange={(event) => update('shape', event.target.value as Shape)}><option value="box">Box</option><option value="sphere">Ball</option><option value="cylinder">Cylinder</option></select></label>
        <label>Object color<input type="color" value={form.objectColor} onChange={(event) => update('objectColor', event.target.value)} /></label>
        <label>Target name<input value={form.targetLabel} maxLength={60} placeholder="Blue pad" onChange={(event) => update('targetLabel', event.target.value)} /></label>
        <label>Target color<input type="color" value={form.targetColor} onChange={(event) => update('targetColor', event.target.value)} /></label>
      </div>
      {inline ? <details className="sim-recorder-details"><summary>Dimensions, positions, and seed</summary>{sceneDimensions}</details> : sceneDimensions}
      <button type="button" className="secondary" disabled={!hasSceneDetails} onClick={() => void previewScene()}>Preview scene</button>
    </fieldset>
    {preview && <div className="sim-image-wrap"><img src={preview.image} width={preview.width} height={preview.height} alt="YAM simulator scene with the new object and target" />
      {Object.entries(preview.markers).map(([name, [x, y]]) => <span key={name} className="sim-marker" style={{ left: `${x / preview.width * 100}%`, top: `${y / preview.height * 100}%` }}>{name}</span>)}
    </div>}
    {!hasSceneDetails && <p className="hint">Enter a task instruction, object name, and target name to continue.</p>}
    {hasSceneDetails && !matchesTask && <div className="sim-task-approval">
      {inline && <p><strong>{draft.prompt}</strong><br />{draft.success_rule}</p>}
      <button type="button" className="secondary" disabled={locked} onClick={() => void setupTask()}>{inline ? 'Approve task' : 'Set up this scene task'}</button>
    </div>}
    {inline && matchesTask && <p role="status">Task approved.</p>}
    <button type="button" disabled={!matchesTask || !preview || locked} onClick={() => void record()}>Record this new task</button>
    {currentStatus?.state === 'recording' && <p role="status">Recording and validating the new scene…</p>}
    {currentStatus?.state === 'complete' && currentStatus.result && !inline && <p className="notice" role="status">Exported {currentStatus.result.frames} verified frames. Review the demo below before keeping it.</p>}
    {(error || currentStatus?.state === 'failed') && <p className="alert" role="alert">{error || currentStatus?.error}</p>}
  </section>;
}
