"""End-to-end contract for the offline review loop. No station or Dream calls."""

import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_demos import make_demo

from teach_task_coach.api import create_app
from teach_task_coach.demos import DemoScanner, DemoStore
from teach_task_coach.episodes import RolloutScanner
from teach_task_coach.preflight import PreflightService
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskStore, TrialInput


class NoExternalCalls:
    def __getattr__(self, name):
        raise AssertionError(f'Offline acceptance must never call {name}')


def local_client(root):
    return TestClient(create_app(PreflightService(NoExternalCalls(), NoExternalCalls()), EpisodeStore(root/'data'),RolloutScanner(root/'rollouts'),demo_scanner=DemoScanner(root/'demos'),dream_gateway=NoExternalCalls()))


def task(c, name):
    response=c.post('/api/tasks',json={'name':name,'prompt':'pick up the apple','baseline_checkpoint':'base','success_rule':'Lift and hold for two seconds.'})
    assert response.status_code == 201
    return response.json()['id']


def recording(root, **fields):
    uid=uuid4().hex
    p=root/'rollouts'/uid
    p.mkdir(parents=True)
    info={'recording_id':uid,'status':'complete','collection_mode':'simulation','body':'yam','task':'pick up the apple','checkpoint':'base','frames':100,'fps':20,'simulation':{'source':'model','policy_origin':'dream_model','model_action_rows':60,'start_pose':'wrist-visible','seed':41,'apple_xy_m':[0.12,0.01]},'stop_reason':'finished'}
    info.update(fields)
    (p/'rollout.json').write_text(json.dumps(info))
    return p


def scan(c):
    assert c.post('/api/rollouts/import').is_success
    return [c.get('/api/episodes/'+r['id']).json() for r in c.get('/api/episodes').json()]


def at(c, task_id, episode_id, cell=2):
    return c.post(f'/api/tasks/{task_id}/sim-baselines',json={'episode_id':episode_id,'start_cell':cell})


def label(c, eid, value, rev=0):
    return c.post(f'/api/episodes/{eid}/label',json={'success':value,'failure_stage':'grasp' if value is False else None,'expected_revision':rev})


def offline_client(root):
    from teach_task_coach.tasks import TaskInput

    data = root / "offline-data"
    tasks = TaskStore(data)
    task = tasks.create_task(
        TaskInput(name="Offline fixture", prompt="pick up the apple", baseline_checkpoint="offline-fixture/baseline", success_rule="lift and hold"),
        offline_mode=True,
    )
    manifest = {
        "schema": "coach-offline-walkthrough-v1", "task_id": task.id,
        "rule_version": "yam-apple-v1",
        "scenes": [{"id": "scene-1", "seed": 41, "sides": ["baseline", "candidate"]}],
    }
    (data / "offline-protocol.json").write_text(json.dumps(manifest))
    client = TestClient(create_app(
        PreflightService(NoExternalCalls(), NoExternalCalls()), EpisodeStore(data),
        RolloutScanner(root / "rollouts"), task_store=tasks,
        demo_store=DemoStore(data), demo_scanner=DemoScanner(root / "demos"),
        dream_gateway=NoExternalCalls(), offline_only=True,
    ))
    return client, task.id, data


def offline_recording(root, task_id, *, scene="scene-1", role="baseline", seed=41):
    path = root / "rollouts" / uuid4().hex
    path.mkdir(parents=True)
    sim = {
        "source": "scripted", "policy_origin": "offline_fixture", "offline_task_id": task_id,
        "offline_scene_id": scene, "comparison_role": role, "seed": seed,
        "model_action_rows": 20, "action_budget": 20, "protocol": "coach-offline-walkthrough-v1",
        "rule_version": "yam-apple-v1", "pre_action_state_hash": "state-1",
        "protocol_sha256": hashlib.sha256((root / "offline-data/offline-protocol.json").read_bytes()).hexdigest(),
        "apple_xy_m": [0.1, 0.1], "start_pose": "wrist-visible",
    }
    (path / "rollout.json").write_text(json.dumps({
        "recording_id": uuid4().hex, "status": "complete", "collection_mode": "simulation",
        "body": "yam", "task": "pick up the apple", "checkpoint": f"offline-fixture/{role}",
        "frames": 20, "fps": 20, "simulation": sim, "stop_reason": "finished",
    }))
    return path


def test_offline_label_scope_and_normal_import_isolation(tmp_path):
    from teach_task_coach.episodes import episode_id

    client, task_id, _data = offline_client(tmp_path)
    offline_recording(tmp_path, task_id)
    foreign_task_id = "not-the-fixture-task"
    foreign = offline_recording(tmp_path, foreign_task_id)
    recording(tmp_path)
    result = client.post("/api/rollouts/import").json()
    assert result["imported"] == 1 and len(result["skipped"]) == 2
    imported = client.get("/api/episodes").json()
    assert len(imported) == 1
    owned_id = imported[0]["id"]
    assert client.post(f"/api/episodes/{owned_id}/label", json={"success": False, "expected_revision": 0}).status_code == 200
    foreign_episode_id = episode_id(foreign)
    assert client.post(f"/api/episodes/{foreign_episode_id}/label", json={"success": True, "expected_revision": 0}).status_code == 404
    assert client.get(f"/api/episodes/{foreign_episode_id}").status_code == 404
    assert client.post("/api/tasks", json={"name":"no", "prompt":"x", "baseline_checkpoint":"base", "success_rule":"x"}).status_code == 403


def test_standard_workspace_rejects_offline_fixture_import_and_labels(tmp_path):
    _, task_id, data = offline_client(tmp_path)
    fixture = offline_recording(tmp_path, task_id)
    recording(tmp_path)
    standard = TestClient(create_app(
        PreflightService(NoExternalCalls(), NoExternalCalls()), EpisodeStore(data),
        RolloutScanner(tmp_path / "rollouts"), task_store=TaskStore(data),
        demo_store=DemoStore(data), demo_scanner=DemoScanner(tmp_path / "demos"),
        dream_gateway=NoExternalCalls(),
    ))
    result = standard.post("/api/rollouts/import").json()
    assert result["imported"] == 1 and len(result["skipped"]) == 1
    assert len(standard.get("/api/episodes").json()) == 1
    from teach_task_coach.episodes import episode_id
    assert standard.post(f"/api/episodes/{episode_id(fixture)}/label", json={"success": True}).status_code == 404
    assert standard.get("/api/offline-review/" + task_id).status_code == 404


def test_offline_guide_from_unlabelled_run_to_kept_demo(tmp_path):
    c=local_client(tmp_path); a=task(c,'A'); b=task(c,'B'); path=recording(tmp_path)
    r,=scan(c); eid=r['id']; route=f'/api/tasks/{b}'
    def g(): return c.get(route+'/guidance').json()
    assert at(c,b,eid).json()['status']=='awaiting_label'
    assert g()['labelled_baseline_runs']==0
    assert label(c,eid,False).is_success
    assert (g()['labelled_baseline_runs'],g()['task_failures'],g()['target_cell'])==(1,1,2)
    assert c.get(route+'/diagnosis').json()['failure_stages']=={'grasp':1}
    shutil.copytree(path,path.with_name('a-copy'))
    c=local_client(tmp_path); assert len(scan(c))==1
    assert at(c,b,eid).json()['status']=='completed' and len(c.get(route+'/baseline-trials').json())==1
    assert at(c,a,eid).status_code==409 and at(c,b,eid,3).status_code==409
    assert c.get(f'/api/tasks/{a}/guidance').json()['labelled_baseline_runs']==0
    folder=make_demo(tmp_path/'demos'); (folder/'meta/tasks.jsonl').write_text('{"task":"pick up the apple"}\n')
    assert c.post(route+'/demos/import').json()['imported']==1
    d,=c.get(route+'/demos').json(); decision='/api/demos/'+d['id']+'/decision'
    assert c.post(decision,json={'decision':'keep','start_cell':2}).is_success
    assert g()['phase']=='train'
    assert c.post(decision,json={'decision':'redo'}).is_success and g()['target_cell']==2
    assert c.post(decision,json={'decision':'keep','start_cell':2}).is_success
    next((folder/'videos').rglob('*.mp4')).unlink(); c.post(route+'/demos/import')
    assert g()['phase']=='review' and g()['target_cell']==2
    assert c.get(route+'/demos').json()[0]['decision']=='unreviewed'  # Changed evidence requires fresh human review.
    assert label(c,eid,True,0).status_code==409
    assert label(c,eid,None,1).is_success and g()['labelled_baseline_runs']==0
    assert c.get(route+'/baseline-trials').json()[0]['status']=='awaiting_label'
    assert label(c,eid,True,2).is_success and (g()['labelled_baseline_runs'],g()['task_failures'])==(1,0)


@pytest.mark.parametrize('override',[{'status':'partial'},{'checkpoint':'wrong'},{'task':'another prompt'},{'collection_mode':'unknown'},{'simulation':{'source':'scripted'}},{'simulation':{'source':'observation dry run'}},{'simulation':{'source':'model','model_action_rows':0}},{'simulation':None}])
def test_ineligible_recordings_remain_visible_not_scored(tmp_path,override):
    c=local_client(tmp_path); t=task(c,'A');recording(tmp_path,**override);r,=scan(c)
    assert at(c,t,r['id']).status_code==409
    assert c.get(f'/api/tasks/{t}/guidance').json()['labelled_baseline_runs']==0


def test_concurrent_confirm_and_independent_same_seed(tmp_path):
    c=local_client(tmp_path);t=task(c,'A');recording(tmp_path);recording(tmp_path);r,s=scan(c)
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _: at(c,t,r['id']).json()['trial_id'],range(2)))
    assert len(set(results))==1 and at(c,t,s['id'],5).json()['trial_id']!=results[0]
    for e in (r,s): assert label(c,e['id'],False).is_success
    assert c.get(f'/api/tasks/{t}/guidance').json()['task_failures']==2


def test_tasks_and_run_review_share_one_committed_verdict(tmp_path):
    c = local_client(tmp_path)
    owner, other = task(c, 'Owner'), task(c, 'Control')
    recording(tmp_path)
    run, = scan(c)
    eid = run['id']
    url = '/api/trials/' + at(c, owner, eid).json()['trial_id'] + '/label'
    initial = {'success': False, 'failure_stage': 'grasp', 'note': 'Reviewed the clip'}
    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(lambda _: c.post(url, json=initial), range(2)))
    assert sorted(r.status_code for r in replies) == [200, 409]
    assert next(r for r in replies if r.is_success).json()['status'] == 'completed'
    assert c.get('/api/episodes/' + eid).json()['review_revision'] == 1
    assert label(c, eid, True, 0).status_code == 409
    assert c.get(f'/api/tasks/{owner}/guidance').json()['task_failures'] == 1
    assert c.get(f'/api/tasks/{other}/guidance').json()['labelled_baseline_runs'] == 0
    assert label(c, eid, True, 1).is_success
    assert c.post(url, json=initial).status_code == 409
    saved = local_client(tmp_path).get('/api/episodes/' + eid).json()
    assert (saved['success'], saved['review_revision']) == (True, 2)
    assert c.get(f'/api/tasks/{owner}/guidance').json()['task_failures'] == 0


def test_trial_status_write_failure_rolls_back_operator_label(tmp_path):
    import sqlite3

    c = local_client(tmp_path)
    owner = task(c, 'Owner')
    recording(tmp_path, collection_mode='station', simulation=None)
    run, = scan(c)
    tasks = TaskStore(tmp_path/'data')
    trial = tasks.create_trial(owner, TrialInput(start_cell=2))
    tasks.transition(trial.id, 'planned', 'awaiting_label', episode_id=run['id'])
    with tasks.db.connect() as db:
        db.execute("""CREATE TRIGGER inject_write_failure BEFORE UPDATE OF status ON trials
                     WHEN NEW.status='completed' BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='simulated disk failure'):
        tasks.complete_review(trial.id, False, 'grasp', None)
    assert tasks.get_trial(trial.id).status == 'awaiting_label'
    saved = c.get('/api/episodes/' + run['id']).json()
    assert (saved['success'], saved['review_revision']) == (None, 0)


def test_fault_review_is_historical_not_a_model_failure(tmp_path):
    c=local_client(tmp_path); t=task(c,'A'); tasks=TaskStore(tmp_path/'data'); base=f'/api/tasks/{t}'; ids=[]
    def add(stop,success):
        p=recording(tmp_path,collection_mode='station',simulation=None,stop_reason=stop)
        e=next(r for r in scan(c) if r['source_path']==str(p)); ids.append(e['id']);tr=tasks.create_trial(t,TrialInput(start_cell=2));tasks.transition(tr.id,'planned','completed',episode_id=e['id']);label(c,e['id'],success)
    add('SafetyStop',False);add('finished',True)
    assert c.get(base+'/guidance').json()['phase']=='fix'
    issue,=c.get(base+'/diagnosis').json()['findings']; path=base+'/findings/'+issue['id']+'/review'
    assert c.post(path,json={'reason':' '}).status_code==422
    first=c.post(path,json={'reason':'Inspected log and control recording'}).json()
    assert first['reviewed_at'] and c.post(path,json={'reason':'Double click'}).json()==first
    c=local_client(tmp_path)
    result=c.get(base+'/guidance').json();assert (result['phase'],result['task_failures'],result['labelled_baseline_runs'])==('baseline',0,1)
    add('SafetyStop',False);add('SafetyStop',False)
    dx=c.get(base+'/diagnosis').json();assert (len(dx['findings']),dx['open_finding_count'],dx['data_count'])==(3,2,0)
    assert c.get(base+'/guidance').json()['phase']=='fix'
