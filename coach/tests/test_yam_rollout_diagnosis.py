from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

SCORER = Path(__file__).resolve().parents[1] / "experiments/yam_sim_faas/grasp_training/rollout_diagnosis.py"
spec = spec_from_file_location("rollout_diagnosis", SCORER)
assert spec is not None and spec.loader is not None
diagnosis = module_from_spec(spec)
spec.loader.exec_module(diagnosis)


@pytest.fixture
def trace():
    count = 33 + 48 * 12
    actions = np.ones((count, 14))
    rise = np.zeros(count)
    replay = SimpleNamespace(gaps=np.full((count, 2), 0.15), contacts=np.zeros((count, 2)))
    return actions, rise, replay


def test_distinguishes_close_outside_grasp_from_a_contact_without_lift(trace):
    actions, rise, replay = trace
    actions[46:, 13] = 0.2
    missed = diagnosis.diagnose_rollout(actions, rise, replay, "recorded")
    assert missed["code"] == "close_outside_grasp"
    assert "left gripper at 0.65 s, 15.0 cm from the apple center" in missed["evidence"][2]

    actions[72:, 6] = 0.2
    replay.gaps[72:, 0] = 0.015
    replay.contacts[90:121, 0] = 2
    touched = diagnosis.diagnose_rollout(actions, rise, replay, "recorded")
    assert touched["code"] == "contact_without_lift"
    assert "right gripper" in touched["evidence"][2]


def test_transient_lift_and_trial_ending_during_lift_have_different_diagnoses(trace):
    actions, rise, replay = trace
    rise[88:104] = 0.09
    dropped = diagnosis.diagnose_rollout(actions, rise, replay, "recorded")
    assert dropped["code"] == "short_hold"
    assert "0.75 s" in dropped["evidence"][2]

    rise[-9:] = 0.10
    ended = diagnosis.diagnose_rollout(actions, rise, replay, "recorded")
    assert ended["code"] == "hold_cut_short"


def test_reports_a_pass_only_reached_within_the_extended_rollout(trace):
    actions, rise, replay = trace
    rise[440:] = 0.09
    result = diagnosis.diagnose_rollout(actions, rise, replay, "recorded")
    assert result["code"] == "extended_rollout_pass"
    assert "After 9 requests" in result["evidence"][2]
    assert "during request 10" in result["evidence"][3]
