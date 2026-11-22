"""Evidence-linked next action for a Dream-1 task, without invented demo counts."""

from typing import Literal

from pydantic import BaseModel

from teach_task_coach.coverage import plan
from teach_task_coach.demos import DemoStore
from teach_task_coach.evaluation import EvaluationStore
from teach_task_coach.faas import FaaSStore, FineTuneRequest
from teach_task_coach.repair import RepairStore
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskStore


class Guidance(BaseModel):
    task_id: str
    phase: Literal["baseline", "collect", "review", "train", "wait", "evaluate", "verdict", "fix"]
    headline: str
    next_action: str
    evidence: list[str]
    target_screen: Literal["tasks", "runs", "demos", "training", "evaluation", "repair"]
    pilot_ready: bool
    suggested_recipe: FineTuneRequest | None = None


def guidance(
    task_id: str,
    tasks: TaskStore,
    episodes: EpisodeStore,
    demos: DemoStore,
    faas: FaaSStore,
    evaluations: EvaluationStore,
    repairs: RepairStore | None = None,
) -> Guidance:
    trials = tasks.list_trials(task_id)
    labelled = []
    station_problems = []
    for trial in trials:
        if trial.status != "completed" or not trial.episode_id:
            continue
        episode = episodes.get(trial.episode_id)
        if episode is None or episode.success is None:
            continue
        labelled.append(episode)
        station_problems.extend(
            finding.message for finding in episode.findings if finding.severity == "problem"
        )
    failures = sum(episode.success is False for episode in labelled)
    demos_for_task = demos.list(task_id)
    kept = [demo for demo in demos_for_task if demo.decision == "keep" and demo.valid]
    pending = sum(demo.decision == "unreviewed" for demo in demos_for_task)
    coverage = plan(task_id, tasks, episodes, demos)
    evidence = [
        f"{len(labelled)} labelled baseline runs; {failures} failures.",
        f"{len(kept)} kept, valid demos; {pending} waiting for review.",
    ]
    if station_problems:
        return Guidance(
            task_id=task_id, phase="fix", headline="Inspect station faults before training",
            next_action="Review the affected rollout and fix the station or setup before collecting more data.",
            evidence=evidence + sorted(set(station_problems)), target_screen="runs", pilot_ready=False,
        )

    versions = faas.list_datasets(task_id)
    jobs = faas.list_finetunes(task_id)
    latest_job = jobs[0] if jobs else None
    unsubmitted = [
        version for version in versions
        if not any(job.dataset_version_id == version.id for job in jobs)
    ]
    if unsubmitted and (latest_job is None or latest_job.status in ("succeeded", "failed")):
        latest_job = None
        versions = unsubmitted
    if latest_job:
        if latest_job.status in ("pending_upload", "processing", "pending_training", "training"):
            return Guidance(
                task_id=task_id, phase="wait", headline="FaaS job is in progress",
                next_action="Watch the job status. The worker reconciles uploads and training after a restart.",
                evidence=evidence + [f"Job {latest_job.id[:8]}: {latest_job.status}."],
                target_screen="training", pilot_ready=True,
            )
        if latest_job.status == "failed":
            return Guidance(
                task_id=task_id, phase="fix", headline="Training needs attention",
                next_action="Inspect the job error and create a corrected dataset version before resubmitting.",
                evidence=evidence + [latest_job.error or "The FaaS job failed."],
                target_screen="training", pilot_ready=False,
            )
        if latest_job.status == "succeeded":
            relevant = [item for item in evaluations.list(task_id) if item.fine_tune_job_id == latest_job.id]
            if not relevant:
                return Guidance(
                    task_id=task_id, phase="evaluate", headline="Checkpoint is ready for a real task test",
                    next_action="Plan a paired baseline versus candidate comparison on held-out setups.",
                    evidence=evidence + [f"Candidate checkpoint: {latest_job.checkpoint}."],
                    target_screen="evaluation", pilot_ready=True,
                )
            evaluation = relevant[0]
            evaluation_trials = tasks.list_evaluation_trials(evaluation.id)
            if any(trial.status == "abandoned" for trial in evaluation_trials):
                return Guidance(
                    task_id=task_id, phase="evaluate", headline="Restart the incomplete comparison",
                    next_action="Plan a fresh comparison; the unusable trial remains in the record.",
                    evidence=evidence + [f"Evaluation {evaluation.id[:8]} contains an unusable run."],
                    target_screen="evaluation", pilot_ready=True,
                )
            report = evaluations.report(evaluation, tasks, episodes)
            if report.usable_pairs < report.target_pairs:
                return Guidance(
                    task_id=task_id, phase="evaluate", headline="Finish the held-out comparison",
                    next_action="Run and label the next supervised scene pair.",
                    evidence=evidence + [f"{report.usable_pairs} of {report.target_pairs} usable pairs."],
                    target_screen="evaluation", pilot_ready=True,
                )
            if report.decision == "improved":
                return Guidance(
                    task_id=task_id, phase="verdict", headline="Candidate cleared the task threshold",
                    next_action="Review videos and safety events, then decide whether to switch the deployed checkpoint.",
                    evidence=evidence + [report.reason], target_screen="evaluation", pilot_ready=True,
                )
            return Guidance(
                task_id=task_id, phase="verdict", headline=f"Candidate result is {report.decision}",
                next_action="Review the paired failures, collect targeted demos if needed, and train a new dataset version.",
                evidence=evidence + [report.reason], target_screen="evaluation", pilot_ready=False,
            )

    if failures and repairs is not None:
        studies = repairs.list(task_id)
        if not studies:
            return Guidance(
                task_id=task_id, phase="fix", headline="Test a cheap repair before FaaS",
                next_action="Compare a prompt or setup change on matched scenes; training may be unnecessary.",
                evidence=evidence, target_screen="repair", pilot_ready=False,
            )
        repair_report = repairs.report(studies[0], tasks, episodes)
        if repair_report.decision == "use_fix":
            return Guidance(
                task_id=task_id, phase="fix", headline="Use the cheaper repair",
                next_action=repair_report.recommendation,
                evidence=evidence + [f"Repair audit: {repair_report.input_sha256}."],
                target_screen="repair", pilot_ready=False,
            )
        if repair_report.decision in ("not_evaluable", "inconclusive"):
            return Guidance(
                task_id=task_id, phase="fix", headline="Finish the cheap repair comparison",
                next_action=repair_report.recommendation,
                evidence=evidence + repair_report.problems,
                target_screen="repair", pilot_ready=False,
            )
        evidence.append("A matched cheap repair produced no observed gain; FaaS is worth considering.")

    if versions:
        latest_version = versions[0]
        if latest_version.status == "pending_validation":
            return Guidance(
                task_id=task_id, phase="wait", headline="Dataset validation is queued",
                next_action="Start or check the local worker, then review the validation report.",
                evidence=evidence + [f"Dataset {latest_version.id[:8]} is pending validation."],
                target_screen="training", pilot_ready=False,
            )
        if latest_version.status == "failed":
            return Guidance(
                task_id=task_id, phase="fix", headline="Dataset validation failed",
                next_action="Fix the reported dataset issue and create a new version.",
                evidence=evidence + [latest_version.error or "Dataset validation failed."],
                target_screen="training", pilot_ready=False,
            )
        if latest_version.status == "validated":
            return Guidance(
                task_id=task_id, phase="train", headline="Validated dataset is ready for a pilot",
                next_action="Review the frozen demos and explicitly submit the first FaaS job.",
                evidence=evidence + [f"Dream local validation passed for dataset {latest_version.id[:8]}."],
                target_screen="training", pilot_ready=True,
                suggested_recipe=FineTuneRequest(),
            )

    if not labelled:
        return Guidance(
            task_id=task_id, phase="baseline", headline="Measure the current checkpoint first",
            next_action="Run supervised baseline trials across the object start grid and label success.",
            evidence=evidence, target_screen="tasks", pilot_ready=False,
        )
    if not failures:
        return Guidance(
            task_id=task_id, phase="baseline", headline="Find a baseline failure to target",
            next_action="Try harder or more varied setups and label the outcomes before collecting demos.",
            evidence=evidence, target_screen="tasks", pilot_ready=False,
        )
    if pending:
        return Guidance(
            task_id=task_id, phase="review", headline="Review newly recorded demonstrations",
            next_action="Inspect each episode, then keep or redo it with a labelled start cell.",
            evidence=evidence, target_screen="demos", pilot_ready=False,
        )
    if not coverage.observed_failure_cells_covered:
        return Guidance(
            task_id=task_id, phase="collect", headline="Cover observed failure positions",
            next_action=coverage.reason + " Record and review a demonstration there next.",
            evidence=evidence, target_screen="demos", pilot_ready=False,
        )
    return Guidance(
        task_id=task_id, phase="train", headline="Coverage supports an initial pilot",
        next_action="Freeze the kept demos as a dataset, run Dream validation, then review the FaaS submission.",
        evidence=evidence + ["Each observed failure cell has at least one kept demo; this does not guarantee success."],
        target_screen="training", pilot_ready=True, suggested_recipe=FineTuneRequest(),
    )
