# Evaluation validation suite to implement

Replace `test_handoff.py` when the engine becomes functional; it intentionally
tests only the unavailable scaffold today. Do not mark numerical acceptance tests
as passing merely because an interface exists.

Suggested modules:

- `test_validation.py`: contaminated, duplicated, incomplete, unverified,
  mismatched, clustered, simulated and observational inputs.
- `test_fixed_horizon.py`: independent reference values and boundary cases,
  empty arms, all-zero/all-one, unequal counts, swapped checkpoint orientation.
- `test_sequential.py`: supported schedule and error control across every look,
  no decisions between looks, deterministic terminal-decision replay.
- `test_reporting.py`: complete attempt accounting, stable hashes, no NaN/inf,
  probabilities vs percentage points, export/reload identity.
- `test_operating_characteristics.py`: seeded Monte Carlo coverage, false-positive
  rate and power for each supported method; use the `statistical` marker.

Compare to independent reference calculations, not the exact same helper used by
the implementation. Set tolerances using Monte Carlo sampling uncertainty before
running simulations; do not pick a favorable seed or loosen thresholds until a
test passes. Record method version, seeds, replication count and assumptions.

Synthetic fixtures establish software behavior only, not robot efficacy.
