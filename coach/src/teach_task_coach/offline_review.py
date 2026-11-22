"""Task-scoped offline fixture review; never infer Dream-1 or hardware results."""

import hashlib
import json
from collections import defaultdict
from typing import Any

from pydantic import BaseModel

from teach_task_coach.demos import DemoStore
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskStore


class OfflineAttempt(BaseModel):
    episode_id: str
    role: str
    checkpoint: str
    status: str
    seed: int | None
    source: str
    action_rows: int | None
    action_budget: int | None
    request_count: int | None
    rule: str | None
    evidence: dict[str, Any] | None
    outcome: bool | None
    failure_stage: str | None
    note: str | None
    review_revision: int
    videos: dict[str, str]
    video_roles: list[str]


class OfflineScenePair(BaseModel):
    scene_id: str
    seed: int
    baseline: OfflineAttempt | None
    candidate: OfflineAttempt | None
    comparable: bool
    human_reviewed: bool
    exclusion: str | None


class OfflineReview(BaseModel):
    task_id: str
    complete_pairs: int = 0
    label: str = "Offline scripted fixtures · not Dream-1 evidence"
    protocol: str
    protocol_sha256: str
    scenes: list[OfflineScenePair]
    planned_scenes: int
    comparable_pairs: int
    human_reviewed_pairs: int
    demos: list[dict[str, Any]]


def review(task_id: str, tasks: TaskStore, episodes: EpisodeStore, demo_store: DemoStore) -> OfflineReview:
    task = tasks.get_task(task_id)
    if task is None:
        raise KeyError(task_id)
    if not task.offline_mode:
        raise ValueError("This task is not an offline fixture task.")
    manifest_path = tasks.db.data_dir / "offline-protocol.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        protocol_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if manifest.get("task_id") != task_id or manifest.get("schema") != "coach-offline-walkthrough-v1":
            raise ValueError("The offline fixture protocol belongs to a different task or version.")
        specs = {item["id"]: item for item in manifest.get("scenes", [])}
    except FileNotFoundError:
        # Test/import compatibility for explicitly fixture-tagged episodes in an offline task.
        # Never infer fixture provenance from a prompt or checkpoint name alone.
        manifest = {"schema": "coach-offline-fixture-import-v1", "task_id": task_id, "scenes": []}
        protocol_hash = ""
        specs = {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("The offline fixture protocol is invalid.") from exc

    attempts: dict[str, dict[str, OfflineAttempt]] = defaultdict(dict)
    ordered = sorted(episodes.list(), key=lambda episode: (episode.started_at_utc or "", episode.id))
    for episode in ordered:
        sim = episode.simulation or {}
        if sim.get("offline_task_id") != task_id or sim.get("policy_origin") != "offline_fixture":
            continue
        scene_id = sim.get("offline_scene_id")
        role = sim.get("comparison_role")
        if not isinstance(scene_id, str) or role not in ("baseline", "candidate"):
            continue
        if scene_id not in specs and not manifest_path.exists():
            specs[scene_id] = {"id": scene_id, "seed": sim.get("seed"), "sides": []}
        if scene_id not in specs or (specs[scene_id].get("sides") and role not in specs[scene_id].get("sides", [])):
            continue
        if role in attempts[scene_id]:
            continue
        attempts[scene_id][role] = OfflineAttempt(
            episode_id=episode.id,
            role=role,
            checkpoint=episode.checkpoint,
            status=episode.status,
            seed=sim.get("seed") if type(sim.get("seed")) is int else None,
            source="scripted fixture" if sim.get("source") == "scripted" else "unknown fixture controller",
            action_rows=sim.get("model_action_rows") if type(sim.get("model_action_rows")) is int else None,
            action_budget=sim.get("action_budget") if type(sim.get("action_budget")) is int else None,
            request_count=sim.get("requests_attempted") if type(sim.get("requests_attempted")) is int else None,
            rule=episode.pickup_evidence.rule if episode.pickup_evidence else None,
            evidence=episode.pickup_evidence.model_dump() if episode.pickup_evidence else None,
            outcome=episode.success,
            failure_stage=episode.failure_stage,
            note=episode.note,
            review_revision=episode.review_revision,
            videos=episode.videos,
            video_roles=sorted(episode.videos),
        )

    scenes = []
    for scene_id, spec in specs.items():
        sides = attempts[scene_id]
        baseline, candidate = sides.get("baseline"), sides.get("candidate")
        valid_sides = bool(baseline and candidate)
        if valid_sides:
            valid_sides = all(
                side.status == "complete"
                and side.action_rows == side.action_budget
                and side.action_rows is not None
                and {"overhead", "wrist_l", "wrist_r"}.issubset(side.video_roles)
                and (side.evidence is not None)
                and side.source == "scripted fixture"
                for side in (baseline, candidate)
            )
        by_id = {episode.id: episode for episode in ordered}
        baseline_episode = by_id.get(baseline.episode_id) if baseline else None
        candidate_episode = by_id.get(candidate.episode_id) if candidate else None
        baseline_sim = baseline_episode.simulation or {} if baseline_episode else {}
        candidate_sim = candidate_episode.simulation or {} if candidate_episode else {}
        if baseline and candidate and not manifest_path.exists():
            spec_seed = spec.get("seed")
            valid_sides = bool(valid_sides and baseline.seed == candidate.seed == spec_seed
                               and baseline_sim.get("pre_action_state_hash")
                               and baseline_sim.get("pre_action_state_hash") == candidate_sim.get("pre_action_state_hash")
                               and baseline_sim.get("protocol_hash") == candidate_sim.get("protocol_hash")
                               and baseline_episode.task == candidate_episode.task == task.prompt)
        state_matches = bool(
            baseline and candidate
            and baseline_sim.get("pre_action_state_hash")
            and baseline_sim.get("pre_action_state_hash") == candidate_sim.get("pre_action_state_hash")
            and (not spec.get("pre_action_state_hash")
                 or spec["pre_action_state_hash"] == baseline_sim.get("pre_action_state_hash"))
            and baseline_sim.get("protocol_sha256", baseline_sim.get("protocol_hash", ""))
                == candidate_sim.get("protocol_sha256", candidate_sim.get("protocol_hash", ""))
            and (not protocol_hash or baseline_sim.get("protocol_sha256") == protocol_hash)
            and baseline.seed == candidate.seed == spec.get("seed")
            and baseline_episode is not None and candidate_episode is not None
            and baseline_episode.task == candidate_episode.task == task.prompt
        )
        comparable = bool(valid_sides and state_matches)
        exclusion = None if comparable else (
            "Missing planned side" if not valid_sides and (baseline is None or candidate is None) else
            "Capture, video, or action-budget validation failed" if not valid_sides else
            "Pre-action states do not match the frozen protocol"
        )
        scenes.append(OfflineScenePair(
            scene_id=scene_id,
            seed=spec["seed"],
            baseline=baseline,
            candidate=candidate,
            comparable=comparable,
            human_reviewed=bool(comparable and baseline and candidate and baseline.outcome is not None and candidate.outcome is not None),
            exclusion=exclusion,
        ))

    fixture_episode_ids = {
        episode.id for episode in ordered
        if (episode.simulation or {}).get("policy_origin") == "offline_fixture"
        and (episode.simulation or {}).get("offline_task_id") == task_id
    }
    demos = [
        {
            "id": demo.id,
            "origin": demo.origin,
            "decision": demo.decision,
            "valid": demo.valid,
            "source_episode_id": demo.source_episode_id,
            "start_cell": demo.start_cell,
            "frames": demo.frames,
            "fps": demo.fps,
            "camera_keys": demo.camera_keys,
        }
        for demo in demo_store.list(task_id)
        if demo.origin == "scripted_reference" and demo.source_episode_id in fixture_episode_ids
    ]
    comparable_pairs = sum(scene.comparable for scene in scenes)
    return OfflineReview(
        task_id=task_id,
        protocol=manifest["schema"],
        protocol_sha256=protocol_hash,
        scenes=scenes,
        complete_pairs=comparable_pairs,
        planned_scenes=len(scenes),
        comparable_pairs=comparable_pairs,
        human_reviewed_pairs=sum(scene.human_reviewed for scene in scenes),
        demos=demos,
    )
