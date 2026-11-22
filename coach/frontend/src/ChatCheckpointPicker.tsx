import { useEffect, useState } from 'react';

type CheckpointOption = {
  checkpoint: string;
  dataset: string;
  steps: number | null;
};

export default function ChatCheckpointPicker({ onClose, onCompare }: {
  onClose: () => void;
  onCompare: (checkpoint: string) => Promise<boolean>;
}) {
  const [options, setOptions] = useState<CheckpointOption[] | null>(null);
  const [checkpoint, setCheckpoint] = useState('');
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [starting, setStarting] = useState(false);
  const selection = options?.find((option) => option.checkpoint === checkpoint);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch('/api/simulator/existing-checkpoints', {
          cache: 'no-store',
          signal: controller.signal,
        });
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(typeof body?.detail === 'string' ? body.detail : 'Could not load your completed fine-tunes.');
        }
        const loaded = await response.json() as CheckpointOption[];
        if (!controller.signal.aborted) setOptions(loaded);
      } catch (caught) {
        if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Could not load your completed fine-tunes.');
      }
    }
    void load();
    return () => controller.abort();
  }, [attempt]);

  async function runComparison() {
    if (!selection || starting) return;
    setStarting(true);
    setError('');
    try {
      if (!await onCompare(selection.checkpoint)) {
        setError('The comparison did not start. Check the simulator status and try again.');
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not start the comparison.');
    } finally {
      setStarting(false);
    }
  }

  return <section className="chat-inline-workspace chat-tool-panel" aria-labelledby="chat-checkpoint-title">
    <header className="chat-workspace-header">
      <h2 id="chat-checkpoint-title">Choose an existing fine-tune</h2>
      <button type="button" className="secondary" onClick={onClose} disabled={starting}>Back to chat</button>
    </header>
    {error && <p className="alert" role="alert">{error}</p>}
    {options === null && (error
      ? <button type="button" className="secondary" onClick={() => { setError(''); setAttempt(attempt + 1); }}>Retry</button>
      : <p role="status">Looking up completed fine-tunes in your Dream account…</p>)}
    {options?.length === 0 && <p>No completed fine-tunes in the connected Dream account are ready for this YAM apple pickup comparison.</p>}
    {!!options?.length && <>
      <label className="chat-workspace-field chat-tool-body">Training dataset and checkpoint
        <select value={checkpoint} disabled={starting} onChange={(event) => { setCheckpoint(event.target.value); setError(''); }}>
          <option value="">Choose a completed fine-tune</option>
          {options.map((option) => <option key={option.checkpoint} value={option.checkpoint}>
            {option.dataset}{option.steps !== null ? ` · ${option.steps.toLocaleString()} steps` : ''} · {option.checkpoint}
          </option>)}
        </select>
      </label>
      {selection && <div className="chat-training-next"><code>{selection.checkpoint}</code></div>}
      <p>Compare this model with Dream-1 on the same four apple pickup scenes. The comparison uses inference credits.</p>
      <button type="button" disabled={!selection || starting} onClick={() => void runComparison()}>
        {starting ? 'Starting comparison…' : 'Run simulator comparison'}
      </button>
    </>}
  </section>;
}
