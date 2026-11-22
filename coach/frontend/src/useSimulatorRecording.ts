import { useEffect, useRef, useState } from 'react';

type Recorder = 'fruit' | 'scene';
type Status = {
  state: 'idle' | 'recording' | 'complete' | 'failed';
  task_id?: string;
  result?: { frames: number; demo_id: string } | null;
  error?: string | null;
};

export type SimulatorTaskDraft = { name: string; prompt: string; success_rule: string };

export async function simulatorRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { cache: 'no-store', ...init });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : `Request failed (${response.status})`);
  return value as T;
}

export function useSimulatorRecording(
  recorder: Recorder,
  taskId: string,
  inline: boolean,
  onComplete: (demoId: string) => void,
) {
  const [status, setStatus] = useState<Status | null>(null);
  const starting = useRef(false);
  const revision = useRef(0);
  const standalonePending = useRef(new Map<string, string>());
  const pendingKey = `dreamcoach-simulator-recording:${recorder}:${taskId}`;
  const currentStatus = taskId && status?.task_id === taskId ? status : null;

  useEffect(() => {
    const controller = new AbortController();
    let timer: number;
    async function poll() {
      const generation = revision.current;
      try {
        const next = await simulatorRequest<Status>('/api/sim-correction/status', { signal: controller.signal });
        if (!controller.signal.aborted && !starting.current && generation === revision.current) setStatus(next);
      } catch { /* A later poll can recover from a transient failure. */ }
      finally {
        if (!controller.signal.aborted) timer = window.setTimeout(poll, 2500);
      }
    }
    void poll();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, []);

  useEffect(() => {
    if (!taskId || starting.current || !status) return;
    const pending = inline ? sessionStorage.getItem(pendingKey) : standalonePending.current.get(pendingKey);
    if (pending == null || currentStatus?.state === 'recording') return;
    const demoId = currentStatus?.state === 'complete' ? currentStatus.result?.demo_id : undefined;
    if (demoId === pending) return;
    if (inline) sessionStorage.removeItem(pendingKey);
    else standalonePending.current.delete(pendingKey);
    if (demoId) onComplete(demoId);
  }, [currentStatus, inline, onComplete, pendingKey, status, taskId]);

  async function start(body: object) {
    if (!taskId || starting.current) return;
    const endpoint = recorder === 'scene' ? 'scene-task' : 'sim-correction';
    const previousDemoId = currentStatus?.result?.demo_id ?? '';
    ++revision.current;
    starting.current = true;
    try {
      const next = await simulatorRequest<Status>(`/api/tasks/${encodeURIComponent(taskId)}/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (next.task_id !== taskId) throw new Error('The server did not confirm a recording for this task.');
      if (inline) sessionStorage.setItem(pendingKey, previousDemoId);
      else standalonePending.current.set(pendingKey, previousDemoId);
      setStatus(next);
    } finally {
      starting.current = false;
      ++revision.current;
    }
  }

  return { currentStatus, recording: status?.state === 'recording', start };
}
