"""Record Dream Labs' scripted MuJoCo YAM pickups as LeRobot v2.1 sessions."""

from __future__ import annotations

import argparse
import csv
import json
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4
import sys
from pathlib import Path

import av
import mujoco
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image

SIM = Path(__file__).resolve().parents[3] / "dream_library/examples/yam_mujoco"
sys.path.insert(0, str(SIM))
import mock_pickups
from yam_env import YamEnv

from teach_task_coach.pickup_evidence import COLUMNS, TRACE

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
    def __init__(self, folder, task, seed, *, defer_video=False, start_pose="home"):
        super().__init__()
        self.folder = folder
        self.task = task
        apple = self.data.joint("apple_free").qpos
        apple[:2] += np.random.default_rng(seed).uniform(-0.025, 0.025, size=2)
        if start_pose == "wrist-visible":
            # Fixed simulator-only starting pose. The open gripper still has to approach.
            for index, angle in enumerate((-0.4, 1.4, 1.4, -1.35, 0.0, 0.0), 1):
                name = f"left_joint{index}"
                self.data.joint(name).qpos[0] = angle
                self.data.actuator(name).ctrl[0] = angle
        elif start_pose != "home":
            raise ValueError(f"Unknown simulator start pose: {start_pose}")
        mujoco.mj_forward(self.model, self.data)
        self.apple_xy = apple[:2].tolist()
        self.states: list[np.ndarray] = []
        self.actions: list[np.ndarray] = []
        self.video_poses = [] if defer_video else None
        self.apple_trace = []
        self.apple_body = self.model.body("apple").id
        self.tip_bodies = {
            self.model.body(f"{side}_tip_{tip}").id: (hand, 1 << index)
            for hand, side in enumerate(("left", "right"))
            for index, tip in enumerate(("left", "right"))
        }
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
        # Sample before step, like the review video. Deferred rendering rewinds qpos in close().
        if self.task.strip().casefold() == TASK:
            fingers = [0, 0]
            other = False
            for c in self.data.contact:
                if c.dist > 0 or c.efc_address < 0 or min(c.geom1, c.geom2) < 0:
                    continue
                a, b = self.model.geom_bodyid[[c.geom1, c.geom2]]
                if self.apple_body not in (a, b):
                    continue
                tip = self.tip_bodies.get(b if a == self.apple_body else a)
                if tip is None:
                    other = True
                else:
                    hand, bit = tip
                    fingers[hand] |= bit
            self.apple_trace.append(
                (len(self.states), self.data.body("apple").xpos[2].item(), *fingers, int(other))
            )
        state = self.state()
        self.states.append(np.r_[state["right"], state["left"]].astype(np.float32))
        self.actions.append(np.r_[right, left].astype(np.float32))
        if self.video_poses is None:
            self._write_video_frame()
        else:
            # Store the actual full scene pose, including the free apple. Rendering
            # review videos between model calls can outlast the gateway session.
            self.video_poses.append((self.data.time, self.data.qpos.copy()))
        return super().step(left, right)

    def _write_video_frame(self):
        images = self.images()
        for camera, role in ROLES.items():
            rgb = np.asarray(Image.fromarray(images[camera]).resize((320, 176), Image.Resampling.BILINEAR))
            container, stream = self.outputs[role]
            frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)

    def close(self):
        if self.video_poses is not None:
            for instant, pose in self.video_poses:
                self.data.time = instant
                self.data.qpos[:] = pose
                mujoco.mj_forward(self.model, self.data)
                self._write_video_frame()
        for container, stream in self.outputs.values():
            for packet in stream.encode():
                container.mux(packet)
            container.close()
        self._write_metadata()
        if self.apple_trace:
            with (self.folder / TRACE).open("w", newline="", encoding="ascii") as stream:
                writer = csv.writer(stream, lineterminator="\n")
                writer.writerow(COLUMNS)
                writer.writerows(self.apple_trace)
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
        parts = [f"joint_{i}" for i in range(6)] + ["gripper"]
        names = [f"{side}_{part}" for side in ("right", "left") for part in parts]
        feature = {"dtype": "float32", "shape": [dim], "names": names}
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
        (meta / "tasks.jsonl").write_text(json.dumps({"task_index": 0, "task": self.task}) + "\n", encoding="utf-8")
        (meta / "episodes.jsonl").write_text(json.dumps({"episode_index": 0, "tasks": [self.task], "length": n}) + "\n", encoding="utf-8")
        print(f"recorded {self.folder.name}: {n} frames, {n/FPS:.1f}s", flush=True)


def scene_seed(value):
    seed = int(value)
    if seed < 0:
        raise argparse.ArgumentTypeError("Use a nonnegative scene seed")
    return seed


@contextmanager
def recording(root, task, checkpoint, seed, source, *, start_pose="home"):
    root.mkdir(parents=True, exist_ok=True)
    folder = root / f"yam-{uuid4().hex}"
    folder.mkdir()
    started = datetime.now(timezone.utc).isoformat()
    env = RecordingYamEnv(folder, task, seed, defer_video=source == "model", start_pose=start_pose)
    details = {"source": source, "seed": seed, "apple_xy_m": env.apple_xy, "start_pose": start_pose}
    status, reason, error = "complete", "finished", None
    try:
        yield env, details
    except BaseException as exc:
        status, reason, error = "partial", "interrupted", type(exc).__name__
        raise
    finally:
        env.close()
        frames = len(env.states)
        info = {
            "collection_mode": "simulation", "simulation": details,
            "robot_name": "YAM simulator", "body": "yam", "task": task,
            "checkpoint": checkpoint, "started_at_utc": started,
            "frames": frames, "fps": FPS, "duration_s": frames / FPS,
            "status": status if frames else "empty", "stop_reason": reason, "error": error,
        }
        pending = folder / "rollout.json.tmp"
        pending.write_text(json.dumps(info, indent=2), encoding="utf-8")
        pending.replace(folder / "rollout.json")
        print(f"Review {folder} (scene seed {seed})", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT)
    parser.add_argument("--episodes", type=int, default=2)
    parser.add_argument("--vary-approach", action="store_true",
                        help="Vary approach height, joint trajectory duration and descent duration by scene seed")
    parser.add_argument("--start-pose", choices=("home", "wrist-visible"), default="home")
    parser.add_argument("--seed", type=scene_seed, help="First scene seed; increments per episode")
    args = parser.parse_args()
    if args.episodes < 1:
        parser.error("--episodes must be positive")
    first_seed = args.seed if args.seed is not None else secrets.randbits(32)
    failures = 0
    for index in range(args.episodes):
        with recording(args.output, TASK, "scripted-yam", first_seed + index, "scripted", start_pose=args.start_pose) as (env, details):
            approach = {}
            if args.vary_approach:
                rng = np.random.default_rng([first_seed + index, 73])
                approach = dict(approach_steps=int(rng.integers(35, 91)),
                                descent_steps=int(rng.integers(38, 86)),
                                approach_height=float(rng.uniform(0.09, 0.155)))
                details["approach"] = approach
            result = mock_pickups.run_trial("apple", env=env, snapshot_dir=env.folder, **approach)
            details["script_result"] = result
            failures += int(not result["passed"])
            (env.folder / "embodiment.json").write_text(json.dumps(CONFIG), encoding="utf-8")
    if failures:
        raise SystemExit(f"{failures} scripted pickups failed the simulator check. Review before training.")
