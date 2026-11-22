import json

import numpy as np

from teach_task_coach.consistency import calibrate_successes, score_rollout


def test_consistency_aligns_overlapping_chunks_and_ignores_discarded(tmp_path):
    folder = tmp_path / "run"
    (folder / "chunks").mkdir(parents=True)
    events = [
        {"kind": "inference", "chunk": 1, "executed_since_obs": 0},
        {"kind": "inference", "discarded": "late"},
        {"kind": "inference", "chunk": 2, "executed_since_obs": 1},
    ]
    (folder / "inference.jsonl").write_text("\n".join(json.dumps(item) for item in events))
    np.savez(folder / "chunks/reply_000000.npz", q_l_chunk=[[0], [1], [2]], q_r_chunk=[[0], [1], [2]])
    np.savez(folder / "chunks/reply_000001.npz", q_l_chunk=[[99], [99], [99]], q_r_chunk=[[99], [99], [99]])
    np.savez(folder / "chunks/reply_000002.npz", q_l_chunk=[[1], [2], [3]], q_r_chunk=[[1], [2], [3]])
    result = score_rollout(folder)
    assert result.comparisons == 1
    assert result.score == 0
    assert calibrate_successes([folder] * 9) is None
    assert calibrate_successes([folder] * 10) == 0
