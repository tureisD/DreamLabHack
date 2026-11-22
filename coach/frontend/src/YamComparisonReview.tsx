import { useEffect, useId, useRef, useState } from 'react';
import type { PairedReport } from './StatisticalAudit';
import type { YamJob } from './YamChatWorkflow';

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
    return 'Review the misses below. Record corrective demos for those starting positions, then test the next checkpoint on fresh scenes.';
  }
  return 'Review where the fine-tune missed, especially scenes the base passed. Record corrective demos for those positions before testing another checkpoint.';
}

export default function YamComparisonReview({ job, report, onConfirmFresh }: {
  job: YamJob;
  report: PairedReport | null;
  onConfirmFresh?: () => void;
}) {
  const detailsId = useId();
  const detailsTop = useRef<HTMLDivElement>(null);
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const expanded = expandedJobId === job.id;
  const evidence = report?.evaluation_id === job.id ? report : null;
  const complete = job.state === 'completed' && evidence?.decision === 'descriptive'
    && evidence.planned_pairs === job.total && evidence.usable_pairs === job.total;
  const improved = evidence?.pairs.filter((pair) => pair.baseline?.outcome === 'failure' && pair.candidate?.outcome === 'success').length ?? 0;
  const regressed = evidence?.pairs.filter((pair) => pair.baseline?.outcome === 'success' && pair.candidate?.outcome === 'failure').length ?? 0;

  useEffect(() => {
    if (expanded) detailsTop.current?.scrollIntoView({ block: 'start' });
  }, [expanded]);

  return <section className="yam-comparison-review" aria-label="Comparison review">
    {evidence && <p><strong>Next step</strong> {nextStep(evidence, complete)}</p>}
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
        </> : <p>The saved results for this run are unavailable right now. I’ll show an explanation when they load.</p>}
        {evidence && onConfirmFresh && <div className="yam-next">
          <button type="button" className="yam-secondary" onClick={onConfirmFresh}>Plan a fresh comparison</button>
          <small>Starting a fresh run uses Dream inference credits.</small>
        </div>}
      </div>}
    </div>
  </section>;
}
