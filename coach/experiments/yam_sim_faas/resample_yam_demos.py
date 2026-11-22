"""Export single-episode YAM simulator recordings as 10 Hz LeRobot v2.1 training sessions."""

import argparse
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


def export_camera(source, target, expected_frames):
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with av.open(str(source)) as src, av.open(str(target), "w") as dst:
        video = src.streams.video[0]
        stream = dst.add_stream("libx264", rate=FPS)
        stream.width, stream.height = video.width, video.height
        stream.pix_fmt = "yuv420p"
        stream.options = {"preset": "fast", "crf": "25"}
        for index, frame in enumerate(src.decode(video)):
            if index % 2 == 0:
                for packet in stream.encode(frame):
                    dst.mux(packet)
                count += 1
        for packet in stream.encode():
            dst.mux(packet)
    if count != expected_frames:
        raise ValueError(f"{source}: kept {count} frames, expected {expected_frames}")
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
        videos[role] = export_camera(session / relative, output / relative, n)
    task = json.loads((session / "meta/tasks.jsonl").read_text(encoding="utf-8"))["task"]
    _write_meta(output, {"frames": n, "fps": FPS, "task": task, "body": "yam"}, columns, videos, VECTOR_NAMES)
    return n


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path.cwd() / "yam_sim_dataset_20hz")
    parser.add_argument("--output", type=Path, default=Path.cwd() / "yam_sim_dataset_10hz")
    args = parser.parse_args()
    source, target = args.source.resolve(), args.output.resolve()
    if target == source or target.is_relative_to(source):
        parser.error("Choose a separate output directory outside the source")
    target.mkdir(parents=True, exist_ok=True)
    for session in sorted(path for path in source.iterdir() if path.is_dir()):
        output = target / session.name
        if output.exists():
            parser.error(f"Output session already exists: {output}. Choose a fresh output directory.")
        with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
            stage = Path(tmp) / session.name
            n = export_session(session, stage)
            stage.rename(output)
        print(f"resampled {session.name}: {n} frames at {FPS} Hz")


if __name__ == "__main__":
    main()
