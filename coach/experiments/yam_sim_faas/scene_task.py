"""Generate a new YAM pick-and-place task from a declarative scene JSON file.

No task-specific Python or physical robot is required. MuJoCo provides the
physics, while the JSON supplies object geometry, target, prompt and goal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import xml.etree.ElementTree as ET
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
from click_to_correct import project
from mock_pickups import solve
from record_yam_demos import CONFIG, recording
from resample_yam_demos import export_session
from yam_env import YamEnv, build_xml

TABLE_TOP = 0.76
SCENE_BODIES = {"apple", "banana", "orange", "water_bottle", "bowl", "plate"}
SHAPES = {"box": 3, "sphere": 1, "cylinder": 2}


def _finite_vector(value: object, length: int, label: str) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != length or any(
        not isinstance(item, (int, float)) or not math.isfinite(item) for item in value
    ):
        raise ValueError(f"{label} needs {length} finite numbers.")
    return tuple(float(item) for item in value)


def _color(value: object, label: str) -> tuple[float, ...]:
    color = _finite_vector(value, 4, label)
    if any(not 0 <= component <= 1 for component in color):
        raise ValueError(f"{label} components must be between zero and one.")
    return color


def _numbers(values: tuple[float, ...] | list[float]) -> str:
    return " ".join(f"{number:.8g}" for number in values)


@dataclass(frozen=True)
class TaskSpec:
    prompt: str
    object_label: str
    shape: str
    size: tuple[float, ...]
    mass: float
    object_color: tuple[float, ...]
    start_xy: tuple[float, float]
    target_label: str
    target_xy: tuple[float, float]
    target_radius: float
    target_color: tuple[float, ...]

    @classmethod
    def from_dict(cls, value: dict) -> TaskSpec:
        if set(value) != {"prompt", "object", "target", "goal"}:
            raise ValueError("Scene needs prompt, object, target, and goal fields only.")
        obj, target, goal = value["object"], value["target"], value["goal"]
        if not all(isinstance(item, dict) for item in (obj, target, goal)):
            raise ValueError("Object, target, and goal must be JSON objects.")
        if set(obj) != {"label", "shape", "size", "mass", "color", "start_xy"}:
            raise ValueError("Object fields: label, shape, size, mass, color, start_xy.")
        if set(target) != {"label", "xy", "radius", "color"}:
            raise ValueError("Target fields: label, xy, radius, color.")
        if goal != {"type": "place_on_target"}:
            raise ValueError("This proof of concept supports the place_on_target goal only.")
        prompt = value["prompt"]
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 200:
            raise ValueError("Prompt must contain 1–200 characters.")
        for label in (obj["label"], target["label"]):
            if not isinstance(label, str) or not label.strip() or len(label) > 60:
                raise ValueError("Object and target labels must contain 1–60 characters.")
        shape = obj["shape"]
        if shape not in SHAPES:
            raise ValueError("Supported object shapes: box, sphere, cylinder.")
        size = _finite_vector(obj["size"], SHAPES[shape], "object.size")
        if any(not 0.015 <= dimension <= 0.05 for dimension in size):
            raise ValueError("Object half-sizes/radius must be 1.5–5 cm for this gripper.")
        mass = float(obj["mass"])
        radius = float(target["radius"])
        if not math.isfinite(mass) or not 0.02 <= mass <= 0.25:
            raise ValueError("Object mass must be 0.02–0.25 kg.")
        if not math.isfinite(radius) or not 0.04 <= radius <= 0.09:
            raise ValueError("Target radius must be 4–9 cm.")
        start_xy = _finite_vector(obj["start_xy"], 2, "object.start_xy")
        target_xy = _finite_vector(target["xy"], 2, "target.xy")
        for xy in (start_xy, target_xy):
            if not -0.4 <= xy[0] <= 0.4 or not -0.35 <= xy[1] <= 0.20:
                raise ValueError("Object and target must stay on the YAM tabletop.")
        if math.dist(start_xy, target_xy) < 0.09:
            raise ValueError("Start and target need at least 9 cm separation.")
        return cls(prompt.strip(), obj["label"].strip(), shape, size, mass,
                   _color(obj["color"], "object.color"), start_xy,
                   target["label"].strip(), target_xy, radius,
                   _color(target["color"], "target.color"))

    @classmethod
    def from_file(cls, path: Path) -> TaskSpec:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    @property
    def half_height(self) -> float:
        return self.size[2] if self.shape == "box" else self.size[0] if self.shape == "sphere" else self.size[1]

    def as_dict(self) -> dict:
        return {
            "prompt": self.prompt,
            "object": {"label": self.object_label, "shape": self.shape, "size": self.size,
                       "mass": self.mass, "color": self.object_color, "start_xy": self.start_xy},
            "target": {"label": self.target_label, "xy": self.target_xy,
                       "radius": self.target_radius, "color": self.target_color},
            "goal": {"type": "place_on_target"},
        }


def scene_xml(spec: TaskSpec) -> str:
    root = ET.fromstring(build_xml())
    world = root.find("worldbody")
    assert world is not None
    for body in list(world):
        if body.tag == "body" and body.get("name") in SCENE_BODIES:
            world.remove(body)
    z = TABLE_TOP + spec.half_height + 0.002
    obj = ET.SubElement(world, "body", name="task_object", pos=_numbers([*spec.start_xy, z]))
    ET.SubElement(obj, "freejoint", name="task_object_free")
    ET.SubElement(obj, "geom", type=spec.shape, size=_numbers(spec.size),
                  mass=str(spec.mass), rgba=_numbers(spec.object_color),
                  friction="6 .08 .008", condim="6", priority="1")
    marker = ET.SubElement(world, "body", name="task_target", pos=_numbers([*spec.target_xy, TABLE_TOP + 0.002]))
    ET.SubElement(marker, "geom", type="cylinder", size=_numbers([spec.target_radius, 0.0015]),
                  rgba=_numbers(spec.target_color), contype="0", conaffinity="0", mass="0")
    return ET.tostring(root, encoding="unicode")


def make_env(spec: TaskSpec, seed: int) -> YamEnv:
    if not 0 <= seed <= 2**32 - 1:
        raise ValueError("Scene seed must be a nonnegative 32-bit integer.")
    env = YamEnv(scene_xml=scene_xml(spec))
    env.data.joint("task_object_free").qpos[:2] += np.random.default_rng(seed).uniform(
        -0.025, 0.025, size=2
    )
    mujoco.mj_forward(env.model, env.data)
    return env


def score(env: YamEnv, spec: TaskSpec, initial_z: float, peak_z: float) -> dict:
    final = env.data.body("task_object").xpos.copy()
    xy_error = math.dist(final[:2], spec.target_xy)
    passed = (peak_z - initial_z >= 0.08 and xy_error <= spec.target_radius
              and abs(final[2] - initial_z) <= 0.035)
    return {"passed": bool(passed), "peak_lift_m": float(peak_z - initial_z),
            "target_error_m": float(xy_error), "final_xyz_m": final.tolist()}


def execute(env: YamEnv, spec: TaskSpec) -> dict:
    home = np.r_[np.zeros(6), 1.0]
    start = env.state()
    for _ in range(30):
        env.step(start["left"], start["right"])
    p = env.data.body("task_object").xpos.copy()
    initial_z = float(p[2])
    side = "left" if p[0] >= 0 else "right"
    rotation = np.diag([1.0, -1.0, -1.0])
    q = env.state()[side][:6].copy()

    def step(command: np.ndarray) -> None:
        env.step(command, home) if side == "left" else env.step(home, command)

    def move(target: np.ndarray, opening: float, steps: int) -> None:
        nonlocal q
        end = solve(env, side, target, rotation, q)
        begin = q.copy()
        for alpha in np.linspace(0, 1, steps):
            step(np.r_[begin + (end - begin) * alpha, opening])
        q = end

    move(p + [0, 0, 0.14], 1.0, 60)
    move(p + [0, 0, 0.002], 1.0, 60)
    for opening in np.linspace(1, 0, 30):
        step(np.r_[q, opening])
    move(p + [0, 0, 0.15], 0.0, 70)
    heights = []
    for _ in range(40):
        step(np.r_[q, 0.0])
        heights.append(float(env.data.body("task_object").xpos[2]))
    peak_z = max(heights)
    if min(heights) - initial_z < 0.08:
        return {"passed": False, "stage": "grasp", "held_lift_m": min(heights) - initial_z}
    move(np.array([*spec.target_xy, 0.90]), 0.0, 75)
    move(np.array([*spec.target_xy, initial_z + 0.035]), 0.0, 45)
    for opening in np.linspace(0, 1, 35):
        step(np.r_[q, opening])
    for _ in range(65):
        step(np.r_[q, 1.0])
        peak_z = max(peak_z, float(env.data.body("task_object").xpos[2]))
    return {"stage": "complete", "held_lift_m": min(heights) - initial_z,
            **score(env, spec, initial_z, peak_z)}


def replay_export(session: Path, spec: TaskSpec, seed: int) -> dict:
    rows = pq.read_table(session / "data/chunk-000/episode_000000.parquet", columns=["action"])
    actions = np.asarray(rows["action"].to_pylist(), dtype=float)
    if actions.ndim != 2 or actions.shape[1] != 14 or not np.isfinite(actions).all():
        raise ValueError("Exported actions are not finite YAM joint controls.")
    env = make_env(spec, seed)
    try:
        initial_z = float(env.data.body("task_object").xpos[2])
        peak_z = initial_z
        for action in actions:
            for _ in range(2):
                env.step(action[7:], action[:7])
                peak_z = max(peak_z, float(env.data.body("task_object").xpos[2]))
        result = score(env, spec, initial_z, peak_z)
        if not result["passed"]:
            raise ValueError(f"Exported action replay failed: {result}")
        return result
    finally:
        env.close()


def preview(spec: TaskSpec, seed: int, image_path: Path) -> dict:
    from PIL import Image

    env = make_env(spec, seed)
    try:
        image_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(env.images()["top"]).save(image_path)
        return {"image": str(image_path.resolve()), "object_xy_m": env.data.body("task_object").xpos[:2].tolist(),
                "target_xy_m": spec.target_xy, "prompt": spec.prompt,
                "markers": {"object": project(env, env.data.body("task_object").xpos),
                            "target": project(env, env.data.body("task_target").xpos)}}
    finally:
        env.close()


def collect(spec: TaskSpec, seed: int, output: Path) -> dict:
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    name = f"yam-scene-task-{seed}-{uuid4().hex[:8]}"
    xml = scene_xml(spec)
    digest = hashlib.sha256(json.dumps(spec.as_dict(), sort_keys=True).encode()).hexdigest()
    with TemporaryDirectory(dir=output.parent) as temporary:
        stage = Path(temporary)
        with recording(stage, spec.prompt, "scripted-yam", seed, "scene-task",
                       object_name="task_object", scene_xml=xml) as (env, details):
            details["scene_spec_sha256"] = digest
            result = execute(env, spec)
            details["script_result"] = result
            (env.folder / "embodiment.json").write_text(json.dumps(CONFIG), encoding="utf-8")
        if not result["passed"]:
            raise ValueError(f"The new task failed in simulation: {result}")
        session = stage / name
        frames = export_session(env.folder, session)
        shutil.rmtree(env.folder)
        replay = replay_export(session, spec, seed)
        report = datasets.validate_dataset(str(stage), CONFIG)
        if not report.ok or report.episodes != 1:
            raise ValueError(f"Dream dataset validation failed: {report}")
        from teach_task_coach.demos import read_demo

        if not read_demo(session, "local-preview").valid:
            raise ValueError("Coach rejected the new task demonstration.")
        (session / "scene_task.json").write_text(json.dumps({
            "method": "declarative_scene_task", "spec": spec.as_dict(), "spec_sha256": digest,
            "seed": seed, "physics": result, "export_replay": replay,
            "interpretation": "Simulator demonstration; held-out model evaluation is still required.",
        }, indent=2), encoding="utf-8")
        session.rename(output / name)
    return {"session_path": str(output / name), "prompt": spec.prompt,
            "frames": frames, "physics": result, "export_replay": replay,
            "spec_sha256": digest}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--preview", type=Path, metavar="PNG")
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("yam_scene_task_demos"))
    args = parser.parse_args()
    if not args.preview and not args.collect:
        parser.error("Use --preview PNG or --collect.")
    spec = TaskSpec.from_file(args.spec)
    if args.preview:
        print(json.dumps(preview(spec, args.seed, args.preview), indent=2))
    if args.collect:
        print("SCENE_RESULT=" + json.dumps(collect(spec, args.seed, args.output)))


if __name__ == "__main__":
    main()
