"""CLI for the coach-effectiveness study analyzer."""

from teach_task_coach.benchmark import analyze, main

__all__ = ["analyze", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
