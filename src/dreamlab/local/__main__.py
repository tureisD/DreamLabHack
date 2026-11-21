"""Run the development API on loopback only."""


def main() -> None:
    import uvicorn

    uvicorn.run("dreamlab.local.api:create_app", factory=True, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
