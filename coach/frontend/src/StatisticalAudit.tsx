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

function percent(value: number | null) {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`;
}

export default function StatisticalAudit() {
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

  return <main className="page">
    <header className="header"><div>
      <p className="eyebrow">Independent trial audit</p>
      <h1>Statistical evaluation</h1>
      <p className="subtitle">Analyze a frozen, human-verified comparison without starting a robot or FaaS job.</p>
    </div></header>
    <section className="card">
      <h2>Plan independent trials</h2>
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
  </main>;
}
