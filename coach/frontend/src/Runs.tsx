import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDownToLine, Camera, Check, ChevronRight, CircleAlert, Film, ListFilter, Save, Search, VideoOff } from 'lucide-react';
import SimBaseline from './SimBaseline';
import PickupEvidence, { type PickupResult } from './PickupEvidence';
import { screenHref } from './workspaceRoute';

type Sim = {source?: string | null; seed?: number | null; start_pose?: string; model_action_rows?: number; requests_attempted?: number};
type Item = {id: string; task: string; checkpoint: string; status: string; started_at_utc: string | null; success: boolean | null; finding_count: number; simulation?: Sim | null};
type Episode = Item & {review_revision: number; pickup_evidence?: PickupResult | null; duration_s: number | null; frames: number | null; fps: number | null; stop_reason: string | null; error: string | null; stalls: number | null; clamps: number | null; videos: Record<string,string>; note: string | null; failure_stage: string | null; findings: {kind: string; severity: string; message: string; evidence:string}[]; events: {kind:string; elapsed_s:number|null; detail:string|null; reason:string|null; action:string|null}[]};
type Audit = {comparable_rows:number;command_rows:number;differing_share:number|null;median_staleness_ms:number|null;discarded_replies:number;warnings:string[]};
function source(s:Sim|null|undefined) {
  if (!s) return 'Station recording';
  return ({scripted:'Scripted reference',model:'Model simulation','observation dry run':'Camera check'} as Record<string,string>)[s.source || ''] || 'Simulator recording';
}
function time(raw:string|null) { if (!raw) return 'Time unknown'; const d=new Date(raw); return Number.isFinite(d.getTime()) ? d.toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : 'Time unknown'; }
function human(v:boolean|null) { return v === null ? 'Unlabelled' : v ? 'Success' : 'Failure'; }
function camera(k:string) {return ({overhead:'Overhead',wrist_l:'Left wrist',wrist_r:'Right wrist'} as Record<string,string>)[k] || k;}
async function request<T>(path:string, init?:RequestInit):Promise<T> { const res=await fetch(path,init); if(!res.ok) throw new Error(`Request failed (${res.status}).`); return res.json() as Promise<T>; }

export default function Runs({requested,taskPrompt}:{requested:string|null; taskPrompt:string}) {
  const [items,setItems]=useState<Item[]>([]), [phase,setPhase]=useState<'loading'|'ready'|'error'>('loading');
  const [term,setTerm]=useState(taskPrompt), [filter,setFilter]=useState('All sources');
  const [reload,setReload]=useState(0), [scanning,setScanning]=useState(false), [message,setMessage]=useState(''), [listError,setListError]=useState('');
  useEffect(()=>{setTerm(taskPrompt);setFilter('All sources');},[taskPrompt]);
  const fetchList=useCallback(async(signal?:AbortSignal)=>{const list=await request<Item[]>('/api/episodes',{signal});if(signal?.aborted)return;setItems(list);setPhase('ready');setListError('');},[]);
  useEffect(()=>{const c=new AbortController();setPhase('loading');fetchList(c.signal).catch(()=>{if(!c.signal.aborted){setPhase('error');setListError('Recordings could not be loaded.');}});return ()=>c.abort();},[fetchList,reload]);
  const visible=useMemo(()=>items.filter(i=>(filter==='All sources'||filter===source(i.simulation)) && [i.task,i.checkpoint,source(i.simulation),i.simulation?.seed==null?'':`seed ${i.simulation.seed}`].join(' ').toLowerCase().includes(term.trim().toLowerCase())),[items,filter,term]);
  const current=requested && visible.some(i=>i.id===requested) ? requested : (visible.find(i=>i.simulation?.source!=='observation dry run') ?? visible[0])?.id;
  const [episode,setEpisode]=useState<Episode|null>(null),[detailError,setDetailError]=useState('');
  const [mobileOpen,setMobileOpen]=useState(false);
  useEffect(()=>{const c=new AbortController();setEpisode(null);setDetailError('');if(current){request<Episode>(`/api/episodes/${current}`,{signal:c.signal}).then(r=>{if(!c.signal.aborted)setEpisode(r);}).catch(()=>{if(!c.signal.aborted)setDetailError('This recording could not be opened.');});}return ()=>c.abort();},[current,reload]);
  async function scan(){setScanning(true);setMessage('');try{const r=await request<{imported:number;skipped:string[]}>('/api/rollouts/import',{method:'POST'});await fetchList();setMessage(`Indexed ${r.imported} recording${r.imported===1?'':'s'}.${r.skipped.length?' Skipped: '+r.skipped.join('; '):''}`);}catch{setListError('Scan failed. Check the local recording directory and try again.');}finally{setScanning(false);}}
  return <main className="page run-workspace">
    <header className="work-head"><div><div className="crumb">Workspace <ChevronRight size={13}/> Evaluation</div><h1>Run review</h1></div><button type="button" className="ink-command" disabled={scanning} onClick={()=>void scan()}><ArrowDownToLine size={16}/>{scanning?'Scanning…':'Scan recordings'}</button></header>
    {message&&<p role="status" className="notice">{message}</p>}{listError&&<p role="alert" className="alert">{listError} <button className="text-action" onClick={()=>setReload(v=>v+1)}>Retry</button></p>}
    <div className="review-grid"><section className={`queue ${mobileOpen?'expanded':''}`} aria-label="Recording library">
      <div className="queue-head"><h2>Recordings <span>{items.length}</span></h2><button type="button" className="mobile-change" aria-expanded={mobileOpen} onClick={()=>setMobileOpen(!mobileOpen)}><ListFilter size={16}/>{mobileOpen?'Close':'Choose run'}</button></div>
      <div className="queue-body"><label className="queue-search"><Search size={16}/><input aria-label="Search recordings" placeholder="Search recordings" value={term} onChange={e=>setTerm(e.target.value)}/></label>
      <select className="source-filter" aria-label="Recording source" value={filter} onChange={e=>setFilter(e.target.value)}>{['All sources','Model simulation','Scripted reference','Camera check','Station recording',...(items.some(i=>source(i.simulation)==='Simulator recording')?['Simulator recording']:[])].map(v=><option key={v}>{v}</option>)}</select>
      {phase==='ready'&&visible.map(item=><a key={item.id} className={`queue-row ${item.id===current?'active':''}`} aria-current={item.id===current?'true':undefined} href={screenHref('runs',{...(taskPrompt?{prompt:taskPrompt}:{}),run:item.id})} onClick={()=>setMobileOpen(false)}><span className="queue-line"><span className="run-source">{source(item.simulation)}</span>{item.simulation?.seed!=null&&<span className="seed">#{item.simulation.seed}</span>}</span><strong>{item.task}</strong><span className="queue-foot"><time title={item.started_at_utc??''}>{time(item.started_at_utc)}</time><span>{item.finding_count>0?`${item.finding_count} findings`:human(item.success)}</span></span></a>)}
      {phase==='ready'&&!visible.length&&items.length>0&&<p>No matching recordings. <button className="text-action" onClick={()=>{setTerm('');setFilter('All sources');}}>Clear filters</button></p>}</div></section>
      <section className="review-canvas" aria-label="Selected recording">{phase==='loading'?<p role="status">Loading recordings…</p>:phase==='error'?null:!items.length?<div className="review-empty"><Film size={28}/><h2>No recordings indexed</h2><p>Scan the local rollout directory, or <a href={screenHref('tasks')}>open Tasks</a> to define an experiment.</p></div>:!current?<p>Select another filter to see a recording.</p>:detailError?<p role="alert">{detailError} <button className="text-action" onClick={()=>setReload(v=>v+1)}>Retry</button></p>:episode?.id===current?<Recording key={current} initial={episode} onSaved={e=>{setEpisode(e);setItems(prev=>prev.map(i=>i.id===e.id?{...i,success:e.success}:i));}}/>:<p role="status">Loading recording…</p>}</section>
    </div></main>;
}

function Recording({initial:r,onSaved}:{initial:Episode;onSaved:(e:Episode)=>void}){
  const roles=Object.keys(r.videos), [role,setRole]=useState(roles.includes('overhead')?'overhead':roles[0]||'');
  const video=useRef<HTMLVideoElement>(null), carry=useRef(0), [media,setMedia]=useState<'loading'|'ready'|'failed'>('loading'),[at,setAt]=useState<number|null>(null);
  const [tab,setTab]=useState<'evidence'|'label'|'diagnostics'>('evidence'); const [audit,setAudit]=useState<Audit|null>(null),[auditError,setAuditError]=useState(false);
  const [label,setLabel]=useState(human(r.success)),[stage,setStage]=useState(r.failure_stage||''),[note,setNote]=useState(r.note||''),[saving,setSaving]=useState(false),[notice,setNotice]=useState(''),[saveError,setSaveError]=useState('');
  const [dirty,setDirty]=useState(false);
  const [conflict,setConflict]=useState<Episode|null>(null);
  const mounted=useRef(true);
  useEffect(()=>{mounted.current=true;return ()=>{mounted.current=false;};},[]);
  useEffect(()=>{if(!dirty)return;const before=(ev:BeforeUnloadEvent)=>{ev.preventDefault();ev.returnValue='';};window.addEventListener('beforeunload',before);return ()=>window.removeEventListener('beforeunload',before);},[dirty]);
  useEffect(()=>{if(tab!=='diagnostics')return;const c=new AbortController();setAuditError(false);request<Audit>(`/api/episodes/${r.id}/intent-audit`,{signal:c.signal}).then(v=>{if(!c.signal.aborted)setAudit(v);}).catch(()=>{if(!c.signal.aborted)setAuditError(true);});return ()=>c.abort();},[r.id,tab]);
  function jump(sec:number){const v=video.current;if(!v||media!=='ready')return;v.pause();v.currentTime=Math.min(sec,Number.isFinite(v.duration)?v.duration:sec);setAt(v.currentTime);v.scrollIntoView({block:'nearest'});}
  async function save(){
    if(saving||conflict)return;
    setSaving(true);setNotice('');setSaveError('');
    try{
      const res=await fetch(`/api/episodes/${r.id}/label`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_revision:r.review_revision,success:label==='Unlabelled'?null:label==='Success',failure_stage:label==='Failure'&&stage?stage:null,note:note.trim()||null})});
      if(res.status===409){
        const latest=await request<Episode>(`/api/episodes/${r.id}`);
        if(mounted.current)setConflict(latest);
        return;
      }
      if(!res.ok)throw new Error('Save failed');
      const updated:Episode=await res.json();
      if(mounted.current){onSaved(updated);setDirty(false);setNotice('Operator review saved.');}
    }catch{if(mounted.current)setSaveError('Review was not saved. Your edits are still here.');}
    finally{if(mounted.current)setSaving(false);}
  }
  function resolveConflict(useDraft:boolean){
    if(!conflict)return;
    if(!useDraft){setLabel(human(conflict.success));setStage(conflict.failure_stage||'');setNote(conflict.note||'');}
    onSaved(conflict);setConflict(null);setDirty(useDraft);setSaveError('');
    setNotice(useDraft?'Your draft is unchanged. Review it, then save.':'Now showing the saved review.');
  }
  return <><header className="recording-head"><div className="recording-meta"><span className="source-tag">{source(r.simulation)}</span>{r.simulation?.seed!=null&&<span>Seed {r.simulation.seed}</span>}<span>{r.status} recording</span></div><h2>{r.task}</h2><p>{r.checkpoint}{r.simulation?.start_pose&&` · Start: ${r.simulation.start_pose}`}</p></header>
  {role?<><div className="camera-bar"><span><Camera size={15}/>Camera</span><div role="group" aria-label="Camera angle">{roles.map(k=><button key={k} aria-pressed={k===role} onClick={()=>{if(k===role)return;carry.current=video.current?.currentTime||0;setMedia('loading');setRole(k);}}>{camera(k)}</button>)}</div></div>
    <video key={role} ref={video} className="run-film" controls playsInline preload="auto" onLoadedMetadata={e=>{const v=e.currentTarget;if(carry.current>0)v.currentTime=Math.min(carry.current,Number.isFinite(v.duration)?v.duration:carry.current);setMedia('ready');}} onError={()=>setMedia('failed')} onPlay={()=>setAt(null)} src={`/api/episodes/${r.id}/video/${encodeURIComponent(role)}`}/>
    <div className="clip-foot"><span>{r.duration_s!=null?`${r.duration_s.toFixed(2)} s`: 'Duration unknown'}{r.frames!=null&&` · ${r.frames} frames`}{r.fps!=null&&` · ${r.fps} fps`}</span><span role="status">{media==='failed'?'Video unavailable':at!==null?`Evidence at ${at.toFixed(2)} s`:''}</span></div></>:<p className="no-video"><VideoOff size={18}/>No finished video in this recording.</p>}
  <div className="review-sections" role="group" aria-label="Review sections">{(['evidence','label','diagnostics'] as const).map(k=><button key={k} aria-pressed={k===tab} onClick={()=>setTab(k)}>{{evidence:'Run evidence',label:'Operator review',diagnostics:'Diagnostics'}[k]}</button>)}</div>
  {tab==='evidence'&&<>{r.pickup_evidence?<PickupEvidence result={r.pickup_evidence} jump={role&&media==='ready'?jump:null} videoState={!role||media==='failed'?'unavailable':media}/>:<div className="review-empty"><h3>No automatic assessment</h3><p>Use the recorded evidence and the task’s success rule for a manual review.</p></div>}<div className="review-bottom"><span>Operator outcome: <strong>{human(r.success)}</strong></span><button className="text-action" onClick={()=>setTab('label')}>Review outcome <ChevronRight size={14}/></button></div></>}
  {tab==='label'&&<SimBaseline recording={r}/>}
  {tab==='label'&&<form className="label-form review-form" onSubmit={e=>{e.preventDefault();void save();}}><h3>Operator review</h3>{conflict&&<section className="review-conflict" aria-label="Conflicting review"><strong role="alert">A newer review was saved. Your draft has not been sent again.</strong><p>Saved outcome: {human(conflict.success)}{conflict.failure_stage && ` · ${conflict.failure_stage}`}</p><p>Saved note: {conflict.note || 'No note'}</p><div><button type="button" className="secondary" onClick={()=>resolveConflict(false)}>Use saved review</button><button type="button" className="secondary" onClick={()=>resolveConflict(true)}>Keep editing my draft</button></div></section>}<label>Outcome<select disabled={saving} value={label} onChange={e=>{setLabel(e.target.value);setDirty(true);setNotice('');}}>{['Unlabelled','Success','Failure'].map(s=><option key={s}>{s}</option>)}</select></label>{label==='Failure'&&<label>Failure stage<select disabled={saving} value={stage} onChange={e=>{setStage(e.target.value);setDirty(true);setNotice('');}}><option value="">Unknown</option>{['approach','grasp','transport','release','other'].map(v=><option key={v}>{v}</option>)}</select></label>}<label>Observation<textarea disabled={saving} maxLength={2000} value={note} onChange={e=>{setNote(e.target.value);setDirty(true);setNotice('');}} /></label><button disabled={!dirty||saving||!!conflict}><Save size={15}/>{saving?'Saving…':'Save review'}</button>{notice&&<p role="status"><Check size={15}/>{notice}</p>}{saveError&&<p role="alert">{saveError}</p>}</form>}
  {tab==='diagnostics'&&<div className="technical"><h3>Recording details</h3><dl className="details">{Object.entries({'Stop reason':r.stop_reason,'Error':r.error,'Requests attempted':r.simulation?.requests_attempted,'Model action rows':r.simulation?.model_action_rows,'Stalls':r.stalls,'Clamps':r.clamps}).map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v??'Not reported'}</dd></div>)}</dl><h3>Findings</h3>{r.findings.length?r.findings.map((v,i)=><p key={i}><CircleAlert size={14}/> {v.message} <small>{v.evidence}</small></p>):<p>No diagnostic findings recorded.</p>}<h3>Inference events</h3>{r.events.length?r.events.map((v,i)=><p key={i}>{v.elapsed_s?.toFixed(1)??'?'} s · {v.kind} · {v.detail||v.reason||v.action||'No detail'}</p>):<p>No inference log available.</p>}<h3>Policy intent</h3>{audit?<><p>{audit.comparable_rows} of {audit.command_rows} command rows aligned · {audit.differing_share==null?'Difference not available':`${(audit.differing_share*100).toFixed(1)}% differed`} · Median staleness: {audit.median_staleness_ms==null?'not reported':`${audit.median_staleness_ms.toFixed(0)} ms`} · {audit.discarded_replies} discarded replies.</p>{audit.warnings.map(w=><p key={w}>{w}</p>)}</>:<p>{auditError?'Command audit unavailable.':'Loading command audit…'}</p>}</div>}</>;
}
