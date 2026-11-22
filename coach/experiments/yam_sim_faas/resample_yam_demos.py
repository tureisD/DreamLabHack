"""Export single-episode YAM simulator recordings as 10 Hz LeRobot v2.1 training sessions."""

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import av
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

# Use the same v2.1 schema and statistics writer as the bundled Dream station.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "dream_library/robots/src"))
from robots.rollout_episode import _stats, _write_meta

FPS = 10
ARM_PARTS = [f"joint_{i}" for i in range(6)] + ["gripper"]
VECTOR_NAMES = [f"{arm}_{part}" for arm in ("right", "left") for part in ARM_PARTS]


def export_camera(source, target, raw_frames):
    target.parent.mkdir(parents=True, exist_ok=True)
    decoded = 0
    with av.open(str(source)) as src, av.open(str(target), "w") as dst:
        video = src.streams.video[0]
        stream = dst.add_stream("libx264", rate=FPS)
        stream.width, stream.height = video.width, video.height
        stream.pix_fmt = "yuv420p"
        stream.options = {"preset": "fast", "crf": "25"}
        for index, frame in enumerate(src.decode(video)):
            if frame.pts is None or abs(float(frame.time) - index / 20) > 0.001:
                raise ValueError(f"{source}: unexpected source timestamp at row {index}")
            decoded += 1
            if index % 2 == 0:
                for packet in stream.encode(frame):
                    dst.mux(packet)
        for packet in stream.encode():
            dst.mux(packet)
    if decoded != raw_frames:
        raise ValueError(f"{source}: decoded {decoded} source frames, expected {raw_frames}")
    with av.open(str(target)) as encoded:
        video = encoded.streams.video[0]
        pixels = []
        for i, frame in enumerate(encoded.decode(video)):
            if abs(float(frame.time) - i / FPS) > 0.001:
                raise ValueError(f"{target}: unexpected timestamp at row {i}")
            if i % FPS == 0:
                pixels.append(frame.to_ndarray(format="rgb24")[::4, ::4].reshape(-1, 3) / 255.)
        width, height = video.width, video.height
    stats = _stats(np.concatenate(pixels), len(pixels))
    return {
        "dtype": "video", "shape": [height, width, 3], "names": ["height", "width", "channels"],
        "info": {"video.height": height, "video.width": width, "video.channels": 3, "video.codec": "h264",
                 "video.pix_fmt": "yuv420p", "video.is_depth_map": False, "has_audio": False},
        "stats": {key: value if key == "count" else [[[x]] for x in value] for key, value in stats.items()},
    }


def export_session(session, output):
    info = json.loads((session / "meta/info.json").read_text(encoding="utf-8"))
    if info["fps"] != 20 or info["total_episodes"] != 1:
        raise ValueError(f"{session}: expected one 20 Hz episode")
    path = Path("data/chunk-000/episode_000000.parquet")
    raw = pq.read_table(session / path)
    if not raw.num_rows or raw.num_rows != info["total_frames"]:
        raise ValueError(f"{session}: frame count differs between parquet and metadata or episode is empty")
    if not np.allclose(raw["timestamp"].to_numpy(), np.arange(raw.num_rows) / 20, rtol=0, atol=0.001):
        raise ValueError(f"{session}: source state/action timestamps are not on the 20 Hz video clock")
    sample = raw.take(pa.array(np.arange(0, raw.num_rows, 2)))
    n = sample.num_rows
    indices = np.arange(n, dtype=np.int64)[:, None]
    columns = {name: np.asarray(sample[name].to_pylist(), dtype=np.float32)
               for name in ("observation.state", "action")}
    if any(x.shape != (n, 14) or not np.isfinite(x).all() for x in columns.values()):
        raise ValueError(f"{session}: invalid YAM vectors")
    columns.update(timestamp=(indices / FPS).astype(np.float32), frame_index=indices, index=indices,
                   episode_index=np.zeros_like(indices), task_index=np.zeros_like(indices))
    parquet = pa.table({k: pa.array(v[:, 0] if v.shape[1] == 1 else list(v)) for k, v in columns.items()})
    (output / path).parent.mkdir(parents=True)
    pq.write_table(parquet, output / path)
    videos = {}
    for role in ("overhead", "wrist_l", "wrist_r"):
        relative = Path(f"videos/chunk-000/observation.images.{role}/episode_000000.mp4")
        videos[role] = export_camera(session / relative, output / relative, raw.num_rows)
    task = json.loads((session / "meta/tasks.jsonl").read_text(encoding="utf-8"))["task"]
    _write_meta(output, {"frames": n, "fps": FPS, "task": task, "body": "yam"}, columns, videos, VECTOR_NAMES)
    return n


def reviewed_source(store, source, task_id, demo_id):
    from teach_task_coach.demos import read_demo

    demo = store.get(demo_id)
    if demo and demo.origin == "offline_fixture":
        raise ValueError("Offline fixture demos are never eligible for training conversion.")
    origins = {"human", "scripted_reference"}
    if not demo or demo.task_id != task_id or demo.decision != "keep" or not demo.valid or demo.origin not in origins:
        raise ValueError(f"Choose a kept, valid demonstration for this task: {demo_id}")
    session = Path(demo.source_path).resolve()
    if session.parent != source:
        raise ValueError("Selected demo is outside the specified source directory.")
    current = read_demo(session, demo.task_id)
    if (
        not current.valid or current.origin != demo.origin or current.offline_task_id is not None
        or current.evidence_sha256 != demo.evidence_sha256
    ):
        raise ValueError("Selected demo evidence changed or belongs to an offline fixture. Rescan the source.")
    conversion = session / "meta/conversion.json"
    if conversion.is_file():
        existing = json.loads(conversion.read_text(encoding="utf-8"))
        if existing.get("origin") == "offline_fixture" or existing.get("offline_task_id"):
            raise ValueError("Offline fixture conversions are never eligible for training resampling.")
    raw_sidecar = (session / "rollout.json").read_bytes()
    sidecar = json.loads(raw_sidecar)
    simulation = sidecar.get("simulation") or {}
    if sidecar.get("status") != "complete" or simulation.get("source") != "scripted":
        raise ValueError("Choose a complete, explicitly scripted recording.")
    if simulation.get("policy_origin") == "offline_fixture":
        raise ValueError("Offline fixture recordings are never eligible for training conversion.")
    return session, {
        "source_demo_id": demo.id,
        "source_task_id": demo.task_id,
        "source_recording_id": sidecar.get("recording_id"),
        "source_sidecar_sha256": hashlib.sha256(raw_sidecar).hexdigest(),
        "source": simulation["source"],
        "origin": demo.origin,
        "source_fps": 20,
        "output_fps": FPS,
        "selection": "even source frames",
        "start_cell": demo.start_cell,
    }


def main():
    from teach_task_coach.demos import DemoStore, read_demo

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path.cwd() / "yam_sim_dataset_20hz")
    parser.add_argument("--output", type=Path, default=Path.cwd() / "yam_sim_dataset_10hz")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--kept-demo", action="append", required=True,
                        help="Coach ID of a reviewed and kept scripted demo. Repeat to select more.")
    args = parser.parse_args()
    source, target = args.source.resolve(), args.output.resolve()
    if target == source or target.is_relative_to(source):
        parser.error("Choose a separate output directory outside the source")
    store = DemoStore()
    try:
        selected = [reviewed_source(store, source, args.task_id, item)
                    for item in dict.fromkeys(args.kept_demo)]
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    target.mkdir(parents=True, exist_ok=True)
    for session, provenance in selected:
        output = target / session.name
        if output.exists():
            parser.error(f"Output session already exists: {output}. Choose a fresh output directory.")
        with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
            stage = Path(tmp) / session.name
            n = export_session(session, stage)
            (stage / "meta/conversion.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
            if not read_demo(stage, args.task_id).valid:
                raise ValueError(f"Converted session failed media validation: {output}")
            stage.rename(output)
        print(f"resampled {session.name}: {n} frames at {FPS} Hz")


if __name__ == "__main__":
    main()
