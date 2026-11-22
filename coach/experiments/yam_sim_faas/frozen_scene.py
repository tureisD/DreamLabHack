"""Content-addressed, pre-warmup YAM snapshots; entirely local, no model calls."""

import hashlib
import json
from pathlib import Path

import mujoco
import numpy as np
from yam_env import ASSETS, build_xml

SPEC = mujoco.mjtState.mjSTATE_INTEGRATION
ATOL = 1e-12


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def engine_key():
    h = hashlib.sha256(build_xml().replace(str(ASSETS), "<assets>").encode())
    for p in sorted(p for p in ASSETS.rglob("*") if p.is_file()):
        h.update(
            p.relative_to(ASSETS).as_posix().encode()
            + b"\0"
            + hashlib.sha256(p.read_bytes()).digest()
        )
    return h.hexdigest()


def state(env):
    a = np.empty(mujoco.mj_stateSize(env.model, SPEC), dtype=np.float64)
    mujoco.mj_getState(env.model, env.data, a, SPEC)
    return a


def freeze(root, env, *, task_id, instruction, rule, seed, pose, split, budget, warmup):
    if (
        split not in ("development", "heldout")
        or not task_id
        or not rule
        or budget < 1
        or warmup < 0
    ):
        raise ValueError("Missing protocol fields")
    root = Path(root)
    root.mkdir(exist_ok=True, parents=True)
    value = {
        "schema": "yam-replay-v1",
        "task_id": task_id,
        "instruction": instruction,
        "rule": rule,
        "rule_hash": digest([instruction, rule]),
        "seed": seed,
        "start_pose": pose,
        "split": split,
        "initial_apple_pose_world_m_wxyz": env.data.joint("apple_free").qpos.tolist(),
        "assets": engine_key(),
        "mujoco": mujoco.__version__,
        "integration_spec": int(SPEC),
        "snapshot": "before warmup; fresh camera history",
        "timestep": float(env.model.opt.timestep),
        "fps": 20,
        "warmup": warmup,
        "action_budget": budget,
        "integration": state(env).tolist(),
    }
    scene_id = digest(value)
    file = root / (scene_id + ".json")
    if file.exists():
        if digest(json.loads(file.read_text())) != scene_id:
            raise ValueError("Existing manifest changed")
    else:
        with file.open("x", encoding="utf-8") as f:
            json.dump(value, f, sort_keys=True, allow_nan=False)
    return file


def restore(file, env, *, seed, pose):
    file = Path(file)
    m = json.loads(file.read_text())
    reference = np.asarray(m["integration"], dtype=float)
    if digest(m) != file.stem or m["schema"] != "yam-replay-v1":
        raise ValueError("Manifest hash mismatch")
    if (
        m["assets"],
        m["mujoco"],
        m["integration_spec"],
        m["seed"],
        m["start_pose"],
        m["timestep"],
    ) != (engine_key(), mujoco.__version__, int(SPEC), seed, pose, float(env.model.opt.timestep)):
        raise ValueError("Simulator, assets, seed or pose mismatch")
    original = state(env)
    if original.shape != reference.shape or not np.allclose(original, reference, atol=ATOL, rtol=0):
        raise ValueError("Fresh simulator start state differs from frozen scene")
    mujoco.mj_setState(env.model, env.data, reference, SPEC)
    mujoco.mj_forward(env.model, env.data)
    actual = state(env)
    if not np.allclose(actual, reference, atol=ATOL, rtol=0):
        raise ValueError("Reset verification failed")
    return m
