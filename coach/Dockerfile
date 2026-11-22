FROM node:22-bookworm-slim AS frontend
WORKDIR /build/coach/frontend
COPY coach/frontend/package.json coach/frontend/package-lock.json ./
RUN npm ci
COPY coach/frontend/index.html coach/frontend/tsconfig.json coach/frontend/vite.config.ts ./
COPY coach/frontend/src ./src
COPY coach/experiments/yam_sim_faas/closed_loop_repair_report.json \
     coach/experiments/yam_sim_faas/horizon_confirmation_report.json \
     /build/coach/experiments/yam_sim_faas/
RUN npm run build

FROM python:3.11-slim-bookworm AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.11.18 /uv /usr/local/bin/uv
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg libgl1 libosmesa6 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY dream_library /app/dream_library
COPY shared /app/shared
COPY coach/pyproject.toml coach/uv.lock /app/coach/
COPY coach/src /app/coach/src
COPY coach/experiments /app/coach/experiments
COPY --from=frontend /build/coach/frontend/dist /app/coach/frontend/dist
WORKDIR /app/coach
RUN uv sync --locked --no-dev --extra sim \
    && useradd --system --uid 10001 --create-home dreamcoach \
    && install -d -m 0700 -o dreamcoach -g dreamcoach /var/lib/dreamcoach
ENV MUJOCO_GL=osmesa \
    DREAM_LOG=off \
    COACH_HOSTED_DATA_DIR=/var/lib/dreamcoach \
    PORT=10000 \
    UV_NO_SYNC=1
USER dreamcoach
EXPOSE 10000
CMD ["/app/coach/.venv/bin/python", "-m", "teach_task_coach.hosted"]
