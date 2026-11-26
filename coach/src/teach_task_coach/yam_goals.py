"""Task and versioned scoring rules for the supported YAM evaluations."""

BOWL_PROMPT = "put the apple in the bowl"
BOWL_TASK_RULE = "Lift the apple, release it into the bowl, and leave it resting inside."
BOWL_EVALUATION_RULE = (
    "Lift the apple at least 8 cm, then release it so it rests inside the bowl "
    "without gripper contact for the final second."
)
BOWL_LIFT_M = 0.08
BOWL_SETTLE_SECONDS = 1.0
BOWL_RADIUS_M = 0.045
BOWL_HEIGHT_M = (0.01, 0.09)
BOWL_SPEED_M_S = 0.03
