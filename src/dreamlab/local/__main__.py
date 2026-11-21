"""Run the development API on loopback only."""

import argparse


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000, help="Loopback port (default: 8000)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    uvicorn.run("dreamlab.local.api:create_app", factory=True, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
