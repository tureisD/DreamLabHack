import { useCallback, useEffect, useState } from 'react';

type Finding = { kind: string; severity: string; message: string; evidence: string };
type Event = { kind: string; elapsed_s: number | null; detail: string | null; reason: string | null; action: string | null };
type EpisodeItem = {
  id: string; task: string; checkpoint: string; status: string;
  started_at_utc: string | null; success: boolean | null; finding_count: number;
};
type Episode = EpisodeItem & {
  simulation?: { source: string; seed: number; start_pose?: string; model_action_rows?: number } | null;
  body: string | null; robot_name: string | null; frames: number | null; fps: number | null;
  duration_s: number | null; stop_reason: string | null; error: string | null;
  stalls: number | null; clamps: number | null; videos: Record<string, string>;
  findings: Finding[]; events: Event[]; failure_stage: string | null; note: string | null;
};
type ImportResult = { imported: number; skipped: string[] };
type IntentAudit = { command_rows: number; comparable_rows: number; differing_rows: number; differing_share: number | null; median_staleness_ms: number | null; discarded_replies: number; warnings: string[] };

export default function Runs() {
  const [items, setItems] = useState<EpisodeItem[]>([]);
  const [selected, setSelected] = useState<Episode | null>(null);
  const [role, setRole] = useState('');
  const [outcome, setOutcome] = useState('unlabelled');
  const [stage, setStage] = useState('');
  const [note, setNote] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [audit, setAudit] = useState<IntentAudit | null>(null);

  const loadItems = useCallback(async () => {
    const response = await fetch('/api/episodes');
    if (!response.ok) throw new Error('Could not load imported runs.');
    setItems((await response.json()) as EpisodeItem[]);
  }, []);

  useEffect(() => {
    void loadItems().catch((caught: Error) => setError(caught.message));
  }, [loadItems]);

  async function openEpisode(id: string) {
    setError('');
    try {
      const response = await fetch(`/api/episodes/${id}`);
      if (!response.ok) throw new Error('Could not load this run.');
      const episode = (await response.json()) as Episode;
      setSelected(episode);
      setAudit(null);
      const auditResponse = await fetch(`/api/episodes/${id}/intent-audit`);
      if (auditResponse.ok) setAudit((await auditResponse.json()) as IntentAudit);
      setRole(Object.keys(episode.videos)[0] ?? '');
      setOutcome(episode.success === null ? 'unlabelled' : episode.success ? 'success' : 'failure');
      setStage(episode.failure_stage ?? '');
      setNote(episode.note ?? '');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load this run.');
    }
  }

  async function scan() {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch('/api/rollouts/import', { method: 'POST' });
      if (!response.ok) throw new Error('Could not scan the rollout directory.');
      const result = (await response.json()) as ImportResult;
      await loadItems();
      setMessage(`Indexed ${result.imported} runs.${result.skipped.length ? ` Skipped: ${result.skipped.join('; ')}` : ''}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not scan rollouts.');
    } finally {
      setBusy(false);
    }
  }

  async function saveLabel() {
    if (!selected) return;
    setBusy(true);
    setError('');
    try {
      const response = await fetch(`/api/episodes/${selected.id}/label`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          success: outcome === 'unlabelled' ? null : outcome === 'success',
          failure_stage: outcome === 'failure' && stage ? stage : null,
          note: note.trim() || null,
        }),
      });
      if (!response.ok) throw new Error('Could not save the run label.');
      setSelected((await response.json()) as Episode);
      await loadItems();
      setMessage('Run label saved.');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save the label.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page">
      <header className="header">
        <div>
          <p className="eyebrow">Evidence first</p>
          <h1>Run review</h1>
          <p className="subtitle">Import saved station or simulator rollouts, inspect failures, and label the task outcome.</p>
        </div>
        <button onClick={() => void scan()} disabled={busy}>{busy ? 'Working…' : 'Scan rollouts'}</button>
      </header>
      {error && <div className="alert" role="alert">{error}</div>}
      {message && <div className="notice" role="status">{message}</div>}
      <div className="runs-layout">
        <section className="card runs-list" aria-label="Imported runs">
          <div className="card-heading"><h2>Imported runs</h2><span className="count">{items.length}</span></div>
          {items.length === 0 && <p>No runs indexed yet. Enable station rollouts, then scan the rollout directory.</p>}
          {items.map((item) => (
            <button key={item.id} className={`run-row ${selected?.id === item.id ? 'selected' : ''}`} onClick={() => void openEpisode(item.id)}>
              <strong>{item.task}</strong>
              <span>{item.checkpoint}</span>
              <small>{item.started_at_utc ?? 'No start time'} · {item.status} · {item.success === null ? 'unlabelled' : item.success ? 'success' : 'failure'}</small>
            </button>
          ))}
        </section>

        <section className="card review" aria-label="Selected run">
          {!selected ? <p>Select a run to review its evidence.</p> : (
            <>
              <div className="card-heading"><h2>{selected.task}</h2><span className="count">{selected.status}</span></div>
              <p className="muted">{selected.checkpoint} · {selected.robot_name ?? selected.body ?? 'Robot unknown'}</p>
              {Object.keys(selected.videos).length > 0 ? (
                <>
                  <div className="role-tabs">{Object.keys(selected.videos).map((name) => <button key={name} className={role === name ? 'role-active' : ''} onClick={() => setRole(name)}>{name}</button>)}</div>
                  <video key={`${selected.id}-${role}`} controls preload="metadata" src={`/api/episodes/${selected.id}/video/${encodeURIComponent(role)}`} />
                </>
              ) : <div className="video-empty">No finished camera video in this rollout.</div>}
              <dl className="details">
                {selected.simulation && <div><dt>Simulation</dt><dd>{selected.simulation.source} � seed {selected.simulation.seed}{selected.simulation.start_pose && ` � start: ${selected.simulation.start_pose}`}{selected.simulation.model_action_rows !== undefined && ` � ${selected.simulation.model_action_rows} model action rows`}</dd></div>}
                <div><dt>Duration</dt><dd>{selected.duration_s?.toFixed(1) ?? '—'} s</dd></div>
                <div><dt>Frames</dt><dd>{selected.frames ?? '—'} at {selected.fps ?? '—'} fps</dd></div>
                <div><dt>Stop reason</dt><dd>{selected.stop_reason ?? '—'}</dd></div>
                <div><dt>Stalls / clamps</dt><dd>{selected.stalls ?? '—'} / {selected.clamps ?? '—'}</dd></div>
                {selected.error && <div><dt>Error</dt><dd>{selected.error}</dd></div>}
              </dl>
              {audit && <><h3>Policy intent versus command</h3><p>{audit.comparable_rows} of {audit.command_rows} command rows aligned to raw replies. {audit.differing_share === null ? 'No comparable rows.' : `${(audit.differing_share * 100).toFixed(1)}% differed from the policy reply.`} Median execution staleness: {audit.median_staleness_ms?.toFixed(0) ?? '—'} ms. Discarded replies: {audit.discarded_replies}.</p>{audit.warnings.map((warning) => <p className="hint" key={warning}>{warning}</p>)}</>}
              <h3>Findings</h3>
              {selected.findings.length ? selected.findings.map((finding, index) => <div className={`finding finding-${finding.severity}`} key={`${finding.kind}-${index}`}><strong>{finding.message}</strong><small>Evidence: {finding.evidence}</small></div>) : <p className="muted">No metadata or inference errors found. This does not establish task success.</p>}
              <h3>Inference events</h3>
              <div className="event-list">{selected.events.length ? selected.events.map((event, index) => <div key={index}><span>{event.elapsed_s === null ? '—' : `${event.elapsed_s.toFixed(1)}s`}</span><strong>{event.kind}</strong><span>{event.detail ?? event.reason ?? event.action ?? ''}</span></div>) : <p>No inference log available.</p>}</div>
              <h3>Operator label</h3>
              <div className="label-form">
                <label>Outcome<select value={outcome} onChange={(event) => setOutcome(event.target.value)}><option value="unlabelled">Unlabelled</option><option value="success">Success</option><option value="failure">Failure</option></select></label>
                {outcome === 'failure' && <label>Failure stage<select value={stage} onChange={(event) => setStage(event.target.value)}><option value="">Unknown</option><option value="approach">Approach</option><option value="grasp">Grasp</option><option value="transport">Transport</option><option value="release">Release</option><option value="other">Other</option></select></label>}
                <label>Note<textarea maxLength={2000} value={note} onChange={(event) => setNote(event.target.value)} placeholder="What happened?" /></label>
                <button onClick={() => void saveLabel()} disabled={busy}>Save label</button>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
