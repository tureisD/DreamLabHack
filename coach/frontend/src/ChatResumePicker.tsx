import { useEffect, useState } from 'react';
import type { YamGoal } from './YamChatWorkflow';

type SavedRun = {
  id: string;
  task_id: string;
  task: string;
  candidate: string;
  completed: number;
  total: number;
  created_at: string;
  goal: YamGoal;
};

export default function ChatResumePicker({ onClose, onResume }: {
  onClose: () => void;
  onResume: (taskId: string, runId: string) => Promise<boolean>;
}) {
  const [options, setOptions] = useState<SavedRun[] | null>(null);
  const [selected, setSelected] = useState('');
  const [starting, setStarting] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const run = options?.find(({ id }) => id === selected);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch('/api/simulator/resumable-comparisons', {
          cache: 'no-store', signal: controller.signal,
        });
        if (!response.ok) throw new Error('Comparisons are unavailable.');
        const saved = await response.json() as SavedRun[];
        if (!controller.signal.aborted) setOptions(saved);
      } catch {
        if (!controller.signal.aborted) setLoadFailed(true);
      }
    }
    void load();
    return () => controller.abort();
  }, [retry]);

  async function resume() {
    if (!run || starting) return;
    setStarting(true);
    try { await onResume(run.task_id, run.id); }
    finally { setStarting(false); }
  }

  return <section className="chat-inline-workspace chat-tool-panel" aria-labelledby="chat-resume-title">
    <header className="chat-workspace-header">
      <h2 id="chat-resume-title">Resume a saved comparison</h2>
      <button type="button" className="secondary" onClick={onClose} disabled={starting}>Back to chat</button>
    </header>
    {options === null && (loadFailed ? <>
      <p className="alert" role="alert">Could not load saved comparisons.</p>
      <button type="button" className="secondary" onClick={() => { setLoadFailed(false); setRetry(retry + 1); }}>Retry</button>
    </> : <p role="status">Looking for interrupted comparisons…</p>)}
    {options?.length === 0 && <p>No interrupted comparisons are available in this workspace.</p>}
    {!!options?.length && <>
      <label className="chat-workspace-field chat-tool-body">Saved comparison
        <select value={selected} disabled={starting} onChange={(event) => setSelected(event.target.value)}>
          <option value="">Choose a comparison</option>
          {options.map((option) => <option key={option.id} value={option.id}>
            {option.goal === 'bowl' ? 'Apple into bowl' : 'Apple pickup'} · {new Date(option.created_at).toLocaleString()} · {option.completed}/{option.total} pairs
          </option>)}
        </select>
      </label>
      {run && <div className="chat-training-next"><p>{run.task}</p><code>{run.candidate}</code></div>}
      <p>Resume keeps the original held-out scenes and valid results. Any remaining Dream model trials use inference credits.</p>
      <button type="button" disabled={!run || starting} onClick={() => void resume()}>
        {starting ? 'Resuming…' : 'Resume selected comparison'}
      </button>
    </>}
  </section>;
}
