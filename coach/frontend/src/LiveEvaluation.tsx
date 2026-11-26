import { useEffect, useState } from 'react';
import type { Evaluation, Report } from './Evaluation';
import type { PairedReport } from './StatisticalAudit';
import type { SimulatorMode } from './YamChatWorkflow';
import './MeasuredEvidenceTeaser.css';

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

type EvaluationSnapshot = {
  taskId: string;
  simulation: SimulatorResult | null;
  result: LiveResult | null | undefined;
  failed: boolean;
};

const refreshSeconds = 5;
const verdicts: Record<Report['decision'], string> = {
  improved: 'Improved',
  worse: 'Regressed',
  inconclusive: 'Inconclusive',
  not_evaluable: 'Audit needed',
};

async function readJson<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal, cache: 'no-store' });
  if (!response.ok) throw new Error(`Evaluation request failed (${response.status})`);
  return response.json() as Promise<T>;
}

function percentagePoints(value: number) {
  return `${value > 0 ? '+' : ''}${(value * 100).toFixed(1)} pp`;
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

export function useLiveEvaluation(taskId: string, comparisonId?: string) {
  const [snapshot, setSnapshot] = useState<EvaluationSnapshot | null>(null);

  useEffect(() => {
    setSnapshot(null);
    if (!taskId) return;

    const controller = new AbortController();
    const { signal } = controller;
    let timer: number;

    async function poll() {
      try {
        const saved = await readJson<SimulatorResult | null>(`/api/simulator/comparisons/${encodeURIComponent(taskId)}`, signal);
        const sim = saved && (!comparisonId || saved.report.evaluation_id === comparisonId) ? saved : null;
        const next = sim ? null : comparisonId ? undefined : await readJson<LiveResult | null>(
          `/api/evaluations/latest?task_id=${encodeURIComponent(taskId)}`, signal,
        );
        if (signal.aborted) return;
        setSnapshot({ taskId, simulation: sim, result: next, failed: false });
      } catch {
        if (!signal.aborted) setSnapshot((previous) => previous?.taskId === taskId
          ? { ...previous, failed: true }
          : { taskId, simulation: null, result: undefined, failed: true });
      } finally {
        if (!signal.aborted) timer = window.setTimeout(poll, refreshSeconds * 1000);
      }
    }

    void poll();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [taskId, comparisonId]);

  const scoped = snapshot?.taskId === taskId ? snapshot : null;
  return {
    simulation: scoped?.simulation?.task_id === taskId
      && (!comparisonId || scoped.simulation.report.evaluation_id === comparisonId) ? scoped.simulation : null,
    result: comparisonId ? undefined : scoped?.result,
    failed: scoped?.failed ?? false,
  };
}

export default function LiveEvaluation({ taskId, simulatorMode, allowPhysicalPlanning, onOpen, onEvidence, evidence }: {
  taskId: string;
  simulatorMode?: SimulatorMode;
  allowPhysicalPlanning: boolean;
  onOpen: (taskId?: string, evaluationId?: string) => void;
  onEvidence: () => void;
  evidence: ReturnType<typeof useLiveEvaluation>;
}) {
  const { result, simulation: sim, failed } = evidence;
  const current = result?.evaluation.task_id === taskId ? result : null;

  return <aside className="card live-evaluation" aria-labelledby="live-evaluation-title">
    <header className="live-eval-header">
      <h2 id="live-evaluation-title">Evaluation statistics</h2>
      {taskId && <p className="live-eval-refresh" data-error={failed}>
        {failed ? (current || sim ? 'Refresh failed · showing last result' : 'Refresh failed · retrying') : `Refreshes every ${refreshSeconds}s`}
      </p>}
    </header>
    {!taskId && <p>Choose a task to see its evaluation.</p>}
    {taskId && result === undefined && !sim && !failed && <p>Loading evaluations…</p>}
    {taskId && result === null && !sim && <p>No evaluation for this task yet.</p>}
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
      <p>{sim.report.decision === 'descriptive' ? 'Result for these simulator scenes.' : 'A scene pair is usable after both models finish with valid scores.'}</p>
      <details className="live-eval-checkpoints"><summary>Checkpoints</summary><p>Base · {sim.baseline}<br />Fine-tune · {sim.candidate}</p></details>
    </div>}
    {current && <div className="live-eval-body">
      <h3>{current.task_name}</h3>
      <p className="live-eval-verdict">{current.report.decision === 'not_evaluable' && current.report.usable_pairs < current.report.target_pairs
        ? 'Evaluation incomplete'
        : verdicts[current.report.decision]}</p>
      <SuccessCounts
        baseline={current.report.baseline_successes}
        candidate={current.report.candidate_successes}
        baselineTotal={current.report.baseline_reviewed}
        candidateTotal={current.report.candidate_reviewed}
      />
      <dl className="live-eval-details">
        <div><dt>Reviewed trials</dt><dd>{current.report.baseline_reviewed + current.report.candidate_reviewed}/{current.report.target_pairs * 2}</dd></div>
        <div><dt>Usable scene pairs</dt><dd>{current.report.usable_pairs}/{current.report.target_pairs}</dd></div>
        {current.report.paired_difference !== null && <div>
          <dt>Fine-tune gain</dt><dd>{percentagePoints(current.report.paired_difference)}</dd>
        </div>}
        {current.report.ci_low !== null && current.report.ci_high !== null && <div>
          <dt>Confidence interval</dt>
          <dd>{percentagePoints(current.report.ci_low)} to {percentagePoints(current.report.ci_high)}</dd>
        </div>}
      </dl>
      <button type="button" className="secondary" onClick={() => onOpen(current.evaluation.task_id, current.evaluation.id)}>
        Open evaluation
      </button>
    </div>}
    {taskId && result === null && !sim && (simulatorMode === 'apple'
      ? <p>Run a matched comparison from chat when a checkpoint is ready.</p>
      : <>{simulatorMode && <p>Automatic simulator comparisons are available for Apple pickup.</p>}
        {allowPhysicalPlanning && <button type="button" className="live-eval-link" onClick={() => onOpen(taskId)}>Plan a physical evaluation</button>}</>)}
    {!sim && !current && <div className="measured-evidence-teaser">
      <span>Measured YAM simulator case</span>
      <strong>14/19 → 19/19</strong>
      <p>The same fine-tune passed more scenes when the evaluation ran long enough. This is an example, not a result for your task.</p>
      <button type="button" className="secondary" onClick={onEvidence}>Explore the saved evidence</button>
    </div>}
  </aside>;
}
