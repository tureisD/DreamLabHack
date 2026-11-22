"""Observed local workflow counts for an operator study; no counterfactual claims."""

from __future__ import annotations

from pydantic import BaseModel

from teach_task_coach.demos import DemoStore
from teach_task_coach.evaluation import EvaluationStore
from teach_task_coach.faas import FaaSStore
from teach_task_coach.repair import RepairStore
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskStore


class TaskFootprint(BaseModel):
    task_id: str
    task_created_at: str
    baseline_trials: int
    repair_trials: int
    demos_imported: int
    demos_kept: int
    dataset_versions: int
    faas_jobs_submitted: int
    faas_steps_submitted: int
    evaluations_planned: int
    validated_improvements: int
    notes: list[str]


def footprint(
    task_id: str, tasks: TaskStore, demos: DemoStore, faas: FaaSStore,
    evaluations: EvaluationStore, episodes: EpisodeStore, repairs: RepairStore,
) -> TaskFootprint:
    task = tasks.get_task(task_id)
    if task is None:
        raise KeyError(task_id)
    all_demos = demos.list(task_id)
    studies = evaluations.list(task_id)
    jobs = faas.list_finetunes(task_id)
    submitted = [job for job in jobs if job.remote_job_id]
    repair_trials = sum(len(tasks.list_repair_trials(study.id)) for study in repairs.list(task_id))
    validated = sum(
        evaluations.report(study, tasks, episodes).decision == "improved"
        for study in studies
    )
    return TaskFootprint(
        task_id=task_id, task_created_at=task.created_at,
        baseline_trials=len(tasks.list_trials(task_id)), repair_trials=repair_trials,
        demos_imported=len(all_demos), demos_kept=sum(demo.decision == "keep" for demo in all_demos),
        dataset_versions=len(faas.list_datasets(task_id)),
        faas_jobs_submitted=len(submitted), faas_steps_submitted=sum(job.steps for job in submitted),
        evaluations_planned=len(studies), validated_improvements=validated,
        notes=[
            "Counts cover this local coach database only; recordings and jobs made elsewhere are absent.",
            "Submitted steps are not the actual Dream bill or completed training steps.",
            "Elapsed wall time and operator hands-on minutes require separate session logs.",
            "These counts do not establish savings without a comparable standard-workflow group.",
        ],
    )
