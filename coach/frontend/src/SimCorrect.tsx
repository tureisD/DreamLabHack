import { useState } from 'react';
import { simulatorRequest, useSimulatorRecording, type SimulatorTaskDraft } from './useSimulatorRecording';

type Preview = {
  image: string; width: number; height: number;
  markers: Record<string, [number, number]>;
  supported: Record<string, string[]>;
};
const newSeed = () => Math.floor(Math.random() * 2 ** 32);

export default function SimCorrect({ taskId, taskPrompt, taskSuccessRule, onComplete, onSetupTask, inline = false }: {
  taskId: string; taskPrompt: string; taskSuccessRule?: string;
  onComplete: (demoId: string) => void;
  onSetupTask: (draft: SimulatorTaskDraft) => Promise<void>;
  inline?: boolean;
}) {
  const [kind, setKind] = useState<'lift' | 'bowl'>(() => taskPrompt === 'put the apple in the bowl' ? 'bowl' : 'lift');
  const [fruit, setFruit] = useState<'apple' | 'banana'>(() => taskPrompt === 'pick up the banana' ? 'banana' : 'apple');
  const [seed, setSeed] = useState(newSeed);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [objectPixel, setObjectPixel] = useState<[number, number] | null>(null);
  const [targetPixel, setTargetPixel] = useState<[number, number] | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { currentStatus, recording, start } = useSimulatorRecording('fruit', taskId, inline, onComplete);
  const locked = loading || recording;
  const draft: SimulatorTaskDraft = {
    name: kind === 'bowl' ? 'Apple placement · click to correct' : `${fruit} lift · click to correct`,
    prompt: kind === 'lift' ? `pick up the ${fruit}` : 'put the apple in the bowl',
    success_rule: kind === 'bowl'
      ? 'Lift the apple, release it into the bowl, and leave it resting inside.'
      : `Lift the ${fruit} at least 8 cm, then release it back onto the table.`,
  };
  const ready = Boolean(taskId) && taskPrompt === draft.prompt && (!inline || taskSuccessRule === draft.success_rule);

  async function loadScene(nextSeed = seed, nextFruit = fruit) {
    setLoading(true); setError(''); setObjectPixel(null); setTargetPixel(null); setPreview(null);
    try {
      setPreview(await simulatorRequest<Preview>(`/api/sim-correction/scene?fruit=${nextFruit}&seed=${nextSeed}`));
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not render scene.'); }
    finally { setLoading(false); }
  }

  function choosePixel(event: React.MouseEvent<HTMLImageElement>) {
    if (!preview || locked) return;
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
      await start({ kind, fruit, seed, object_pixel: objectPixel,
        target_pixel: kind === 'bowl' ? targetPixel : null });
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Recording failed to start.'); }
    finally { setLoading(false); }
  }

  async function setupTask() {
    setLoading(true); setError('');
    try { await onSetupTask(draft); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not set up the local task.'); }
    finally { setLoading(false); }
  }

  return <section className={inline ? 'sim-correct' : 'card sim-correct'}>
    <h2>Click to correct in YAM simulation</h2>
    <p>Load a scene and click the fruit. For placement, click inside the bowl too.</p>
    <fieldset className="sim-recorder-fields training-controls" aria-label="Fruit scene configuration" disabled={locked}>
      <label>Goal<select value={kind} onChange={(event) => { const next = event.target.value as 'lift' | 'bowl'; setKind(next); if (next === 'bowl') setFruit('apple'); setPreview(null); setObjectPixel(null); setTargetPixel(null); }}><option value="lift">Lift fruit</option><option value="bowl">Put fruit in bowl</option></select></label>
      <label>Object<select value={fruit} onChange={(event) => { const next = event.target.value as 'apple' | 'banana'; setFruit(next); setPreview(null); setObjectPixel(null); setTargetPixel(null); }}><option value="apple">Apple</option>{kind === 'lift' && <option value="banana">Banana</option>}</select></label>
      <label>Scene seed<input type="number" min="0" max="4294967295" value={seed} onChange={(event) => { setSeed(Number(event.target.value)); setPreview(null); }} /></label>
      <button type="button" className="secondary" onClick={() => { const next = newSeed(); setSeed(next); void loadScene(next); }}>New scene</button>
      <button type="button" className="secondary" onClick={() => void loadScene()}>Load scene</button>
    </fieldset>
    {preview && <div className="sim-image-wrap"><img src={preview.image} width={preview.width} height={preview.height} alt="YAM overhead simulator scene; click a fruit and optional bowl target" onClick={choosePixel} />
      {Object.entries(preview.markers).map(([name, [x, y]]) => <span key={name} className="sim-marker" style={{ left: `${x / preview.width * 100}%`, top: `${y / preview.height * 100}%` }} title={name}>{name}</span>)}
      {objectPixel && <span className="sim-click" style={{ left: `${objectPixel[0] / preview.width * 100}%`, top: `${objectPixel[1] / preview.height * 100}%` }}>1</span>}
      {targetPixel && <span className="sim-click" style={{ left: `${targetPixel[0] / preview.width * 100}%`, top: `${targetPixel[1] / preview.height * 100}%` }}>2</span>}
    </div>}
    {preview && <p className="hint">{!objectPixel ? 'Click the selected fruit.' : kind === 'bowl' && !targetPixel ? 'Now click inside the bowl.' : 'Check the marked selection before recording.'}</p>}
    {preview?.markers[fruit] && !objectPixel && <button type="button" className="secondary" disabled={locked}
      onClick={() => setObjectPixel(preview.markers[fruit])}>Select the marked {fruit}</button>}
    {preview?.markers.bowl && kind === 'bowl' && objectPixel && !targetPixel && <button type="button"
      className="secondary" disabled={locked} onClick={() => setTargetPixel(preview.markers.bowl)}>Select the bowl center</button>}
    {!ready && <div className="sim-task-approval">
      {inline ? <p><strong>{draft.prompt}</strong><br />{draft.success_rule}</p>
        : <p className="hint">Set up the local task for <strong>{draft.prompt}</strong> before recording.</p>}
      <button type="button" className="secondary" disabled={locked} onClick={() => void setupTask()}>{inline ? 'Approve task' : 'Set up this fruit task'}</button>
    </div>}
    {inline && ready && <p role="status">Task approved.</p>}
    <button type="button" disabled={!ready || !preview || !objectPixel || (kind === 'bowl' && !targetPixel) || locked} onClick={() => void record()}>Record and verify demo</button>
    {currentStatus?.state === 'recording' && <p role="status">Recording three camera videos and validating the result…</p>}
    {currentStatus?.state === 'complete' && currentStatus.result && !inline && <p className="notice" role="status">Physical goal passed. Exported {currentStatus.result.frames} frames. Review this demo below before keeping it.</p>}
    {(error || currentStatus?.state === 'failed') && <p className="alert" role="alert">{error || currentStatus?.error}</p>}
  </section>;
}
