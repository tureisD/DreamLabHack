import { useEffect, useRef, useState } from 'react';

type Screen = 'preflight' | 'tasks' | 'demos' | 'training' | 'evaluation' | 'statistical';
type Message = { role: 'user' | 'assistant'; content: string };
type TaskDraft = { name: string; prompt: string; success_rule: string };
type Reply = { message: string; input_kind: 'text' | 'dream_key'; suggested_screen: Screen | null; task_draft: TaskDraft | null };
type Account = { configured: boolean; source: string; dashboard_url: string };
type Task = { id: string; name: string; baseline_checkpoint: string };
type Status = { configured: boolean; source: string };

async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(path, { method, cache: 'no-store', headers: body === undefined ? undefined : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(detail.detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function savedMessages(): Message[] {
  try {
    const result: unknown = JSON.parse(sessionStorage.getItem('coach-chat') || '[]');
    return Array.isArray(result) ? result.filter((item): item is Message => item && (item.role === 'user' || item.role === 'assistant') && typeof item.content === 'string').slice(-24) : [];
  } catch { return []; }
}

export default function CoachChat({ open }: { open: (screen: Screen) => void }) {
  const [messages, setMessages] = useState<Message[]>(savedMessages);
  const [reply, setReply] = useState<Reply | null>(null);
  const [ai, setAi] = useState<Status | null>(null);
  const [account, setAccount] = useState<Account | null>(null);
  const [text, setText] = useState('');
  const [secret, setSecret] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const bottom = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  useEffect(() => { sessionStorage.setItem('coach-chat', JSON.stringify(messages.slice(-24))); bottom.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);
  useEffect(() => {
    void Promise.all([api<Status>('/api/assistant/status'), api<Account>('/api/account/status')])
      .then(([aiStatus, dreamStatus]) => { setAi(aiStatus); setAccount(dreamStatus); })
      .catch((caught: Error) => setError(caught.message));
  }, []);
  useEffect(() => {
    if (ai?.configured && !started.current && messages.length === 0) {
      started.current = true;
      void turn([]);
    }
  // Initial turn only. Subsequent turns are sent by submit or Continue.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ai?.configured]);

  async function workflowState() {
    const dream = await api<Account>('/api/account/status');
    setAccount(dream);
    const [preflight, tasks] = await Promise.all([
      api<{ dream: { state: string; message: string }; station: { state: string; message: string }; models: { id: string; servable: boolean }[] }>('/api/preflight'),
      api<Task[]>('/api/tasks'),
    ]);
    const current = tasks[0];
    const taskData = current ? await Promise.all([
      api<{ phase: string; next_action: string; evidence: string[] }>(`/api/tasks/${current.id}/guidance`),
      api<{ decision: string }[]>(`/api/tasks/${current.id}/demos`),
      api<{ status: string }[]>(`/api/tasks/${current.id}/datasets`),
      api<{ status: string; checkpoint: string | null }[]>(`/api/tasks/${current.id}/finetunes`),
      api<unknown[]>(`/api/tasks/${current.id}/evaluations`),
    ]) : null;
    return {
      dream_connected: dream.configured, dream_preflight: preflight.dream,
      robot_station: preflight.station, available_models: preflight.models.filter((model) => model.servable).map((model) => model.id).slice(0, 8),
      tasks: tasks.map((task) => ({ id: task.id, name: task.name, baseline_checkpoint: task.baseline_checkpoint })),
      current_task: current ? { id: current.id, name: current.name, guidance: taskData?.[0],
        kept_demos: taskData?.[1].filter((demo) => demo.decision === 'keep').length,
        dataset_count: taskData?.[2].length, training_jobs: taskData?.[3].map((job) => ({ status: job.status, checkpoint: job.checkpoint })),
        evaluations: taskData?.[4].length } : null,
    };
  }

  async function turn(history: Message[]) {
    setBusy(true); setError(''); setNotice('');
    try {
      const state = await workflowState();
      const result = await api<Reply>('/api/assistant/chat', 'POST', { messages: history.slice(-24), state });
      setReply(result);
      setMessages([...history, { role: 'assistant', content: result.message }]);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'The coach could not reply.'); }
    finally { setBusy(false); }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const input = text.trim();
    if (!input || busy) return;
    if (/\b(?:dl_live_|sk-)[A-Za-z0-9_-]{12,}/.test(input)) { setError('Enter API keys in the masked key field, not the chat.'); return; }
    setText('');
    const history: Message[] = [...messages, { role: 'user', content: input }];
    setMessages(history);
    await turn(history);
  }

  async function connectAi(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const status = await api<Status>('/api/assistant/connect', 'POST', { api_key: secret.trim() });
      setSecret(''); setAi(status);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not connect AI.'); }
    finally { setBusy(false); }
  }

  async function connectDream(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const status = await api<Account>('/api/account/connect', 'POST', { api_key: secret.trim() });
      setSecret(''); setAccount(status);
      const history: Message[] = [...messages, { role: 'user', content: 'I connected my Dream Labs account successfully.' }];
      setMessages(history);
      await turn(history);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not connect Dream Labs.'); setBusy(false); }
  }

  async function saveTask(draft: TaskDraft) {
    setBusy(true); setError('');
    try {
      const preflight = await api<{ models: { id: string; servable: boolean }[] }>('/api/preflight');
      const checkpoint = preflight.models.find((model) => model.servable)?.id || 'dreamlabs/dream-1';
      await api('/api/tasks', 'POST', { ...draft, baseline_checkpoint: checkpoint });
      const history: Message[] = [...messages, { role: 'user', content: `I confirmed and saved the task “${draft.name}”.` }];
      setMessages(history); setReply(null);
      await turn(history);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not save task.'); setBusy(false); }
  }

  return <main className="page chat-page">
    <header className="header"><div><p className="eyebrow">Your fine-tuning guide</p><h1>Teach it a task</h1><p className="subtitle">Tell the coach what you want your robot to do. It will ask what it needs, one step at a time.</p></div></header>
    {!ai?.configured ? <section className="card chat-setup"><h2>Connect the AI coach</h2><p>This conversation uses an AI model. Enter an OpenAI API key to start; this is separate from your Dream Labs key. The AI key stays in this local server process until you restart it. Dream credentials and videos are never sent in the chat.</p><form onSubmit={(event) => void connectAi(event)} className="chat-secret"><input aria-label="OpenAI API key" type="password" autoComplete="off" minLength={20} value={secret} onChange={(event) => setSecret(event.target.value)} placeholder="OpenAI API key" /><button disabled={busy || !secret.trim()}>Connect AI</button></form><p className="hint">You can also set OPENAI_API_KEY on the server before starting it. This needs API access; a ChatGPT subscription alone does not supply an API key.</p></section> : <section className="card chat-shell" aria-label="Fine-tuning coach conversation">
      <div className="chat-thread" aria-live="polite">
        {messages.map((item, index) => <div key={index} className={`chat-bubble chat-${item.role}`}><span>{item.role === 'assistant' ? 'Coach' : 'You'}</span><p>{item.content}</p></div>)}
        {busy && <div className="chat-bubble chat-assistant"><span>Coach</span><p>Thinking through your next step…</p></div>}
        <div ref={bottom} />
      </div>
      {account && !account.configured && <div className="chat-action"><p><a href={account.dashboard_url} target="_blank" rel="noreferrer">Open Dream Labs to create your API key</a>. Paste it in this private field when you have it. The key is not added to the chat.</p><form onSubmit={(event) => void connectDream(event)} className="chat-secret"><input aria-label="Dream API key" type="password" autoComplete="off" value={secret} onChange={(event) => setSecret(event.target.value)} placeholder="Dream API key" /><button disabled={busy || !secret.trim()}>Connect Dream</button></form></div>}
      {reply?.task_draft && <div className="chat-action"><strong>Ready to save this task?</strong><p>{reply.task_draft.name} · {reply.task_draft.prompt}<br />Success: {reply.task_draft.success_rule}</p><button disabled={busy} onClick={() => void saveTask(reply.task_draft!)}>Confirm and save task</button></div>}
      {reply?.suggested_screen && <div className="chat-action"><button className="secondary" onClick={() => open(reply.suggested_screen!)}>Open {reply.suggested_screen}</button><span>Return here afterward and tell the coach what happened.</span></div>}
      <form onSubmit={(event) => void submit(event)} className="chat-composer"><textarea aria-label="Message to coach" value={text} maxLength={2000} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit(event); } }} placeholder="Tell me about your robot or ask what to do next…" /><button disabled={busy || !text.trim()}>Send</button></form>
      <div className="chat-footer"><button className="secondary" disabled={busy} onClick={() => { const history: Message[] = [...messages, { role: 'user', content: 'Please check my current progress and ask me the next question.' }]; setMessages(history); void turn(history); }}>Check my progress</button><button className="secondary" disabled={busy} onClick={() => { setMessages([]); setReply(null); started.current = false; void turn([]); }}>Start over</button><span>The agent advises; you approve robot runs and paid training in their screens.</span></div>
    </section>}
    {error && <div className="alert" role="alert">{error}</div>}{notice && <div className="notice" role="status">{notice}</div>}
  </main>;
}
