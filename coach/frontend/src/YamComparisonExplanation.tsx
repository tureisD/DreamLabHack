import type { PairedReport } from './StatisticalAudit';
import type { YamGoal, YamJob } from './YamChatWorkflow';

export function yamSuccessRule(goal?: YamGoal) {
  return goal === 'bowl'
    ? 'Lift the apple at least 8 cm, then release it so it rests inside the bowl without gripper contact for the final second.'
    : 'Lift the apple at least 8 cm above its starting height and hold it there for two continuous seconds.';
}

export function YamComparisonPlan({ pairs, goal }: { pairs: number; goal?: YamGoal }) {
  return <div className="yam-comparison-explanation">
    <p>I’ll have base Dream-1 and your fine-tune try the same {pairs} {goal === 'bowl' ? 'apple-into-bowl' : 'apple-pickup'} scenes held out from training. I’ll reset each scene to the same starting state for both models, for {pairs * 2} trials total.</p>
    <p>{yamSuccessRule(goal)} These trials use Dream inference credits.</p>
  </div>;
}

export function YamComparisonProgress({ job, report }: { job: YamJob; report: PairedReport | null }) {
  const attempts = report?.pairs ?? [];
  const baseFinished = attempts.filter(({ baseline }) => baseline?.outcome === 'success' || baseline?.outcome === 'failure').length;
  const fineTuneFinished = attempts.filter(({ candidate }) => candidate?.outcome === 'success' || candidate?.outcome === 'failure').length;
  const finished = baseFinished + fineTuneFinished;
  const pairsComplete = Math.max(job.completed, report?.usable_pairs ?? 0);
  const running = job.state === 'running' || job.state === 'stopping';

  let summary;
  if (job.state === 'completed') {
    if (!report || report.baseline_attempted < job.total || report.candidate_attempted < job.total) {
      summary = <p>Both models finished. I’m loading their scores.</p>;
    } else if (report.decision === 'descriptive' && report.planned_pairs === job.total && report.usable_pairs === job.total
      && baseFinished === job.total && fineTuneFinished === job.total) {
      summary = <>
        <p>Base Dream-1 succeeded on {report.baseline_successes} of {job.total} scenes. Your fine-tune succeeded on {report.candidate_successes} of {job.total}.</p>
        <p>These scores describe the {job.goal === 'bowl' ? 'apple placements' : 'apple pickups'} on these {job.total} simulator scenes.</p>
      </>;
    } else {
      summary = <p>I have {report.usable_pairs} of {job.total} usable pairs. The evidence is incomplete, so I can’t give a final comparison.</p>;
    }
  } else if (running && finished < pairsComplete * 2) {
    summary = <p>I’m loading the scores from the latest finished scene.</p>;
  } else if (report && finished > 0) {
    summary = <p>
      {finished} of {job.total * 2} trials finished.
      {baseFinished > 0 && ` Base Dream-1 succeeded in ${report.baseline_successes} of ${baseFinished} finished ${baseFinished === 1 ? 'trial' : 'trials'}.`}
      {fineTuneFinished > 0 && ` Your fine-tune succeeded in ${report.candidate_successes} of ${fineTuneFinished} finished ${fineTuneFinished === 1 ? 'trial' : 'trials'}.`}
    </p>;
  }

  return <div className="yam-comparison-explanation">
    <p>{job.message}</p>
    {running && <>
      <div className="yam-job-progress">
        <progress value={pairsComplete} max={job.total} aria-label="Completed scene pairs" />
        <small>{pairsComplete}/{job.total} scene pairs complete</small>
      </div>
      <p>A pair is complete once both models finish the same scene.</p>
    </>}
    {summary}
    {!!report?.interruptions?.length && <p>Earlier interrupted attempts are saved in the comparison explanation.</p>}
  </div>;
}
