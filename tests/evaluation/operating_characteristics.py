"""Synthetic finite-design audit. Run directly; public-engine parity is the default."""

import argparse
import json
from dataclasses import dataclass
from functools import lru_cache
from math import sqrt

import numpy as np
from scipy.stats import binom
from statsmodels.stats.proportion import confint_proportions_2indep, proportion_confint

from dreamlab.evaluation.methods.planning import fixed_horizon_power

REPS = 50_000
ALPHA = 0.05
LOOKS = (20, 40, 80, 120)
ENDPOINT_TOL = 2e-12


@dataclass(frozen=True)
class Case:
    name: str
    pb: float
    pc: float
    margin: float
    fixed_seed: int
    seq_seed: int | None
    n: int = 80


CASES = (
    Case("equal", 0.5, 0.5, 0, 5101, 6101),
    Case("margin", 0.375, 0.5, 0.125, 5102, 6102),
    Case("low-equal", 0.0625, 0.0625, 0, 5103, 6103),
    Case("large", 0.375, 0.875, 0.125, 5104, 6104),
    Case("regression", 0.875, 0.375, 0.125, 5105, 6105),
    Case("modest", 0.375, 0.625, 0.125, 5106, 6106),
    Case("zero", 0, 0, 0, 5107, 6107),
    Case("one", 1, 1, 0, 5108, 6108),
    Case("separation", 0, 1, 0.125, 5109, 6109),
    Case("tiny", 0.5, 0.5, 0, 5110, None, 1),
)


@dataclass(frozen=True)
class Bounds:
    arm_low: np.ndarray
    arm_high: np.ndarray
    low: np.ndarray
    high: np.ndarray


@lru_cache(maxsize=8)
def bounds(n, sequential):
    # Tables use the library's vectorized reference routines, not production
    # internals. Rows = baseline successes, columns = candidate successes.
    k = np.arange(n + 1)
    if sequential:
        al, ah = proportion_confint(k, n, alpha=ALPHA / (2 * len(LOOKS)), method="beta")
        low, high = al[None, :] - ah[:, None], ah[None, :] - al[:, None]
    else:
        al, ah = proportion_confint(k, n, alpha=ALPHA, method="wilson")
        low, high = confint_proportions_2indep(
            k[None, :], n, k[:, None], n, alpha=ALPHA, method="newcomb", compare="diff"
        )
    return Bounds(al, ah, low, high)


def look_events(case, low, high):
    gain = case.pc - case.pb
    improved, regressed = low > case.margin, high < 0
    false = (improved & (gain <= case.margin)) | (regressed & (gain >= 0))
    covered = (low <= gain) & (gain <= high)
    return improved, regressed, false, covered


def simulate(case, sequential):
    schedule = LOOKS if sequential else (case.n,)
    seed = case.seq_seed if sequential else case.fixed_seed
    rng = np.random.Generator(np.random.PCG64(seed))
    b = np.zeros(REPS, dtype=int)
    c = b.copy()
    stop = np.full(REPS, schedule[-1])
    im = np.zeros(REPS, dtype=bool)
    reg, ever_false, noncoverage = im.copy(), im.copy(), im.copy()
    # A small fixed subset of the *actual simulated* trajectories goes through
    # the public engine; deterministic boundary probes supplement these in parity.
    probes = []
    previous = 0
    for n in schedule:
        b += rng.binomial(n - previous, case.pb, REPS)
        c += rng.binomial(n - previous, case.pc, REPS)
        tab = bounds(n, sequential)
        improve, regress, false, cover = look_events(case, tab.low[b, c], tab.high[b, c])
        active = ~(im | reg)
        stop[active & (improve | regress)] = n
        im |= active & improve
        reg |= active & regress
        ever_false |= false
        noncoverage |= ~cover
        probes.append(np.stack((b[:12], c[:12]), axis=-1))
        previous = n
    gain = case.pc - case.pb
    stopped_false = (im & (gain <= case.margin)) | (reg & (gain >= 0))
    samples = dict(
        coverage=~noncoverage,
        any_false=ever_false,
        improved=im,
        regressed=reg,
        stopped_false=stopped_false,
        mean_n=stop,
    )
    return samples, np.stack(probes, axis=1)


def advance(mass, increment, pb, pc):
    """Exact finite-state recursion: convolve two independent block binomial PMFs."""
    k = np.arange(increment + 1)
    mid = np.apply_along_axis(np.convolve, 0, mass, binom.pmf(k, increment, pb))
    return np.apply_along_axis(np.convolve, 1, mid, binom.pmf(k, increment, pc))


def finite_reference(case, sequential):
    schedule = LOOKS if sequential else (case.n,)
    alive, covered, no_false = (np.ones((1, 1)) for _ in range(3))
    pi, pr, p_false, mean, second = 0.0, 0.0, 0.0, 0.0, 0.0
    prev = 0
    for n in schedule:
        tab = bounds(n, sequential)
        # Independent event masks for the deterministic mass recursion. Do not
        # reuse simulated first-stop/coverage/false-claim accumulators here.
        effect = case.pc - case.pb
        im, reg = tab.low > case.margin, tab.high < 0
        false = ((case.margin >= effect) & im) | ((0 <= effect) & reg)
        covers = ~((effect < tab.low) | (effect > tab.high))
        alive, covered, no_false = (
            advance(m, n - prev, case.pb, case.pc) for m in (alive, covered, no_false)
        )
        covered[~covers] = 0
        # Sum newly crossing mass directly: 1 - P(no false claim) loses
        # probabilities many orders of magnitude smaller than float epsilon.
        p_false += no_false[false].sum()
        no_false[false] = 0
        pi += alive[im].sum()
        pr += alive[reg].sum()
        stop_mass = alive.sum() if n == schedule[-1] else alive[im | reg].sum()
        mean += n * stop_mass
        second += n * n * stop_mass
        alive[im | reg] = 0
        prev = n
    assert abs(pi + pr + alive.sum() - 1) <= 2e-12
    gain = case.pc - case.pb
    out = dict(
        coverage=covered.sum(),
        any_false=p_false,
        improved=pi,
        regressed=pr,
        stopped_false=pi * (gain <= case.margin) + pr * (gain >= 0),
    )
    if not sequential:
        # Independent cutpoint/tail library planner vs. full count table PMF.
        planned = fixed_horizon_power(
            trials_per_arm=case.n,
            baseline_rate=case.pb,
            candidate_rate=case.pc,
            minimum_improvement=case.margin,
        )
        assert abs(planned - pi) <= 2e-12
    out = {k: float(np.clip(v, 0, 1)) for k, v in out.items()}
    out["mean_n"] = float(mean)
    return out, sqrt(max(0.0, second - mean * mean))


def validate_row(case, sequential, samples):
    ref, sd_n = finite_reference(case, sequential)
    metrics = {}
    for key, values in samples.items():
        q = ref[key]
        avg = float(values.mean())
        se = (
            float(values.std(ddof=1)) / sqrt(REPS)
            if key == "mean_n"
            else sqrt(avg * (1 - avg) / REPS)
        )
        expected_se = sd_n / sqrt(REPS) if key == "mean_n" else sqrt(q * (1 - q) / REPS)
        tolerance = 5 * expected_se + (LOOKS[-1] if key == "mean_n" else 1) / REPS
        assert abs(avg - q) <= tolerance, (case.name, sequential, key, avg, q, tolerance)
        metrics[key] = dict(estimate=avg, mc_se=se, finite_reference=q, tolerance=tolerance)
    assert ref["coverage"] >= (0.95 if sequential else 0.93) - 2e-12
    assert ref["any_false"] <= (0.05 if sequential else 0.07) + 2e-12
    assert ref["stopped_false"] <= ref["any_false"] + 2e-12
    if case.name == "margin":
        assert ref["improved"] <= 0.05
    if case.name == "large":
        assert ref["improved"] >= 0.85 and (not sequential or ref["mean_n"] < 110)
    if case.name == "regression":
        assert ref["regressed"] >= 0.85
    if case.name in {"zero", "one", "tiny"}:
        assert ref["improved"] == ref["regressed"] == 0
        if case.name != "tiny":
            assert ref["coverage"] == 1 and ref["mean_n"] == (LOOKS[-1] if sequential else case.n)
    if case.name == "separation":
        assert ref["improved"] == 1
    return metrics


def run_audit(*, public_parity=True):
    if not __debug__:
        raise RuntimeError("validation requires assertions; do not use python -O")
    engine = None
    methods = set()
    checked = 0
    if public_parity:
        from public_engine_parity import audit_paths, boundary_probes, plan_for

        from dreamlab.evaluation.engine import StatisticalEvaluator

        engine = StatisticalEvaluator()
        checked += boundary_probes(engine, methods, LOOKS, ALPHA, bounds, ENDPOINT_TOL)
    rows = []
    for case in CASES:
        for seq in [False, True] if case.seq_seed is not None else [False]:
            samples, probes = simulate(case, seq)
            if public_parity:
                schedule = LOOKS if seq else (case.n,)
                plan = plan_for(schedule, case.margin, ALPHA, seq)
                checked += audit_paths(
                    engine, methods, plan, schedule, probes, bounds, ENDPOINT_TOL
                )
            rows.append(
                dict(
                    case=case.name,
                    mode="sequential" if seq else "fixed",
                    seed=case.seq_seed if seq else case.fixed_seed,
                    baseline_rate=case.pb,
                    candidate_rate=case.pc,
                    margin=case.margin,
                    schedule=LOOKS if seq else (case.n,),
                    metrics=validate_row(case, seq, samples),
                )
            )
    return dict(
        status="public-engine-parity" if public_parity else "REFERENCE ONLY, NO ENGINE",
        replications_per_row=REPS,
        alpha=ALPHA,
        looks=LOOKS,
        rows=rows,
        public_reports_checked=checked,
        engine_methods=sorted(methods),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference-only",
        action="store_true",
        help="Run finite-law and MC checks only; NOT engine validation.",
    )
    args = parser.parse_args()
    print(json.dumps(run_audit(public_parity=not args.reference_only), indent=2, allow_nan=False))
