"""Resample Dream Labs YAM recordings from 20 Hz to FaaS-supported 10 Hz."""

import argparse
import json
from pathlib import Path

import av
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, default=Path.cwd() / "yam_sim_dataset_20hz")
parser.add_argument("--output", type=Path, default=Path.cwd() / "yam_sim_dataset_10hz")
args = parser.parse_args()
SOURCE = args.source.resolve()
TARGET = args.output.resolve()

if SOURCE == TARGET or TARGET.is_relative_to(SOURCE):
    parser.error("Choose a separate output directory outside the source")

for session in sorted(SOURCE.iterdir()):
    if not session.is_dir():
        continue
    output = TARGET / session.name
    info = json.loads((session / "meta/info.json").read_text(encoding="utf-8"))
    if info["fps"] != 20:
        parser.error(f"{session.name} is not a 20 Hz recording")
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error(f"Output session already exists: {output}. Choose a fresh output directory.")
    data = pq.read_table(session / "data/chunk-000/episode_000000.parquet")
    indices = np.arange(0, data.num_rows, 2)
    sampled = data.take(pa.array(indices))
    column = sampled.schema.get_field_index("timestamp")
    sampled = sampled.set_column(column, "timestamp", pa.array(np.arange(len(indices)) / 10))
    path = output / "data/chunk-000/episode_000000.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(sampled, path)

    for source_video in (session / "videos").rglob("*.mp4"):
        relative = source_video.relative_to(session)
        target_video = output / relative
        target_video.parent.mkdir(parents=True, exist_ok=True)
        with av.open(str(source_video)) as source, av.open(str(target_video), "w") as destination:
            stream = destination.add_stream("libx264", rate=10)
            stream.width, stream.height = 320, 176
            stream.pix_fmt = "yuv420p"
            stream.options = {"preset": "fast", "crf": "25"}
            for index, frame in enumerate(source.decode(video=0)):
                if index % 2:
                    continue
                for packet in stream.encode(frame):
                    destination.mux(packet)
            for packet in stream.encode():
                destination.mux(packet)

    meta = output / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    info["fps"] = 10
    info["total_frames"] = len(indices)
    (meta / "info.json").write_text(json.dumps(info), encoding="utf-8")
    (meta / "tasks.jsonl").write_bytes((session / "meta/tasks.jsonl").read_bytes())
    episode = json.loads((session / "meta/episodes.jsonl").read_text(encoding="utf-8"))
    episode["length"] = len(indices)
    (meta / "episodes.jsonl").write_text(json.dumps(episode) + "\n", encoding="utf-8")
    print(f"resampled {session.name}: {len(indices)} frames at 10 Hz")
