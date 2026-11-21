"""Record Dream Labs' scripted MuJoCo YAM pickups as LeRobot v2.1 sessions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import av
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image

SIM = Path(__file__).resolve().parents[3] / "dream_library/examples/yam_mujoco"
sys.path.insert(0, str(SIM))
import mock_pickups
from yam_env import YamEnv

ROOT = Path.cwd() / "yam_sim_dataset_20hz"
TASK = "pick up the apple"
FPS = 20
ROLES = {"top": "overhead", "left": "wrist_l", "right": "wrist_r"}
PARTS = {
    "right_arm": [0, 6], "right_gripper": [6, 7],
    "left_arm": [7, 13], "left_gripper": [13, 14],
}
CONFIG = {
    "state": PARTS,
    "action": PARTS,
    "video": {role: f"observation.images.{role}" for role in ROLES.values()},
}


class RecordingYamEnv(YamEnv):
    episode = 0

    def __init__(self):
        super().__init__()
        self.folder = ROOT / f"apple-{type(self).episode:03d}"
        type(self).episode += 1
        self.states: list[np.ndarray] = []
        self.actions: list[np.ndarray] = []
        self.outputs = {}
        for role in ROLES.values():
            video = self.folder / f"videos/chunk-000/observation.images.{role}/episode_000000.mp4"
            video.parent.mkdir(parents=True, exist_ok=True)
            container = av.open(str(video), "w")
            stream = container.add_stream("libx264", rate=FPS)
            stream.width, stream.height = 320, 176
            stream.pix_fmt = "yuv420p"
            stream.options = {"preset": "fast", "crf": "25"}
            self.outputs[role] = (container, stream)

    def step(self, left, right):
        state = self.state()
        self.states.append(np.r_[state["right"], state["left"]].astype(np.float32))
        self.actions.append(np.r_[right, left].astype(np.float32))
        images = self.images()
        for camera, role in ROLES.items():
            rgb = np.asarray(Image.fromarray(images[camera]).resize((320, 176), Image.Resampling.BILINEAR))
            container, stream = self.outputs[role]
            frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        return super().step(left, right)

    def close(self):
        for container, stream in self.outputs.values():
            for packet in stream.encode():
                container.mux(packet)
            container.close()
        self._write_metadata()
        super().close()

    def _write_metadata(self):
        n = len(self.states)
        dim = 14
        vectors = {}
        for name, values in (("action", self.actions), ("observation.state", self.states)):
            flat = np.asarray(values, dtype=np.float32).reshape(-1)
            offsets = pa.array(np.arange(0, flat.size + 1, dim, dtype=np.int32))
            vectors[name] = pa.ListArray.from_arrays(offsets, pa.array(flat))
        table = pa.table(vectors | {
            "timestamp": np.arange(n) / FPS,
            "episode_index": np.zeros(n, dtype=np.int64),
        })
        data = self.folder / "data/chunk-000/episode_000000.parquet"
        data.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, data)
        meta = self.folder / "meta"
        meta.mkdir(parents=True, exist_ok=True)
        feature = {"dtype": "float32", "shape": [dim], "names": [f"joint_{i}" for i in range(dim - 1)] + ["gripper"]}
        video_feature = {"dtype": "video", "shape": [176, 320, 3], "names": ["height", "width", "channels"]}
        info = {
            "codebase_version": "v2.1", "total_episodes": 1, "total_frames": n,
            "fps": FPS, "chunks_size": 1000,
            "data_path": "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet",
            "video_path": "videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4",
            "features": {"action": feature, "observation.state": feature}
            | {f"observation.images.{role}": video_feature for role in ROLES.values()},
        }
        (meta / "info.json").write_text(json.dumps(info), encoding="utf-8")
        (meta / "tasks.jsonl").write_text(json.dumps({"task_index": 0, "task": TASK}) + "\n", encoding="utf-8")
        (meta / "episodes.jsonl").write_text(json.dumps({"episode_index": 0, "tasks": [TASK], "length": n}) + "\n", encoding="utf-8")
        print(f"recorded {self.folder.name}: {n} frames, {n/FPS:.1f}s", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT, help="Output dataset directory")
    parser.add_argument("--episodes", type=int, default=2, help="Number of scripted pickup episodes")
    args = parser.parse_args()
    if args.episodes < 1:
        parser.error("--episodes must be positive")
    ROOT = args.output.resolve()
    ROOT.mkdir(exist_ok=True)
    mock_pickups.YamEnv = RecordingYamEnv
    for _ in range(args.episodes):
        result = mock_pickups.run_trial("apple", yaw=0, lift=0.15)
        if not result["passed"]:
            raise SystemExit("Scripted pickup failed; do not train on this dataset.")
    manifest = ROOT.with_name(ROOT.name + "-manifest.json")
    manifest.write_text(json.dumps({"source": "Dream Labs yam_mujoco scripted pickup", "task": TASK, "embodiment": CONFIG}, indent=2), encoding="utf-8")
