"""Read-only audit of commanded actions against raw Dream policy replies."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from pydantic import BaseModel


class IntentAudit(BaseModel):
    episode_path: str
    status: str
    command_rows: int
    comparable_rows: int
    differing_rows: int
    differing_share: float | None
    median_staleness_ms: float | None
    discarded_replies: int
    warnings: list[str]


def audit_rollout(folder: Path) -> IntentAudit:
    info = json.loads((folder / "rollout.json").read_text(encoding="utf-8"))
    files = sorted((folder / "data").rglob("*.parquet"))
    warnings: list[str] = []
    if not files:
        return IntentAudit(
            episode_path=str(folder), status=info.get("status", "unknown"), command_rows=0,
            comparable_rows=0, differing_rows=0, differing_share=None,
            median_staleness_ms=None, discarded_replies=0,
            warnings=["No finalized action parquet; an empty or partial rollout cannot be compared."],
        )
    table = pq.read_table(files[0], columns=["action", "rollout.chunk", "rollout.row"])
    commands = np.asarray(table["action"].to_pylist(), dtype=float)
    chunks = table["rollout.chunk"].to_pylist()
    rows = table["rollout.row"].to_pylist()
    raw_files = sorted((folder / "chunks").glob("reply_*.npz"))
    events = []
    log = folder / "inference.jsonl"
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                event = json.loads(line)
                if event.get("kind") == "inference":
                    events.append(event)
    if len(events) != len(raw_files):
        warnings.append("Reply files and inference events differ in count; only indexed matches are compared.")
    by_chunk: dict[int, Path] = {}
    staleness = []
    discarded = 0
    fps = float(info.get("fps") or 0)
    for event, path in zip(events, raw_files):
        if event.get("discarded"):
            discarded += 1
            continue
        chunk = event.get("chunk")
        if isinstance(chunk, int):
            by_chunk[chunk] = path
            if fps > 0 and isinstance(event.get("executed_since_obs"), (int, float)):
                staleness.append(event["executed_since_obs"] / fps * 1000)
    comparable = differing = 0
    cached: dict[Path, tuple[np.ndarray, np.ndarray] | None] = {}
    for command, chunk, row in zip(commands, chunks, rows, strict=True):
        path = by_chunk.get(chunk)
        if path is None or not isinstance(row, int) or row < 0:
            continue
        if path not in cached:
            try:
                with np.load(path, allow_pickle=False) as reply:
                    cached[path] = (reply["q_l_chunk"], reply["q_r_chunk"])
            except (OSError, KeyError, ValueError):
                cached[path] = None
        pair = cached[path]
        if pair is None or row >= len(pair[0]) or row >= len(pair[1]):
            continue
        intended = np.concatenate((pair[0][row], pair[1][row])).astype(float)
        if intended.shape != command.shape:
            continue
        comparable += 1
        differing += int(not np.allclose(intended, command, atol=1e-3, rtol=0))
    if not comparable:
        warnings.append("No rows could be aligned to a same-width raw reply; no label-repair claim is possible.")
    return IntentAudit(
        episode_path=str(folder), status=info.get("status", "unknown"),
        command_rows=len(commands), comparable_rows=comparable, differing_rows=differing,
        differing_share=differing / comparable if comparable else None,
        median_staleness_ms=statistics.median(staleness) if staleness else None,
        discarded_replies=discarded, warnings=warnings,
    )
