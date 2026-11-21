"""Start the local API or inspect read-only preflight results from a terminal."""

import argparse

import uvicorn

from teach_task_coach.preflight import PreflightService


def main() -> None:
    parser = argparse.ArgumentParser(prog="teach-task-coach")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("preflight", help="Check station and Dream model access without robot motion")
    serve = subcommands.add_parser("serve", help="Serve the local coach API")
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.command == "preflight":
        print(PreflightService().run().model_dump_json(indent=2))
    else:
        uvicorn.run("teach_task_coach.api:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
