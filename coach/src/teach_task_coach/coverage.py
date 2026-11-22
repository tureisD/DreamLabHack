"""Evidence-linked suggestions for the next demonstration grid cell."""

from pydantic import BaseModel

from teach_task_coach.baseline_workflow import findings, scoreable
from teach_task_coach.demos import DemoStore
from teach_task_coach.storage import EpisodeStore
from teach_task_coach.tasks import TaskStore


class CellCoverage(BaseModel):
    cell: int
    baseline_runs: int
    baseline_failures: int
    kept_demos: int
    priority: float


class CoveragePlan(BaseModel):
    cells: list[CellCoverage]
    next_cell: int | None
    reason: str
    observed_failure_cells_covered: bool


def plan(task_id: str, tasks: TaskStore, episodes: EpisodeStore, demos: DemoStore) -> CoveragePlan:
    setup_ids = {f.episode_id for f in findings(task_id, tasks, episodes)}
    totals = [0] * 9
    failures = [0] * 9
    kept = [0] * 9
    for trial in tasks.list_trials(task_id):
        if trial.status != "completed" or trial.episode_id is None:
            continue
        episode = episodes.get(trial.episode_id)
        if episode is None or episode.id in setup_ids or not scoreable(episode, trial.status):
            continue
        totals[trial.start_cell] += 1
        failures[trial.start_cell] += int(not episode.success)
    for demo in demos.training_eligible(task_id):
        if demo.decision == "keep" and demo.valid and demo.start_cell is not None:
            kept[demo.start_cell] += 1

    cells = [
        CellCoverage(
            cell=cell,
            baseline_runs=totals[cell],
            baseline_failures=failures[cell],
            kept_demos=kept[cell],
            priority=round(((failures[cell] + 1) / (totals[cell] + 2)) / (kept[cell] + 1), 3),
        )
        for cell in range(9)
    ]
    if sum(totals) == 0:
        return CoveragePlan(
            cells=cells,
            next_cell=None,
            reason="Label baseline trials before collecting targeted demonstrations.",
            observed_failure_cells_covered=False,
        )
    # Prioritize observed failure cells; unknown cells remain visible on the map.
    candidates = [cell for cell in cells if cell.baseline_failures > 0]
    if not candidates:
        return CoveragePlan(
            cells=cells,
            next_cell=None,
            reason="No baseline failures were observed. Add harder baseline setups before fine-tuning.",
            observed_failure_cells_covered=False,
        )
    uncovered = [cell for cell in candidates if cell.kept_demos == 0]
    if not uncovered:
        return CoveragePlan(cells=cells, next_cell=None, reason='Every observed failure cell has a valid kept demonstration.', observed_failure_cells_covered=True)
    next_cell = max(uncovered, key=lambda item: (item.priority, -item.cell))
    return CoveragePlan(
        cells=cells,
        next_cell=next_cell.cell,
        reason=(
            f"Cell {next_cell.cell + 1} had {next_cell.baseline_failures} failures in "
            f"{next_cell.baseline_runs} baseline runs and {next_cell.kept_demos} kept demos."
        ),
        observed_failure_cells_covered=False,
    )
