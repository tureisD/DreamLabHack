"""Click-selected YAM task adapters: lift a fruit or place it in the bowl.

This is a simulator-only teacher. It converts a sparse object/goal selection to
joint-space actions, then checks physics before exporting a demonstration.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import secrets
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import mujoco
import numpy as np
import pyarrow.parquet as pq
from dream import datasets

SIM = Path(__file__).resolve().parents[3] / "dream_library/examples/yam_mujoco"
sys.path.insert(0, str(SIM))
from mock_pickups import solve
from record_yam_demos import CONFIG, YamEnv, recording
from resample_yam_demos import export_session

FRUITS = ("apple", "banana")
GOALS = ("lift", "bowl")
WIDTH, HEIGHT = 640, 360


@dataclass(frozen=True)
class Goal:
    kind: str
    fruit: str
    target_xy: tuple[float, float] | None = None

    @property
    def task_text(self) -> str:
        return (f"pick up the {self.fruit}" if self.kind == "lift"
                else f"put the {self.fruit} in the bowl")

    def validate(self) -> None:
        if self.kind not in GOALS or self.fruit not in FRUITS:
            raise ValueError("Unsupported YAM task or object.")
        if self.kind == "bowl":
            if self.fruit != "apple":
                raise ValueError("The bowl adapter currently supports apple only.")
            if self.target_xy is None or len(self.target_xy) != 2 or not all(
                math.isfinite(value) for value in self.target_xy
            ):
                raise ValueError("Bowl placement needs a finite clicked target.")
            if math.dist(self.target_xy, (0.0, -0.04)) > 0.025:
                raise ValueError("Click a point inside the bowl interior.")
        elif self.target_xy is not None:
            raise ValueError("Lift does not use a placement target.")


def project(env: YamEnv, point: np.ndarray, camera: str = "top") -> tuple[float, float]:
    """Project world position into the cropped 640x360 policy image."""
    index = env.model.camera(camera).id
    rotation = env.data.cam_xmat[index].reshape(3, 3)
    local = rotation.T @ (np.asarray(point) - env.data.cam_xpos[index])
    if local[2] >= 0:
        raise ValueError("Point is behind the simulator camera.")
    intrinsic = env.model.cam_intrinsic[index]
    sensor = env.model.cam_sensorsize[index]
    resolution = env.model.cam_resolution[index]
    focal = intrinsic[:2] / sensor * resolution
    principal = resolution / 2 + intrinsic[2:] / sensor * resolution
    return (float(principal[0] + focal[0] * local[0] / -local[2]),
            float(principal[1] - focal[1] * local[1] / -local[2] - 60))


def unproject(env: YamEnv, pixel: tuple[float, float], z: float,
              camera: str = "top") -> tuple[float, float]:
    index = env.model.camera(camera).id
    intrinsic = env.model.cam_intrinsic[index]
    sensor = env.model.cam_sensorsize[index]
    resolution = env.model.cam_resolution[index]
    focal = intrinsic[:2] / sensor * resolution
    principal = resolution / 2 + intrinsic[2:] / sensor * resolution
    direction_camera = np.array([(pixel[0] - principal[0]) / focal[0],
                                 -(pixel[1] + 60 - principal[1]) / focal[1], -1.0])
    direction = env.data.cam_xmat[index].reshape(3, 3) @ direction_camera
    origin = env.data.cam_xpos[index]
    if abs(direction[2]) < 1e-6:
        raise ValueError("Click ray is parallel to the target plane.")
    distance = (z - origin[2]) / direction[2]
    if distance <= 0:
        raise ValueError("Click ray does not reach the target plane.")
    hit = origin + distance * direction
    return float(hit[0]), float(hit[1])


def identify_fruit(env: YamEnv, pixel: tuple[float, float]) -> str:
    centers = {name: project(env, env.data.body(name).xpos) for name in FRUITS}
    selected = min(centers, key=lambda name: math.dist(pixel, centers[name]))
    if math.dist(pixel, centers[selected]) > 42:
        raise ValueError("Click the center of a visible fruit.")
    return selected


def scene_markers(env: YamEnv) -> dict[str, tuple[float, float]]:
    return {name: project(env, env.data.body(name).xpos) for name in (*FRUITS, "bowl")}


def seeded_env(fruit: str, seed: int) -> YamEnv:
    if fruit not in FRUITS or seed < 0 or seed > 2**32 - 1:
        raise ValueError("Choose a supported fruit and a 32-bit nonnegative scene seed.")
    env = YamEnv()
    env.data.joint(f"{fruit}_free").qpos[:2] += np.random.default_rng(seed).uniform(
        -0.025, 0.025, size=2
    )
    mujoco.mj_forward(env.model, env.data)
    return env


def goal_from_clicks(env: YamEnv, kind: str, fruit: str,
                     object_pixel: tuple[float, float],
                     target_pixel: tuple[float, float] | None = None) -> Goal:
    if not all(math.isfinite(value) and 0 <= value < limit for value, limit in
               zip(object_pixel, (WIDTH, HEIGHT), strict=True)):
        raise ValueError("Object click is outside the overhead image.")
    if identify_fruit(env, object_pixel) != fruit:
        raise ValueError("The object click does not match the selected fruit.")
    if kind == "bowl":
        if target_pixel is None or not all(math.isfinite(value) and 0 <= value < limit
                                            for value, limit in zip(target_pixel, (WIDTH, HEIGHT), strict=True)):
            raise ValueError("Click inside the bowl on the overhead image.")
        goal = Goal(kind, fruit, unproject(env, target_pixel, 0.80))
    else:
        if target_pixel is not None:
            raise ValueError("Lift needs an object click only.")
        goal = Goal(kind, fruit)
    goal.validate()
    return goal


def _rotation(yaw: float) -> np.ndarray:
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([[c, s, 0], [s, -c, 0], [0, 0, -1]])


def execute(env: YamEnv, goal: Goal, *, snapshot_dir: Path | None = None) -> dict:
    goal.validate()
    fruit = goal.fruit
    home = np.r_[np.zeros(6), 1.0]
    start = env.state()
    for _ in range(30):
        env.step(start["left"], start["right"])
    p = env.data.body(fruit).xpos.copy()
    initial_z = float(p[2])
    side = "left" if p[0] > 0 else "right"
    yaw = math.pi / 2 if fruit == "banana" else 0.0
    rotation = _rotation(yaw)
    q = env.state()[side][:6].copy()
    limits = env.model.jnt_range[[env.model.joint(f"{side}_joint{i}").id for i in range(1, 7)]]
    q = np.clip(q, limits[:, 0], limits[:, 1])

    def step(command: np.ndarray) -> None:
        env.step(command, home) if side == "left" else env.step(home, command)

    def move(target: np.ndarray, opening: float, steps: int) -> None:
        nonlocal q
        end = solve(env, side, np.asarray(target), rotation, q)
        begin = q.copy()
        for alpha in np.linspace(0, 1, steps):
            step(np.r_[begin + (end - begin) * alpha, opening])
        q = end

    approach_height = 0.10 if fruit == "orange" else 0.14
    move(p + [0, 0, approach_height], 1.0, 60)
    move(p + [0, 0, -0.009 if fruit == "orange" else 0.003], 1.0, 60)
    for opening in np.linspace(1, 0, 30):
        step(np.r_[q, opening])
    move(p + [0, 0, 0.12 if fruit == "orange" else 0.15], 0.0, 70)
    held_rises = []
    for _ in range(40):
        step(np.r_[q, 0.0])
        held_rises.append(float(env.data.body(fruit).xpos[2] - initial_z))
    held_lift = min(held_rises)
    if held_lift < 0.08:
        return {"passed": False, "stage": "grasp", "held_lift_m": held_lift}

    if goal.kind == "bowl":
        assert goal.target_xy is not None
        target = np.array([*goal.target_xy, 0.90])
        move(target, 0.0, 75)
        for _ in range(20):
            step(np.r_[q, 0.0])
        target = np.array([*goal.target_xy, 0.88])
        move(target, 0.0, 45)
    if snapshot_dir is not None:
        from PIL import Image

        snapshot_dir.mkdir(parents=True, exist_ok=True)
        Image.fromarray(env.images()["top"]).save(snapshot_dir / f"{fruit}-pre-release.png")
    for opening in np.linspace(0, 1, 35):
        step(np.r_[q, opening])
    for _ in range(60):
        step(np.r_[q, 1.0])
    final = env.data.body(fruit).xpos.copy()
    if goal.kind == "lift":
        passed = held_lift >= 0.08 and float(final[2]) < initial_z + 0.08
    else:
        passed = (math.dist(final[:2], goal.target_xy) < 0.05
                  and math.dist(final[:2], (0.0, -0.04)) < 0.045
                  and 0.77 < final[2] < 0.85)
    result = {"passed": bool(passed), "stage": "complete" if passed else "release",
              "held_lift_m": float(held_lift), "final_xyz_m": final.tolist(),
              "goal": {"kind": goal.kind, "fruit": fruit, "target_xy": goal.target_xy}}
    if snapshot_dir is not None:
        (snapshot_dir / "goal_check.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def replay_export(session: Path, goal: Goal, seed: int) -> dict:
    """Check that the downsampled action stream still achieves the physical goal."""
    rows = pq.read_table(session / "data/chunk-000/episode_000000.parquet", columns=["action"])
    actions = np.asarray(rows["action"].to_pylist(), dtype=np.float64)
    if actions.ndim != 2 or actions.shape[1] != 14 or not np.isfinite(actions).all():
        raise ValueError("Exported actions are not finite 14-value YAM controls.")
    env = seeded_env(goal.fruit, seed)
    try:
        initial_z = float(env.data.body(goal.fruit).xpos[2])
        heights = []
        for action in actions:
            for _ in range(2):
                env.step(action[7:], action[:7])
                heights.append(float(env.data.body(goal.fruit).xpos[2]))
        final = env.data.body(goal.fruit).xpos.copy()
        if goal.kind == "bowl":
            passed = (max(heights) - initial_z > 0.08
                      and math.dist(final[:2], (0.0, -0.04)) < 0.045
                      and 0.77 < final[2] < 0.85)
        else:
            passed = max(heights) - initial_z > 0.08 and final[2] < initial_z + 0.08
        if not passed:
            raise ValueError(f"Exported action replay failed the goal check: {final.tolist()}")
        return {"passed": True, "peak_lift_m": max(heights) - initial_z,
                "final_xyz_m": final.tolist()}
    finally:
        env.close()


def preview_scene(fruit: str, seed: int) -> dict:
    from PIL import Image

    env = seeded_env(fruit, seed)
    try:
        markers = scene_markers(env)
        image = Image.fromarray(env.images()["top"])
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
    finally:
        env.close()
    return {
        "image": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
        "width": WIDTH, "height": HEIGHT, "markers": markers,
        "supported": {"lift": ["apple", "banana"], "bowl": ["apple"]},
    }


def collect(output: Path, kind: str, fruit: str, seed: int,
            object_pixel: tuple[float, float],
            target_pixel: tuple[float, float] | None = None) -> dict:
    """Record, verify, resample, and atomically publish one reviewed simulator demo."""
    output = output.expanduser().resolve()
    with_seed = seeded_env(fruit, seed)
    try:
        goal = goal_from_clicks(with_seed, kind, fruit, object_pixel, target_pixel)
    finally:
        with_seed.close()
    output.mkdir(parents=True, exist_ok=True)
    name = f"yam-click-{kind}-{fruit}-{seed}-{uuid4().hex[:8]}"
    with TemporaryDirectory(dir=output.parent) as temporary:
        stage = Path(temporary)
        with recording(stage, goal.task_text, "scripted-yam", seed, "scripted-click",
                       object_name=fruit) as (env, details):
            details["clicks"] = {"object_px": object_pixel, "target_px": target_pixel}
            result = execute(env, goal)
            details["script_result"] = result
            (env.folder / "embodiment.json").write_text(json.dumps(CONFIG), encoding="utf-8")
        if not result["passed"]:
            raise ValueError(f"Simulator goal check failed: {result}")
        session = stage / name
        frames = export_session(env.folder, session)
        shutil.rmtree(env.folder)
        replay = replay_export(session, goal, seed)
        report = datasets.validate_dataset(str(stage), CONFIG)
        if not report.ok or report.episodes != 1:
            raise ValueError(f"Dream dataset validation failed: {report}")
        from teach_task_coach.demos import read_demo

        if not read_demo(session, "local-preview").valid:
            raise ValueError("The coach rejected the exported demonstration.")
        (session / "click_correction.json").write_text(json.dumps({
            "method": "click_to_correct_simulation", "seed": seed,
            "goal": {"kind": kind, "fruit": fruit, "target_xy_m": goal.target_xy},
            "clicks": {"object_px": object_pixel, "target_px": target_pixel},
            "physics": result, "export_replay": replay, "frames": frames, "fps": 10,
            "interpretation": "Simulator demonstration; no physical robot or model improvement claimed.",
        }, indent=2), encoding="utf-8")
        session.rename(output / name)
    return {"session_path": str(output / name), "task": goal.task_text,
            "frames": frames, "physics": result, "export_replay": replay}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--kind", choices=GOALS)
    parser.add_argument("--fruit", choices=FRUITS, required=True)
    parser.add_argument("--seed", type=int, default=secrets.randbits(32))
    parser.add_argument("--object-pixel", type=float, nargs=2, metavar=("X", "Y"))
    parser.add_argument("--target-pixel", type=float, nargs=2, metavar=("X", "Y"))
    parser.add_argument("--output", type=Path, default=Path(os.getenv("COACH_DEMOS_DIR", "yam_click_demos")))
    args = parser.parse_args()
    if args.preview:
        print(json.dumps(preview_scene(args.fruit, args.seed)))
        return
    if args.kind is None or args.object_pixel is None:
        parser.error("--kind and --object-pixel are required to record")
    result = collect(args.output, args.kind, args.fruit, args.seed,
                     tuple(args.object_pixel),
                     tuple(args.target_pixel) if args.target_pixel else None)
    print("CLICK_RESULT=" + json.dumps(result))


if __name__ == "__main__":
    main()
