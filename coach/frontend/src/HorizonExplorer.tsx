import { useState } from 'react';
import study from '../../experiments/yam_sim_faas/horizon_confirmation_report.json';
import './HorizonExplorer.css';

const notableSeeds = [923, 930, 933, 934, 936];
const requests = Array.from({ length: 12 }, (_, index) => index + 1);

function centimeters(meters: number | null) {
  return meters === null ? '—' : `${(meters * 100).toFixed(1)} cm`;
}

export default function HorizonExplorer() {
  const [seed, setSeed] = useState(933);
  const trial = study.trials.find((item) => item.seed === seed) ?? study.trials[0];
  const first = trial.earliest_success_request;

  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(study, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'horizon-confirmation-report.json';
    link.click();
    URL.revokeObjectURL(url);
  }

  return <section className="card horizon-explorer" aria-labelledby="horizon-explorer-title">
    <p className="eyebrow">Observed simulator evidence · fresh confirmation</p>
    <h2 id="horizon-explorer-title">What happens when evaluation stops at request 9?</h2>
    <p>We scored the first nine requests and all twelve requests from each saved trajectory of the <strong>same unchanged fine-tune</strong>. Success means lifting the apple 8 cm and holding it for two seconds.</p>
    <div className="horizon-explorer-stats" aria-label="Confirmation results">
      <div><strong>{study.prefix_9_successes}/{study.valid_trials}</strong><span>passed by request 9</span></div>
      <div><strong>{study.full_12_successes}/{study.valid_trials}</strong><span>passed by request 12</span></div>
      <div><strong>{study.extra_requests_needed}</strong><span>needed request 10 or 11</span></div>
    </div>
    <div className="horizon-explorer-picker">
      <div><strong>Inspect a scene</strong><p>These five scenes changed from fail to pass after the original cutoff.</p></div>
      <div className="horizon-explorer-presets" role="group" aria-label="Scenes needing extra requests">
        {notableSeeds.map((value) => <button key={value} type="button" className={value === seed ? 'selected' : ''}
          aria-pressed={value === seed} onClick={() => setSeed(value)}>{value}</button>)}
      </div>
      <label>All twenty attempts
        <select value={seed} onChange={(event) => setSeed(Number(event.target.value))}>
          {study.trials.map((item) => <option key={item.seed} value={item.seed}>
            Scene {item.seed}{item.valid ? item.prefix_success ? ' · passed by 9' : ' · needed more time' : ' · invalid'}
          </option>)}
        </select>
      </label>
    </div>
    <div className="horizon-explorer-scene" aria-live="polite">
      <div className="horizon-explorer-scene-title">
        <h3>Scene {trial.seed}</h3>
        <span>{!trial.valid ? 'Invalid run' : first && first > 9 ? `First passed at request ${first}` : 'Passed by request 9'}</span>
      </div>
      <ol className="horizon-explorer-timeline" aria-label="Action request timeline">
        {requests.map((request) => <li key={request} className={`${request === 9 ? 'cutoff ' : ''}${first && request >= first ? 'passed' : 'waiting'}`}>
          <span>{request}</span>
        </li>)}
      </ol>
      <div className="horizon-explorer-labels"><span>Original evaluation stops at 9 ↑</span><span>Extended evaluation ends at 12 ↑</span></div>
      {trial.valid ? <div className="horizon-explorer-lift">
        <div><span>Held lift at request 9</span><strong>{centimeters(trial.prefix_held_lift_m)}</strong></div>
        <div><span>Held lift by request 12</span><strong>{centimeters(trial.full_held_lift_m)}</strong></div>
      </div> : <p className="horizon-explorer-invalid">Dream restarted the episode; only ten action chunks executed. This attempt stays invalid and was not rerun.</p>}
    </div>
    <p className="horizon-explorer-decision"><strong>Coach decision:</strong> allow enough execution time before collecting more demos or paying for another fine-tune. The study measures evaluation correctness in one simulator task; it does not measure saved operator time, demos, or FaaS dollars.</p>
    <details><summary>Study record and limits</summary>
      <p>{study.valid_trials} of {study.planned_trials} attempts produced complete, replay-checked trajectories. One service-interrupted attempt is retained as invalid. The nine-request score uses the same action prefix as the twelve-request score, so no extra model call was made to calculate it.</p>
      <p>Frozen-plan SHA-256: <code>{study.plan_sha256}</code>. Model: <code>{study.model}</code>.</p>
      <button type="button" className="secondary" onClick={download}>Download all scene results</button>
    </details>
  </section>;
}
