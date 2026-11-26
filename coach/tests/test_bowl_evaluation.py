from pathlib import Path

import pytest

from teach_task_coach.yam_goals import BOWL_PROMPT

SCRIPTS = Path(__file__).resolve().parents[1] / "experiments/yam_sim_faas"


def test_bowl_evaluation_scores_a_real_scripted_release(tmp_path, monkeypatch):
    pytest.importorskip("mujoco")
    monkeypatch.syspath_prepend(str(SCRIPTS))
    monkeypatch.syspath_prepend(str(SCRIPTS / "grasp_training"))
    from click_to_correct import Goal, execute
    from record_yam_demos import recording
    from score_rollouts import score
    from score_workflow_rollout import score_trial

    seed = 2**31 + 41
    with recording(tmp_path, BOWL_PROMPT, "fixture/bowl", seed, "model", videos=False) as (env, details):
        result = execute(env, Goal("bowl", "apple", (0.0, -0.04)))
        assert result["passed"]
        while len(env.actions) < 609:
            state = env.state()
            env.step(state["left"], state["right"])
        details.update(model_action_rows=576, split="heldout")
    result = score_trial(tmp_path, seed, diagnose=True)
    assert result["success"]
    assert result["task"] == BOWL_PROMPT and result["started_at"]
    assert result["bowl_placement"]["settled_s"] >= 1
    assert result["diagnosis"]["code"] == "bowl_placed"
    with pytest.raises(ValueError, match="not an eligible"):
        score(env.folder, training_candidate=True)


@pytest.mark.parametrize(
    ("last_sample", "expected"),
    [
        ([0.02, 0.05, 0.0, 1, 0], "bowl_placed"),
        ([0.02, 0.05, 0.0, 1, 1], "bowl_unreleased"),
        ([0.02, 0.05, 0.2, 1, 0], "bowl_unsettled"),
        ([0.10, 0.05, 0.0, 0, 0], "bowl_outside"),
    ],
)
def test_bowl_evaluation_requires_a_released_settled_apple(monkeypatch, last_sample, expected):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    from bowl_evidence import evaluate_placement

    samples = [[0.02, 0.05, 0.0, 1, 0]] * 20 + [last_sample]
    result = evaluate_placement(samples, 0.12, 20)
    assert result["success"] == (expected == "bowl_placed")
    assert result["diagnosis"]["code"] == expected
