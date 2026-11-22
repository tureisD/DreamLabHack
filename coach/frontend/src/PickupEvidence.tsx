import { Clock3, Focus, ScanLine } from 'lucide-react';

const outcomes = {
  no_actions: ['No model attempt', 'Check the recording status before retrying.'],
  unavailable: ['Not assessable', 'Review the video manually. Missing measurements are not a failed pickup.'],
  no_contact: ['No contact in this clip', 'Review the approach and how much time the arm had to reach the apple.'],
  contact: ['Contact without a verified lift', 'Check finger placement at the first contact.'],
  unverified_lift: ['Lift without a verified grasp', 'Check whether another object pushed or supported the apple.'],
  brief_hold: ['Lift observed, hold too short', 'Check whether contact stopped or the recording ended first.'],
  held: ['Pickup held', 'Inspect the hold before recording your own judgement.'],
} as const;

export type PickupResult = {
  rule: 'yam-apple-v1'; source: 'model' | 'scripted' | 'observation dry run';
  observation: keyof typeof outcomes; detail: string; analyzed_frames: number;
  first_contact_s: number | null; peak_lift_m: number | null;
  longest_hold_s: number | null; evidence_s: number | null;
};

type Props = {result: PickupResult; jump: ((seconds: number) => void) | null; videoState: 'ready'|'loading'|'failed'|'unavailable'};
export default function PickupEvidence({result:r, jump, videoState}: Props) {
  const [title, next] = outcomes[r.observation];
  const headline = r.source === 'observation dry run' ? 'Camera check: no model actions' : `${r.source === 'scripted' ? 'Scripted reference' : 'Model simulation'}: ${title.toLowerCase()}`;
  const points = [['First contact', r.first_contact_s], ['Verified frame', r.evidence_s]] as const;
  return <section className="measurements" aria-label="Simulator pickup evidence">
    <div className="reading-head"><ScanLine size={19} aria-hidden="true"/><h3>{headline}</h3></div>
    <p>{r.detail}</p>
    {r.peak_lift_m !== null && <dl className="measures"><div><dt>Peak lift</dt><dd>{(r.peak_lift_m*100).toFixed(1)} <small>cm</small></dd></div><div><dt>Longest hold</dt><dd>{r.longest_hold_s?.toFixed(2)} <small>s</small></dd></div><div><dt>Frames assessed</dt><dd>{r.analyzed_frames}</dd></div></dl>}
    <div className="markers">{points.map(([name,secs],i)=>secs!==null && !(i===1 && secs===r.first_contact_s) && <button type="button" key={name} disabled={!jump} onClick={()=>jump?.(secs)}>{i===0?<Clock3 size={15}/>:<Focus size={15}/>} {i===1 && r.observation!=='held'?'Evidence frame':name} <b>{secs.toFixed(2)} s</b></button>)}</div>
    {points.some(([,t])=>t!==null)&&!jump&&<p className="quiet" role="status">{videoState==='loading'?'Loading video metadata…':'Video unavailable; the timestamps above are recording time.'}</p>}
    <p className="review-next"><strong>Next</strong> {next}</p><small className="rule-id">Rule: {r.rule} · Simulator measurements, not an operator label</small>
  </section>;
}
