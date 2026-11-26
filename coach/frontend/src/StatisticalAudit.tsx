import { useState } from 'react';

type Interval = { lower: number; upper: number; confidence_level: number };
type Arm = {
  attempted: number; successes: number; failures: number; unknown: number; invalid: number;
  success_rate: number | null; success_interval: Interval | null;
};
type AuditReport = {
  decision: 'improved' | 'regressed' | 'inconclusive' | 'not_evaluable';
  baseline: Arm; candidate: Arm; difference: number | null;
  difference_interval: Interval | null; method: string; input_sha256: string;
  rationale: string; warnings: string[]; trial_ids: string[];
};
type SamplePlan = {
  feasible: boolean; trials_per_arm: number | null; power_at_recommendation: number | null;
  power_at_budget: number; max_trials_per_arm: number;
};
type PairAttempt = {
  trial_id: string; outcome: string; held_lift_m: number | null; first_close_after_warmup_s: number | null;
  model_action_rows: number | null; replay_max_state_error_m: number | null;
  interventions?: number; duration_s?: number | null; first_response_s?: number | null;
};
type Pair = { pair_id: string; baseline: PairAttempt | null; candidate: PairAttempt | null };
export type PairedReport = {
  evaluation_id: string;
  decision: 'descriptive' | 'improved' | 'regressed' | 'inconclusive' | 'not_evaluable';
  planned_pairs: number; submitted_pairs: number; usable_pairs: number;
  baseline_attempted: number; candidate_attempted: number;
  baseline_successes: number; candidate_successes: number; observed_difference: number | null;
  difference_interval: [number, number] | null; interval_method: string | null;
  input_sha256: string; problems: string[]; warnings: string[]; pairs: Pair[];
  interruptions?: { pair_id: string; role: 'baseline' | 'candidate'; attempt: PairAttempt }[];
  baseline_interventions?: number; candidate_interventions?: number;
  baseline_mean_duration_s?: number | null; candidate_mean_duration_s?: number | null;
  baseline_mean_first_response_s?: number | null; candidate_mean_first_response_s?: number | null;
};

function percent(value: number | null) {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`;
}

export default function StatisticalAudit({ embedded = false }: { embedded?: boolean }) {
  const [snapshot, setSnapshot] = useState('');
  const [report, setReport] = useState<AuditReport | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [planError, setPlanError] = useState('');
  const [samplePlan, setSamplePlan] = useState<SamplePlan | null>(null);
  const [baselineRate, setBaselineRate] = useState(0.375);
  const [assumedGain, setAssumedGain] = useState(0.25);
  const [margin, setMargin] = useState(0.125);
  const [budget, setBudget] = useState(80);
  const [pairedSnapshot, setPairedSnapshot] = useState('');
  const [pairedReport, setPairedReport] = useState<PairedReport | null>(null);
  const [pairedError, setPairedError] = useState('');
  const [pairedBusy, setPairedBusy] = useState(false);

  async function analyze() {
    setError(''); setReport(null);
    let value: unknown;
    try { value = JSON.parse(snapshot); }
    catch { setError('The snapshot is not valid JSON.'); return; }
    setBusy(true);
    try {
      const response = await fetch('/api/statistical-evaluations/analyze', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
      });
      const body = await response.json();
      if (!response.ok) {
        const detail = body.detail;
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
      }
      setReport(body as AuditReport);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not analyze the snapshot.');
    } finally { setBusy(false); }
  }

  function downloadReport() {
    if (!report) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'statistical-evaluation-report.json';
    link.click();
    URL.revokeObjectURL(url);
  }

  async function planTrials() {
    setPlanError(''); setSamplePlan(null); setPlanning(true);
    try {
      const response = await fetch('/api/statistical-evaluations/plan', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ baseline_rate: baselineRate, alternative_gain: assumedGain,
          minimum_improvement: margin, max_trials_per_arm: budget, target_power: 0.8 }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail));
      setSamplePlan(body as SamplePlan);
    } catch (caught) {
      setPlanError(caught instanceof Error ? caught.message : 'Could not calculate sample size.');
    } finally { setPlanning(false); }
  }

  async function analyzePaired(value?: unknown) {
    setPairedError(''); setPairedReport(null);
    let parsed = value;
    if (parsed === undefined) {
      try { parsed = JSON.parse(pairedSnapshot); }
      catch { setPairedError('The paired snapshot is not valid JSON.'); return; }
    }
    setPairedBusy(true);
    try {
      const response = await fetch('/api/paired-evaluations/analyze', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(parsed),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail));
      setPairedReport(body as PairedReport);
    } catch (caught) {
      setPairedError(caught instanceof Error ? caught.message : 'Could not analyze paired evidence.');
    } finally { setPairedBusy(false); }
  }

  async function loadAppleDemo(url = '/api/paired-evaluations/demo') {
    setPairedError(''); setPairedBusy(true);
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`Could not load the demo (${response.status}).`);
      const value: unknown = await response.json();
      setPairedSnapshot(JSON.stringify(value, null, 2));
      setPairedBusy(false);
      await analyzePaired(value);
    } catch (caught) {
      setPairedError(caught instanceof Error ? caught.message : 'Could not load the demo.');
      setPairedBusy(false);
    }
  }

  function downloadPaired() {
    if (!pairedReport) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(pairedReport, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'paired-evaluation-report.json';
    link.click();
    URL.revokeObjectURL(url);
  }

  const Container = embedded ? 'div' : 'main';
  return <Container className="page">
    <header className="header"><div>
      {!embedded && <><p className="eyebrow">Checkpoint evidence</p><h1>Statistical evaluation</h1></>}
      <p className="subtitle">Compare fine-tuned and base models with the method appropriate to how the trials were collected.</p>
    </div></header>
    <section className="card">
      <h2>Matched fine-tune comparison</h2>
      <p>Analyze predeclared scene pairs. Physical pairs with reviewed outcomes can receive a conservative interval. Simulator pairs show measured task outcomes without a real-robot or deployment claim.</p>
      <div className="chat-workspace-actions">
        <button type="button" className="secondary" disabled={pairedBusy} onClick={() => void loadAppleDemo()}>
          Analyze varied 500-step apple demo
        </button>
        <button type="button" className="secondary" disabled={pairedBusy} onClick={() => void loadAppleDemo('/api/paired-evaluations/demo/second-account')}>
          Analyze independent 500-step apple demo
        </button>
      </div>
      <label className="audit-file">Or load a paired JSON snapshot
        <input type="file" accept=".json,application/json" onChange={async (event) => {
          const file = event.target.files?.[0];
          if (file) { setPairedSnapshot(await file.text()); setPairedReport(null); setPairedError(''); }
        }} />
      </label>
      <label className="audit-file">Paired evidence JSON
        <textarea value={pairedSnapshot} onChange={(event) => { setPairedSnapshot(event.target.value); setPairedReport(null); }}
          placeholder='{"plan": { ... }, "pairs": [ ... ]}' spellCheck={false} />
      </label>
      <button type="button" disabled={pairedBusy || !pairedSnapshot.trim()} onClick={() => void analyzePaired()}>
        {pairedBusy ? 'Analyzing…' : 'Analyze matched scenes'}
      </button>
    </section>
    {pairedError && <div className="alert" role="alert">{pairedError}</div>}
    {pairedReport && <section className="card evaluation-report" aria-live="polite">
      <h2>Matched result: {pairedReport.decision.replace('_', ' ')}</h2>
      <div className="evaluation-metrics">
        <div><strong>{pairedReport.baseline_successes}/{pairedReport.baseline_attempted}</strong><span>Base successes</span></div>
        <div><strong>{pairedReport.candidate_successes}/{pairedReport.candidate_attempted}</strong><span>Fine-tune successes</span></div>
        <div><strong>{percent(pairedReport.observed_difference)}</strong><span>Observed paired gain</span></div>
        <div><strong>{pairedReport.difference_interval ? `${percent(pairedReport.difference_interval[0])} to ${percent(pairedReport.difference_interval[1])}` : '—'}</strong><span>Physical-trial interval</span></div>
      </div>
      <div className="evaluation-secondary-metrics">
        <div><strong>Human interventions</strong><span>Base {pairedReport.baseline_interventions ?? '—'} · candidate {pairedReport.candidate_interventions ?? '—'}</span></div>
        <div><strong>Mean run duration</strong><span>Base {pairedReport.baseline_mean_duration_s?.toFixed(1) ?? '—'}s · candidate {pairedReport.candidate_mean_duration_s?.toFixed(1) ?? '—'}s</span></div>
        <div><strong>Mean first response</strong><span>Base {pairedReport.baseline_mean_first_response_s?.toFixed(1) ?? '—'}s · candidate {pairedReport.candidate_mean_first_response_s?.toFixed(1) ?? '—'}s</span></div>
      </div>
      <p>{pairedReport.decision === 'descriptive'
        ? 'These simulator outcomes show task performance on the submitted scenes. They do not establish physical-robot success or statistical improvement.'
        : pairedReport.decision === 'not_evaluable' ? 'The evidence is incomplete or inconsistent; review the problems below.'
          : `Method: ${pairedReport.interval_method}. This result still needs independent verification of scene resets, labels, and safety.`}</p>
      {pairedReport.problems.length > 0 && <><h3>Problems</h3><ul>{pairedReport.problems.map((item) => <li key={item}>{item}</li>)}</ul></>}
      <div className="audit-table-wrap"><table className="audit-table">
        <thead><tr><th>Scene</th><th>Base held lift</th><th>Fine-tune held lift</th><th>Base close</th><th>Fine-tune close</th><th>Base</th><th>Fine-tune</th><th>Interventions (base / fine-tune)</th></tr></thead>
        <tbody>{pairedReport.pairs.map((pair) => <tr key={pair.pair_id}>
          <td>{pair.pair_id}</td><td>{pair.baseline?.held_lift_m == null ? '—' : `${(pair.baseline.held_lift_m * 100).toFixed(1)} cm`}</td>
          <td>{pair.candidate?.held_lift_m == null ? '—' : `${(pair.candidate.held_lift_m * 100).toFixed(1)} cm`}</td>
          <td>{pair.baseline?.first_close_after_warmup_s == null ? '—' : `${pair.baseline.first_close_after_warmup_s.toFixed(1)} s`}</td>
          <td>{pair.candidate?.first_close_after_warmup_s == null ? '—' : `${pair.candidate.first_close_after_warmup_s.toFixed(1)} s`}</td>
          <td>{pair.baseline?.outcome ?? 'missing'}</td><td>{pair.candidate?.outcome ?? 'missing'}</td>
          <td>{pair.baseline?.interventions ?? '—'} / {pair.candidate?.interventions ?? '—'}</td>
        </tr>)}</tbody>
      </table></div>
      <p className="hint">All {pairedReport.submitted_pairs} submitted pairs are retained. Snapshot SHA-256: <code>{pairedReport.input_sha256}</code>.</p>
      <h3>Limits</h3><ul>{pairedReport.warnings.map((item) => <li key={item}>{item}</li>)}</ul>
      <button type="button" className="secondary" onClick={downloadPaired}>Download paired report JSON</button>
    </section>}
    <section className="card">
      <h2>Plan independent real-world trials</h2>
      <p>Estimate the equal-arm sample size for a fixed-horizon comparison with 80% target power. Enter assumed true rates before collecting evaluation outcomes. This calculation does not estimate those rates or account for paired scenes, repeated sessions, missing labels, or safety outcomes.</p>
      <div className="audit-plan-grid">
        <label>Assumed base success rate<input type="number" min="0" max="1" step="0.01" value={baselineRate} onChange={(event) => setBaselineRate(Number(event.target.value))} /></label>
        <label>Assumed candidate gain<input type="number" min="0" max="1" step="0.01" value={assumedGain} onChange={(event) => setAssumedGain(Number(event.target.value))} /></label>
        <label>Minimum useful gain<input type="number" min="0" max="0.99" step="0.01" value={margin} onChange={(event) => setMargin(Number(event.target.value))} /></label>
        <label>Maximum trials per model<input type="number" min="1" max="512" step="1" value={budget} onChange={(event) => setBudget(Number(event.target.value))} /></label>
      </div>
      <button type="button" disabled={planning} onClick={() => void planTrials()}>{planning ? 'Calculating…' : 'Calculate sample size'}</button>
      {planError && <div className="alert" role="alert">{planError}</div>}
      {samplePlan && <p className="notice">{samplePlan.feasible
        ? `At least ${samplePlan.trials_per_arm} trials per model (${(samplePlan.trials_per_arm ?? 0) * 2} total) under these assumptions; calculated power ${percent(samplePlan.power_at_recommendation)}.`
        : `No size through ${samplePlan.max_trials_per_arm} trials per model reaches 80% power under these assumptions. Power at that budget: ${percent(samplePlan.power_at_budget)}.`}</p>}
    </section>
    <section className="card">
      <h2>Submit an evaluation snapshot</h2>
      <p>Use this for prospective independent attempts in one predeclared real-world scenario. Include the plan, every attempt, source IDs, and reviewed outcomes. The engine refuses paired or simulated trials; use the regular Evaluation screen for matched scene pairs.</p>
      <label className="audit-file">Load JSON file
        <input type="file" accept=".json,application/json" onChange={async (event) => {
          const file = event.target.files?.[0];
          if (file) { setSnapshot(await file.text()); setReport(null); setError(''); }
        }} />
      </label>
      <label className="audit-file">Or paste the complete snapshot
        <textarea value={snapshot} onChange={(event) => { setSnapshot(event.target.value); setReport(null); }}
          placeholder='{"plan": { ... }, "trials": [ ... ]}' spellCheck={false} />
      </label>
      <button type="button" disabled={busy || !snapshot.trim()} onClick={() => void analyze()}>
        {busy ? 'Analyzing…' : 'Analyze snapshot'}
      </button>
    </section>
    {error && <div className="alert" role="alert">{error}</div>}
    {report && <section className="card evaluation-report" aria-live="polite">
      <div className="card-heading"><h2>Result: {report.decision.replace('_', ' ')}</h2></div>
      <button type="button" className="secondary" onClick={downloadReport}>Download report JSON</button>
      <div className="evaluation-metrics">
        <div><strong>{report.baseline.successes}/{report.baseline.attempted}</strong><span>Base successes</span></div>
        <div><strong>{report.candidate.successes}/{report.candidate.attempted}</strong><span>Candidate successes</span></div>
        <div><strong>{percent(report.difference)}</strong><span>Candidate − base</span></div>
        <div><strong>{report.difference_interval ? `${percent(report.difference_interval.lower)} to ${percent(report.difference_interval.upper)}` : '—'}</strong><span>Difference interval</span></div>
      </div>
      <p>{report.rationale}</p>
      <p className="hint">Method: {report.method}. Snapshot SHA-256: <code>{report.input_sha256}</code>. All {report.trial_ids.length} submitted trial IDs are retained in the report.</p>
      <h3>Limits</h3><ul>{report.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
      <p className="footnote">This audit does not promote a checkpoint, prove random assignment, or authorize robot deployment. An inconclusive result is not evidence that the models are equal.</p>
    </section>}
  </Container>;
}
