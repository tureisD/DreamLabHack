import { useEffect, useState } from 'react';
import type { Evaluation, Report } from './Evaluation';
import type { PairedReport } from './StatisticalAudit';

type LiveResult = {
  task_name: string;
  evaluation: Evaluation;
  report: Report;
};

type SimulatorResult = {
  task_id: string;
  baseline: string;
  candidate: string;
  report: PairedReport;
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

export default function LiveEvaluation({ taskId, simulatorActive, onOpen, onOpenAudit }: {
  taskId: string;
  simulatorActive: boolean;
  onOpen: (taskId?: string, evaluationId?: string) => void;
  onOpenAudit: () => void;
}) {
  const [result, setResult] = useState<LiveResult | null | undefined>(undefined);
  const [simulation, setSimulation] = useState<SimulatorResult | null>(null);
  const [example, setExample] = useState<PairedReport | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    let timer: number;
    let requestedExample = false;

    async function poll() {
      try {
        const sim = taskId
          ? await readJson<SimulatorResult | null>(`/api/simulator/comparisons/${taskId}`, signal)
          : null;
        const next = sim ? null : await readJson<LiveResult | null>(
          taskId ? `/api/evaluations/latest?task_id=${encodeURIComponent(taskId)}` : '/api/evaluations/latest', signal,
        );
        if (signal.aborted) return;
        setSimulation(sim);
        setResult(next);
        setFailed(false);
        if (!taskId && next === null && !requestedExample) {
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

    setResult(undefined);
    setSimulation(null);
    setFailed(false);
    void poll();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [taskId]);

  const sim = simulation?.task_id === taskId ? simulation : null;

  return <aside className="card live-evaluation" aria-labelledby="live-evaluation-title">
    <header className="live-eval-header">
      <h2 id="live-evaluation-title">Evaluation statistics</h2>
      <p className="live-eval-refresh" data-error={failed}>
        {failed ? (result || sim ? 'Refresh failed · showing last result' : 'Refresh failed · retrying') : `Refreshes every ${refreshSeconds}s`}
      </p>
    </header>
    {result === undefined && !failed && <p>Loading evaluations…</p>}
    {result === null && !sim && <p>{taskId ? 'No evaluation for this task yet.' : 'No saved evaluations yet.'}</p>}
    {sim && <div className="live-eval-body">
      <h3>Apple pickup · live simulator trials</h3>
      <SuccessCounts
        baseline={sim.report.baseline_successes}
        candidate={sim.report.candidate_successes}
        baselineTotal={sim.report.baseline_attempted}
        candidateTotal={sim.report.candidate_attempted}
      />
      <dl className="live-eval-details">
        <div><dt>Usable scene pairs</dt><dd>{sim.report.usable_pairs}/{sim.report.planned_pairs}</dd></div>
        {sim.report.observed_difference !== null && <div>
          <dt>Observed gain</dt><dd>{percentagePoints(sim.report.observed_difference)}</dd>
        </div>}
      </dl>
      <p>{sim.report.decision === 'descriptive' ? 'Descriptive result from matched simulator scenes.' : 'Comparison incomplete. Counts include recorded attempts.'}</p>
      <details className="live-eval-checkpoints"><summary>Checkpoints</summary><p>Base · {sim.baseline}<br />Fine-tune · {sim.candidate}</p></details>
    </div>}
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
    {!taskId && result === null && example && <div className="live-eval-body">
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
    {result === null && !sim && (simulatorActive
      ? <p>Run a matched comparison from chat when a checkpoint is ready.</p>
      : <button type="button" className="live-eval-link" onClick={() => onOpen(taskId || undefined)}>Plan a physical evaluation</button>)}
  </aside>;
}
