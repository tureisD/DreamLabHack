import { useEffect, useId, useRef, useState } from 'react';
import type { PairedReport } from './StatisticalAudit';
import type { YamComparisonDiagnostics, YamJob, YamTrialDiagnosis } from './YamChatWorkflow';

type Trial = NonNullable<PairedReport['pairs'][number]['baseline']>;
type DiagnosticState = {
  jobId: string;
  attemptsKey: string;
  retry: number;
  trials: Record<string, YamTrialDiagnosis>;
  error: boolean;
};

function outcomeLabel(outcome: string | undefined) {
  switch (outcome) {
    case 'success': return 'Pass';
    case 'failure': return 'Miss';
    case 'invalid': return 'Invalid trial';
    case 'unknown': return 'Unscored';
    default: return 'Missing';
  }
}

function nextStep(report: PairedReport, complete: boolean) {
  if (!complete) return 'Check for missing or invalid trials in the scene results. A fresh comparison can collect a complete set.';
  if (report.candidate_successes > report.baseline_successes) {
    return 'Keep this checkpoint and test it on more fresh scenes with varied apple positions before relying on it.';
  }
  if (report.candidate_successes === report.planned_pairs) {
    return 'Both models picked up the apple in every scene. Try more challenging starting positions to see where their performance differs.';
  }
  if (report.candidate_successes === report.baseline_successes) {
    return 'Review the misses below. Record corrections on new training scenes that reproduce the missed approach or grasp, then test on fresh held-out scenes.';
  }
  return 'Review where the fine-tune missed, especially scenes the base passed. Record corrections on similar training scenes before testing another checkpoint.';
}

export function YamTrialDiagnosisDetails({ diagnosis }: { diagnosis: YamTrialDiagnosis }) {
  return <>
    <p><strong>{diagnosis.title}</strong></p>
    <p>{diagnosis.summary}</p>
    {diagnosis.evidence.length > 0 && <details>
      <summary>Recorded evidence</summary>
      <ul className="yam-diagnostic-evidence">
        {diagnosis.evidence.map((item, index) => <li key={index}>{item}</li>)}
      </ul>
    </details>}
    {diagnosis.next_step && <p><strong>What to try</strong> {diagnosis.next_step}</p>}
  </>;
}

function TrialDiagnosis({ name, attempt, diagnosis, pending }: {
  name: string;
  attempt: Trial | null;
  diagnosis?: YamTrialDiagnosis;
  pending: boolean;
}) {
  return <section className="yam-diagnostic-attempt">
    <h5>{name} <span>· {outcomeLabel(attempt?.outcome)}</span></h5>
    {diagnosis ? <YamTrialDiagnosisDetails diagnosis={diagnosis} />
      : !attempt ? <p>No recorded attempt for this model in this scene.</p>
      : pending ? <p>Waiting for the trace analysis.</p>
      : <p>The saved evidence is insufficient to explain this outcome.</p>}
  </section>;
}

export default function YamComparisonReview({ job, report, onConfirmFresh }: {
  job: YamJob;
  report: PairedReport | null;
  onConfirmFresh?: () => void;
}) {
  const detailsId = useId();
  const detailsTop = useRef<HTMLDivElement>(null);
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<DiagnosticState | null>(null);
  const [retry, setRetry] = useState(0);
  const expanded = expandedJobId === job.id;
  const evidence = report?.evaluation_id === job.id ? report : null;
  const running = job.state === 'running' || job.state === 'stopping';
  const complete = job.state === 'completed' && evidence?.decision === 'descriptive'
    && evidence.planned_pairs === job.total && evidence.usable_pairs === job.total;
  const awaitingFinalReport = job.state === 'completed' && evidence
    && (evidence.baseline_attempted < job.total || evidence.candidate_attempted < job.total);
  const improved = evidence?.pairs.filter((pair) => pair.baseline?.outcome === 'failure' && pair.candidate?.outcome === 'success').length ?? 0;
  const regressed = evidence?.pairs.filter((pair) => pair.baseline?.outcome === 'success' && pair.candidate?.outcome === 'failure').length ?? 0;
  const attemptsKey = evidence?.pairs.flatMap((pair) => [pair.baseline, pair.candidate]
    .filter((attempt) => attempt !== null).map((attempt) => `${attempt.trial_id}:${attempt.outcome}`)).join('|') ?? '';
  const saved = diagnostics?.jobId === job.id ? diagnostics : null;
  const pending = Boolean(attemptsKey) && (saved?.attemptsKey !== attemptsKey || saved.retry !== retry);

  useEffect(() => {
    if (expanded) detailsTop.current?.scrollIntoView({ block: 'start' });
  }, [expanded]);

  useEffect(() => {
    if (!expanded || !attemptsKey) return;
    const controller = new AbortController();
    const { signal } = controller;
    const context = { jobId: job.id, attemptsKey, retry };

    async function loadDiagnostics() {
      try {
        const response = await fetch(`/api/simulator/comparisons/${encodeURIComponent(job.task_id)}/diagnostics`, { signal, cache: 'no-store' });
        if (!response.ok) throw new Error('Trace analysis was unavailable.');
        const result = await response.json() as YamComparisonDiagnostics | null;
        if (result && result.evaluation_id !== job.id) throw new Error('Trace analysis belongs to a different run.');
        if (!signal.aborted) setDiagnostics({ ...context, trials: result?.trials ?? {}, error: false });
      } catch {
        if (!signal.aborted) setDiagnostics((previous) => ({
          ...context, trials: previous?.jobId === job.id ? previous.trials : {}, error: true,
        }));
      }
    }

    void loadDiagnostics();
    return () => controller.abort();
  }, [expanded, attemptsKey, job.id, job.task_id, retry]);

  return <section className="yam-comparison-review" aria-label="Comparison review">
    {evidence && !running && !awaitingFinalReport && <p><strong>Next step</strong> {nextStep(evidence, complete)}</p>}
    <button type="button" className="yam-secondary" aria-expanded={expanded} aria-controls={detailsId}
      onClick={() => setExpandedJobId(expanded ? null : job.id)}>
      {expanded ? 'Hide comparison explanation' : 'Explain comparison results'}
    </button>
    <div id={detailsId} hidden={!expanded} ref={detailsTop}>
      {expanded && <div className="yam-comparison-explanation">
        {evidence ? <>
          {complete ? <>
            <p>Both models started from the same apple position in each scene.
              {improved > 0 && ` The fine-tune passed ${improved} ${improved === 1 ? 'scene' : 'scenes'} the base missed.`}
              {regressed > 0 && ` It missed ${regressed} ${regressed === 1 ? 'scene' : 'scenes'} the base passed.`}
            </p>
            <p>These results cover {job.total} scenes in simulation. More varied trials are needed to estimate how reliably the model picks up apples.</p>
          </> : <p>{evidence.usable_pairs} of {job.total} scene pairs have valid results for both models. You can still review the saved outcomes below.</p>}
          {evidence.pairs.length > 0 && <table className="audit-table">
            <caption>Saved scene outcomes</caption>
            <thead><tr><th scope="col">Scene</th><th scope="col">Base</th><th scope="col">Fine-tune</th></tr></thead>
            <tbody>{evidence.pairs.map((pair, index) => <tr key={pair.pair_id}>
              <th scope="row">{index + 1}</th><td>{outcomeLabel(pair.baseline?.outcome)}</td>
              <td>{outcomeLabel(pair.candidate?.outcome)}</td>
            </tr>)}</tbody>
          </table>}
          {evidence.pairs.length > 0 && <section className="yam-diagnostic-list" aria-label="Run diagnoses">
            <h4>What happened in each scene</h4>
            {pending && <p role="status">Analyzing recorded trial evidence…</p>}
            {!pending && saved?.error && <div className="yam-next">
              <p>The trace analysis is unavailable.</p>
              <button type="button" className="yam-secondary" onClick={() => setRetry((current) => current + 1)}>
                Retry analysis
              </button>
            </div>}
            {evidence.pairs.map((pair, index) => <article className="yam-diagnostic-scene" key={pair.pair_id}>
              <h4>Scene {index + 1}</h4>
              <div className="yam-diagnostic-models">
                <TrialDiagnosis name="Base Dream-1" attempt={pair.baseline} pending={pending}
                  diagnosis={pair.baseline ? saved?.trials[pair.baseline.trial_id] : undefined} />
                <TrialDiagnosis name="Fine-tune" attempt={pair.candidate} pending={pending}
                  diagnosis={pair.candidate ? saved?.trials[pair.candidate.trial_id] : undefined} />
              </div>
            </article>)}
          </section>}
        </> : <p>The saved results for this run are unavailable right now. I’ll show an explanation when they load.</p>}
        {evidence && !running && !awaitingFinalReport && onConfirmFresh && <div className="yam-next">
          <button type="button" className="yam-secondary" onClick={onConfirmFresh}>Plan a fresh comparison</button>
          <small>Starting a fresh run uses Dream inference credits.</small>
        </div>}
      </div>}
    </div>
  </section>;
}
