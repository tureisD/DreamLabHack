import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from teach_task_coach.rollout_audit import audit_many, audit_rollout


def test_intent_audit_aligns_installed_chunks_and_ignores_discarded(tmp_path):
    folder = tmp_path / "episode"
    (folder / "chunks").mkdir(parents=True)
    (folder / "data").mkdir()
    (folder / "rollout.json").write_text(json.dumps({"status": "complete", "fps": 20}))
    events = [
        {"kind": "inference", "chunk": None, "discarded": "late"},
        {"kind": "inference", "chunk": 1, "discarded": None, "executed_since_obs": 2},
    ]
    (folder / "inference.jsonl").write_text("\n".join(json.dumps(value) for value in events))
    np.savez(folder / "chunks/reply_000000.npz", q_l_chunk=np.ones((2, 2)), q_r_chunk=np.ones((2, 2)))
    np.savez(folder / "chunks/reply_000001.npz", q_l_chunk=np.array([[1, 2], [3, 4]]), q_r_chunk=np.array([[5, 6], [7, 8]]))
    pq.write_table(pa.table({
        "action": pa.array([[1.0, 2, 5, 6], [3.0, 4, 7, 0]]),
        "rollout.chunk": pa.array([1, 1]), "rollout.row": pa.array([0, 1]),
    }), folder / "data/episode.parquet")
    report = audit_rollout(folder)
    assert report.command_rows == 2
    assert report.comparable_rows == 2
    assert report.differing_rows == 1
    assert report.differing_share == 0.5
    assert report.median_staleness_ms == 100
    assert report.discarded_replies == 1
    (tmp_path / "unfinished").mkdir()
    (tmp_path / "unfinished/INCOMPLETE.txt").write_text("interrupted")
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad/rollout.json").write_text("{")
    first = audit_many(tmp_path)
    second = audit_many(tmp_path)
    assert first.model_dump() == second.model_dump()
    assert first.processed == 1
    assert first.failed == 2
    assert first.differing_share == 0.5
