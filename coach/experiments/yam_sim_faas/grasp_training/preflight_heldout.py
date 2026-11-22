"""Compare the actual camera warm-ups and state recordings before a paid simulator evaluation."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import av
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import record_dream_model_rollout as pilot
from teach_task_coach.episodes import read_episode


def camera_digest(path, expected_rows, fps):
    digest = hashlib.sha256()
    count = 0
    with av.open(path) as stream:
        for i, frame in enumerate(stream.decode(video=0)):
            if frame.time is None or abs(float(frame.time) - i / fps) > 1e-6:
                raise ValueError(f"Camera timestamp mismatch in {path} at frame {i}")
            digest.update(frame.to_ndarray(format="rgb24").tobytes())
            count += 1
    if count != expected_rows:
        raise ValueError(f"Expected {expected_rows} frames in {path}, decoded {count}")
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory for eight offline recordings and their report")
    args = parser.parse_args()
    manifests = sorted((HERE / "held_out").glob("*.json"))
    seeds = [json.loads(path.read_text())["seed"] for path in manifests]
    if sorted(seeds) != [901, 902, 903, 904]:
        raise ValueError("Expected one frozen scene for each held-out seed 901 through 904")
    candidate = json.loads((HERE / "varied-checkpoint.json").read_text())["checkpoint"]
    args.output.mkdir(parents=True, exist_ok=False)
    comparisons = []
    for seed, manifest in sorted(zip(seeds, manifests)):
        tables, cameras, runs = [], [], {}
        for role, checkpoint in (("base", pilot.dream_control.BETA_MODEL), ("candidate", candidate)):
            dest = args.output / str(seed) / role
            pilot.main(["--held-out-scene", str(manifest), "--model", checkpoint, "--dry-run", "--output", str(dest)])
            folder, = dest.glob("yam-*")
            run = read_episode(folder)
            sim = run.simulation
            if not (
                run.status == "complete" and sim["scene_id"] == manifest.stem and run.checkpoint == checkpoint
                and sim["source"] == "observation dry run" and sim["requests_attempted"] == sim["model_action_rows"] == 0
                and sim["warmup_rows"] == run.frames == 33 and run.fps == 20
                and run.pickup_evidence.observation == "no_actions" and run.success is None
                and set(run.videos) == {"overhead", "wrist_l", "wrist_r"}
            ):
                raise ValueError(f"Invalid offline recording at {folder}")
            table = pq.read_table(next(folder.rglob("*.parquet")))
            if table.num_rows != run.frames:
                raise ValueError(f"State row count does not match video at {folder}")
            tables.append(table)
            cameras.append({k: camera_digest(v, run.frames, run.fps) for k, v in run.videos.items()})
            runs[role] = str(folder.relative_to(args.output).as_posix())
        if cameras[0] != cameras[1] or not tables[0].equals(tables[1]):
            raise ValueError(f"Paired starting observations differ for seed {seed}")
        comparisons.append({"seed": seed, "scene_id": manifest.stem, "recordings": runs, "camera_sha256": cameras[0]})
    report = {"status": "passed", "kind": "offline camera and state preflight", "model_calls": 0, "scenes": comparisons}
    path = args.output / "report.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Four matched scene pairs verified. Report: {path}")


if __name__ == "__main__":
    main()
