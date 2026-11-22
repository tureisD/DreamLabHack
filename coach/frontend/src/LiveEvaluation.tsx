import { useEffect, useState } from 'react';
import type { Evaluation, Report } from './Evaluation';
import type { PairedReport } from './StatisticalAudit';

type LiveResult = {
  task_name: string;
  evaluation: Evaluation;
  report: Report;
};

const refreshSeconds = 5;
const verdicts: Record<Report['decision'], string> = {
  improved: 'Improved',
  worse: 'Regressed',
  inconclusive: 'Inconclusive',
  not_evaluable: 'Audit needed',
};

async function readJson<T>(url: string, signal: AbortSignal, snapshot?: unknown): Promise<T> {
  const response = await fetch(url, {
    signal,
    cache: 'no-store',
    ...(snapshot === undefined ? {} : {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(snapshot),
    }),
  });
  if (!response.ok) throw new Error(`Evaluation request failed (${response.status})`);
  return response.json() as Promise<T>;
}

function percentagePoints(value: number) {
  return `${value > 0 ? '+' : ''}${(value * 100).toFixed(1)} pp`;
}

async function readExample(signal: AbortSignal) {
  const snapshot = await readJson<unknown>('/api/paired-evaluations/demo/second-account', signal);
  return readJson<PairedReport>('/api/paired-evaluations/analyze', signal, snapshot);
}

function SuccessCounts({ baseline, candidate, baselineTotal, candidateTotal }: {
  baseline: number;
  candidate: number;
  baselineTotal: number;
  candidateTotal: number;
}) {
  return <dl className="live-eval-scores">
    <div><dt>Base successes</dt><dd>{baselineTotal ? `${baseline}/${baselineTotal}` : '—'}</dd></div>
    <div><dt>Fine-tune successes</dt><dd>{candidateTotal ? `${candidate}/${candidateTotal}` : '—'}</dd></div>
  </dl>;
}

export default function LiveEvaluation({ onOpen, onOpenAudit }: {
  onOpen: (taskId?: string, evaluationId?: string) => void;
  onOpenAudit: () => void;
}) {
  const [result, setResult] = useState<LiveResult | null | undefined>(undefined);
  const [example, setExample] = useState<PairedReport | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    let timer: number;
    let requestedExample = false;

    async function poll() {
      try {
        const next = await readJson<LiveResult | null>('/api/evaluations/latest', signal);
        if (signal.aborted) return;
        setResult(next);
        setFailed(false);
        if (next === null && !requestedExample) {
          requestedExample = true;
          void readExample(signal).then((report) => {
            if (!signal.aborted) setExample(report);
          }).catch(() => { requestedExample = false; });
        }
      } catch {
        if (!signal.aborted) setFailed(true);
      } finally {
        if (!signal.aborted) timer = window.setTimeout(poll, refreshSeconds * 1000);
      }
    }

    void poll();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, []);

  return <aside className="card live-evaluation" aria-labelledby="live-evaluation-title">
    <header className="live-eval-header">
      <h2 id="live-evaluation-title">Evaluation statistics</h2>
      <p className="live-eval-refresh" data-error={failed}>
        {failed ? (result ? 'Refresh failed · showing last result' : 'Refresh failed · retrying') : `Refreshes every ${refreshSeconds}s`}
      </p>
    </header>
    {result === undefined && !failed && <p>Loading evaluations…</p>}
    {result === null && <p>No saved evaluations yet.</p>}
    {result && <div className="live-eval-body">
      <h3>{result.task_name}</h3>
      <p className="live-eval-verdict">{result.report.decision === 'not_evaluable' && result.report.usable_pairs < result.report.target_pairs
        ? 'Evaluation incomplete'
        : verdicts[result.report.decision]}</p>
      <SuccessCounts
        baseline={result.report.baseline_successes}
        candidate={result.report.candidate_successes}
        baselineTotal={result.report.baseline_reviewed}
        candidateTotal={result.report.candidate_reviewed}
      />
      <dl className="live-eval-details">
        <div><dt>Reviewed trials</dt><dd>{result.report.baseline_reviewed + result.report.candidate_reviewed}/{result.report.target_pairs * 2}</dd></div>
        <div><dt>Usable scene pairs</dt><dd>{result.report.usable_pairs}/{result.report.target_pairs}</dd></div>
        {result.report.paired_difference !== null && <div>
          <dt>Fine-tune gain</dt><dd>{percentagePoints(result.report.paired_difference)}</dd>
        </div>}
        {result.report.ci_low !== null && result.report.ci_high !== null && <div>
          <dt>Confidence interval</dt>
          <dd>{percentagePoints(result.report.ci_low)} to {percentagePoints(result.report.ci_high)}</dd>
        </div>}
      </dl>
      <button type="button" className="secondary" onClick={() => onOpen(result.evaluation.task_id, result.evaluation.id)}>
        Open evaluation
      </button>
    </div>}
    {result === null && example && <div className="live-eval-body">
      <h3>Apple pickup · simulator example</h3>
      <SuccessCounts
        baseline={example.baseline_successes}
        candidate={example.candidate_successes}
        baselineTotal={example.baseline_attempted}
        candidateTotal={example.candidate_attempted}
      />
      {example.observed_difference !== null && <p>Observed gain {percentagePoints(example.observed_difference)}</p>}
      <button type="button" className="secondary" onClick={onOpenAudit}>Open statistical audit</button>
    </div>}
    {result === null && <button type="button" className="live-eval-link" onClick={() => onOpen()}>Plan an evaluation</button>}
  </aside>;
}
