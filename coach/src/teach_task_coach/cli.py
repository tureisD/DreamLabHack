"""Start the local API or inspect read-only preflight results from a terminal."""

import argparse

import uvicorn

from teach_task_coach.demos import DemoStore
from teach_task_coach.faas import FaaSStore, run_worker
from teach_task_coach.preflight import PreflightService
from teach_task_coach.storage import default_data_dir
from teach_task_coach.tasks import TaskStore


def main() -> None:
    parser = argparse.ArgumentParser(prog="teach-task-coach")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("preflight", help="Check station and Dream model access without robot motion")
    serve = subcommands.add_parser("serve", help="Serve the local coach API")
    serve.add_argument("--port", type=int, default=8765)
    worker = subcommands.add_parser("worker", help="Advance local dataset and Dream FaaS jobs")
    worker.add_argument("--interval", type=float, default=30)
    args = parser.parse_args()

    if args.command == "preflight":
        print(PreflightService().run().model_dump_json(indent=2))
    elif args.command == "serve":
        uvicorn.run("teach_task_coach.api:app", host="127.0.0.1", port=args.port)
    else:
        data_dir = default_data_dir()
        run_worker(FaaSStore(data_dir), TaskStore(data_dir), DemoStore(data_dir), args.interval)


if __name__ == "__main__":
    main()
