"""Single-host DreamCoach gateway with a separate local worker per browser workspace."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
import uvicorn
from dream import DreamClient
from dream.errors import DreamError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from teach_task_coach.assistant import CHAT_WELCOME

COOKIE = "__Host-dreamcoach"
PREVIEW_COOKIE = "dreamcoach-preview"
WORKSPACE_SECONDS = 7 * 24 * 60 * 60
IDLE_SECONDS = 30 * 60
MAX_BODY = 512 * 1024
SITE = Path(__file__).resolve().parents[2] / "frontend" / "dist"
SAFE_HEADERS = {"content-type", "range", "if-range", "accept"}
RESPONSE_HEADERS = {"content-type", "content-length", "content-range", "accept-ranges"}
HARDWARE_PATH = re.compile(
    r"(?:^api/teleop/|/teleop/start$|/prepare-scene$|^api/trials/[^/]+/(?:start|stop|sync|reconcile)$|/deployment/rollback$|/promote$)"
)
HOST_ENV = {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR",
    "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR", "MUJOCO_GL", "PYOPENGL_PLATFORM",
}


def browser_workspace_dir(root: Path, token: str) -> Path:
    return root / hashlib.sha256(token.encode()).hexdigest()


def workspace_environment(path: Path) -> dict[str, str]:
    # The host's Dream/OpenAI keys and station configuration are never inherited.
    environment = {key: value for key, value in os.environ.items() if key.upper() in HOST_ENV}
    environment.update(
        COACH_DATA_DIR=str(path / "data"),
        COACH_DEMOS_DIR=str(path / "demos"),
        COACH_ROLLOUTS_DIR=str(path / "rollouts"),
        COACH_AI_CREDENTIALS=str(path / "ai-credentials.dpapi"),
        COACH_STATION_URL="http://127.0.0.1:1",
        COACH_ARMS_LOCK=str(path / "arms.lock"),
        DREAM_CREDENTIALS=str(path / "dream-credentials"),
        DREAM_LOG="off",
        DREAM_YAM_CONFIG_DIR=str(path / "yam-config"),
        PYTHONUNBUFFERED="1",
    )
    if os.name == "nt":
        environment["USERPROFILE"] = str(path)
    return environment


@dataclass
class Worker:
    process: subprocess.Popen
    port: int
    touched: float

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"


class WorkspacePool:
    def __init__(self, root: Path, limit: int, maximum_workspaces: int) -> None:
        self.root = root.resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.limit = limit
        self.maximum_workspaces = maximum_workspaces
        self.workers: dict[Path, Worker] = {}
        self.lock = threading.RLock()
        self.creations: deque[float] = deque()
        self.pending_creations = 0

    def locate(self, token: str | None) -> Path | None:
        if token is None or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            return None
        path = browser_workspace_dir(self.root, token)
        try:
            created = int((path / "created").read_text(encoding="ascii"))
        except (FileNotFoundError, ValueError):
            return None
        return path if time.time() < created + WORKSPACE_SECONDS else None

    def reserve_creation(self) -> None:
        with self.lock:
            now = time.monotonic()
            while self.creations and now - self.creations[0] > 60:
                self.creations.popleft()
            if len(self.creations) >= 8:
                raise HTTPException(429, "Workspace creation is busy. Wait a minute and try again.")
            self.creations.append(now)
            if len(self.workers) + self.pending_creations >= self.limit:
                raise HTTPException(503, "All simulator workspaces are busy. Try again later.")
            self.pending_creations += 1

    def release_creation(self) -> None:
        with self.lock:
            self.pending_creations -= 1

    def create(self, key: str) -> str:
        with self.lock:
            if sum(path.is_dir() for path in self.root.iterdir()) >= self.maximum_workspaces:
                raise HTTPException(503, "Workspace storage is full. Contact the site operator.")
            token = secrets.token_urlsafe(32)
            path = browser_workspace_dir(self.root, token)
            path.mkdir(mode=0o700)
            descriptor = os.open(path / "dream-credentials", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="ascii") as file:
                file.write(f"DREAM_API_KEY={key}\n")
            (path / "created").write_text(str(int(time.time())), encoding="ascii")
            return token

    def get(self, path: Path) -> Worker:
        with self.lock:
            for key, worker in list(self.workers.items()):
                if worker.process.poll() is not None:
                    del self.workers[key]
            existing = self.workers.get(path)
            if existing is not None:
                existing.touched = time.monotonic()
                return existing
            if len(self.workers) >= self.limit:
                raise HTTPException(503, "All simulator workspaces are busy. Try again shortly.")
            with socket.socket() as port_socket:
                port_socket.bind(("127.0.0.1", 0))
                port = port_socket.getsockname()[1]
            process = subprocess.Popen(
                [sys.executable, "-m", "teach_task_coach.cli", "serve", "--port", str(port)],
                env=workspace_environment(path),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            worker = Worker(process, port, time.monotonic())
            self.workers[path] = worker
            try:
                with httpx.Client(timeout=0.5, trust_env=False) as client:
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline and process.poll() is None:
                        try:
                            if client.get(worker.origin + "/health").is_success:
                                return worker
                        except httpx.RequestError:
                            pass
                        time.sleep(0.15)
            finally:
                if process.poll() is not None:
                    self.workers.pop(path, None)
            self.workers.pop(path, None)
            self.stop(worker)
            raise HTTPException(503, "DreamCoach could not start your workspace. Please try again.")

    @staticmethod
    def stop(worker: Worker) -> None:
        if worker.process.poll() is None:
            worker.process.terminate()
            try:
                worker.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.process.kill()
                worker.process.wait()

    def reap_idle(self) -> None:
        with self.lock:
            for path, worker in list(self.workers.items()):
                if worker.process.poll() is not None:
                    del self.workers[path]
                    continue
                if time.monotonic() - worker.touched < IDLE_SECONDS:
                    continue
                # Active simulator capture or FaaS polling should survive tab closure.
                with httpx.Client(timeout=2, trust_env=False) as client:
                    try:
                        yam = client.get(worker.origin + "/api/simulator/workflow").json() or {}
                        click = client.get(worker.origin + "/api/sim-correction/status").json()
                    except (httpx.HTTPError, ValueError):
                        continue
                if yam.get("state") in {"running", "stopping"} or click.get("state") == "recording":
                    continue
                # Keep the worker for queued or running paid work as well.
                from teach_task_coach.faas import FaaSStore

                jobs = FaaSStore(path / "data").list_finetunes()
                if any(job.status in {"pending_upload", "processing", "pending_training", "training"} for job in jobs):
                    continue
                self.stop(worker)
                del self.workers[path]

    def close(self) -> None:
        with self.lock:
            for worker in self.workers.values():
                self.stop(worker)
            self.workers.clear()


def verify_dream_key(key: str) -> None:
    try:
        DreamClient(api_key=key).get_models()
    except DreamError as exc:
        raise HTTPException(400, "Dream Labs could not validate this API key.") from exc


def create_gateway(
    data_root: Path,
    origin: str,
    *,
    workspace_limit: int = 4,
    maximum_workspaces: int = 128,
    validator: Callable[[str], None] = verify_dream_key,
) -> FastAPI:
    parsed = urlsplit(origin)
    local = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    if not parsed.netloc or origin != f"{parsed.scheme}://{parsed.netloc}" or (
        parsed.scheme != "https" and not local
    ) or parsed.username or parsed.password:
        raise ValueError("COACH_PUBLIC_ORIGIN must be an HTTPS origin, with no path or trailing slash.")
    cookie_name = PREVIEW_COOKIE if local else COOKIE
    pool = WorkspacePool(data_root, workspace_limit, maximum_workspaces)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        async def cleanup():
            while True:
                await asyncio.sleep(60)
                await asyncio.to_thread(pool.reap_idle)

        async with httpx.AsyncClient(timeout=60, trust_env=False, follow_redirects=False) as client:
            app.state.upstream = client
            task = asyncio.create_task(cleanup())
            try:
                yield
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                await asyncio.to_thread(pool.close)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.pool = pool

    @app.middleware("http")
    async def private_origin(request: Request, call_next):
        if request.url.path != "/health" and request.headers.get("host", "").lower() != parsed.netloc.lower():
            return JSONResponse({"detail": "Incorrect host."}, status_code=421)
        # All browser mutations must originate from this deployment.
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("origin") != origin:
            return JSONResponse({"detail": "Incorrect request origin."}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    if (SITE / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=SITE / "assets"), name="assets")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/")
    async def root(request: Request):
        connected = pool.locate(request.cookies.get(cookie_name)) is not None
        workspace_state = "connected" if connected else "required"
        page = (SITE / "index.html").read_text(encoding="utf-8")
        page = page.replace(
            "</head>",
            '<meta name="dreamcoach-mode" content="hosted">'
            f'<meta name="dreamcoach-workspace" content="{workspace_state}">'
            f'<meta name="dreamcoach-introduction" content="{escape(CHAT_WELCOME)}"></head>',
        )
        return HTMLResponse(page)

    @app.post("/hosted/workspace", status_code=201)
    async def workspace(request: Request):
        if pool.locate(request.cookies.get(cookie_name)) is not None:
            return JSONResponse({"detail": "This browser already has a workspace."}, status_code=409)
        payload = await bounded_body(request, maximum=2048)
        try:
            key = json.loads(payload)["api_key"]
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(400, "Enter a Dream Labs API key.") from exc
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{12,300}", key):
            raise HTTPException(400, "Enter a Dream Labs API key.")
        pool.reserve_creation()
        try:
            await asyncio.to_thread(validator, key)
            token = await asyncio.to_thread(pool.create, key)
        finally:
            pool.release_creation()
        response = JSONResponse({"ready": True}, status_code=201)
        response.set_cookie(cookie_name, token, max_age=WORKSPACE_SECONDS, secure=not local,
                            httponly=True, samesite="lax", path="/")
        return response

    @app.api_route("/api/{subpath:path}", methods=["GET", "POST", "HEAD"], response_model=None)
    async def proxy(subpath: str, request: Request):
        path = pool.locate(request.cookies.get(cookie_name))
        if path is None:
            raise HTTPException(401, "Create a DreamCoach workspace first.")
        local_path = "api/" + subpath
        if local_path.startswith("api/docs/"):
            raise HTTPException(404)
        if HARDWARE_PATH.search(local_path) or local_path in {"api/account/connect", "api/simulator/prepare"}:
            raise HTTPException(403, "Use the provisioned simulator and the Dream account for this workspace.")
        if any(part in {"", ".", ".."} for part in subpath.split("/")):
            raise HTTPException(404)
        payload = await bounded_body(request) if request.method == "POST" else None
        worker = await asyncio.to_thread(pool.get, path)
        client: httpx.AsyncClient = request.app.state.upstream
        headers = {k: v for k, v in request.headers.items() if k in SAFE_HEADERS}
        if request.method == "POST":
            headers["origin"] = worker.origin
        url = worker.origin + "/" + quote(local_path, safe="/")
        outgoing = client.build_request(request.method, url, params=request.query_params,
                                        headers=headers, content=payload)
        try:
            upstream = await client.send(outgoing, stream=True)
        except httpx.RequestError as exc:
            raise HTTPException(503, "The workspace is temporarily unavailable.") from exc

        async def stream():
            try:
                async for block in upstream.aiter_bytes():
                    yield block
            finally:
                await upstream.aclose()

        return StreamingResponse(stream(), status_code=upstream.status_code,
                                 headers={k: v for k, v in upstream.headers.items() if k in RESPONSE_HEADERS})

    return app


async def bounded_body(request: Request, maximum: int = MAX_BODY) -> bytes:
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > maximum:
            raise HTTPException(413, "This request is too large.")
        chunks.extend(chunk)
    return bytes(chunks)


def main() -> None:
    origin = os.getenv("COACH_PUBLIC_ORIGIN") or os.environ["RENDER_EXTERNAL_URL"]
    gateway = create_gateway(
        Path(os.environ["COACH_HOSTED_DATA_DIR"]), origin,
        workspace_limit=int(os.getenv("COACH_MAX_ACTIVE_WORKSPACES", "4")),
    )
    uvicorn.run(gateway, host=os.getenv("COACH_HOSTED_BIND", "0.0.0.0"),
                port=int(os.getenv("PORT", "10000")), access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()
