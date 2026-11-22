"""Incremental accounting and eligibility checks in the submitted trial order."""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from posixpath import normpath
from urllib.parse import unquote, urlsplit

from dreamlab.contracts import EvaluationPlan, Trial

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def _source_key(source: str) -> tuple[str, str, str, str]:
    """Lexical checks only. URI fragments do not establish independent footage."""
    scheme = _URI_SCHEME.match(source)
    # A bare path (including a Windows drive path) is not URI-escaped; '?' and
    # '#' can be literal filename characters, so don't pass it through urlsplit.
    # Do not mistake opaque application URIs such as `s3:bucket/key` for paths.
    drive_path = (
        len(source) >= 3 and source[0].isalpha() and source[1] == ":" and source[2] in "/\\"
    )
    if scheme is None or drive_path:
        if not source.strip():
            raise ValueError("Missing source location")
        return "file", "", normpath(source), ""
    uri = urlsplit(source)
    if not (uri.netloc or uri.path):
        raise ValueError("Missing source location")
    if uri.scheme == "file" and uri.netloc.lower() in {"", "localhost"}:
        return "file", "", normpath(unquote(uri.path, errors="strict")), ""
    authority = uri.netloc
    if uri.scheme in {"https", "http"}:
        if not uri.hostname:
            raise ValueError("Missing source host")
        userinfo, sep, _ = authority.rpartition("@")
        host = uri.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        port = uri.port
        standard_port = 443 if uri.scheme == "https" else 80
        authority = (
            userinfo + sep + host + (f":{port}" if port not in {None, standard_port} else "")
        )
        return uri.scheme, authority, uri.path or "/", uri.query
    # Object keys and application-specific authorities/queries can be case sensitive.
    return uri.scheme, authority, uri.path, uri.query


@dataclass(slots=True)
class Counts:
    attempted: int = 0
    outcomes: Counter[str] = field(default_factory=Counter)
    scenarios: Counter[str] = field(default_factory=Counter)

    def record(self, trial: Trial) -> None:
        self.attempted += 1
        self.outcomes[trial.outcome] += 1
        self.scenarios[trial.scenario_id] += 1


class Evidence:
    """Transport validation handles membership and trial/episode identity, not eligibility."""

    def __init__(self, plan: EvaluationPlan):
        self.plan = plan
        self.baseline = Counts()
        self.candidate = Counts()
        self.problems: set[str] = set()
        self.sessions: set[str] = set()
        self.sources: set[tuple[str, str, str, str]] = set()
        self.plan_time = plan.created_at - _EPOCH
        self.previous_time = None
        self.temporal_error = False
        if plan.design != "independent":
            self.problems.add(f"Unsupported {plan.design} design; independent trials are required.")
        if len(plan.scenario_ids) != 1:
            self.problems.add(
                "V1 inference supports one fixed scenario only; pooled multi-scenario "
                "intervals do not account for scenario heterogeneity."
            )

    def record(self, trial: Trial, *, post_stop: bool = False) -> None:
        if trial.checkpoint_id == self.plan.baseline_checkpoint:
            self.baseline.record(trial)
        else:
            self.candidate.record(trial)
        # Check chronology over the entire supplied snapshot, including rows
        # after a recorded terminal look. A mislabeled post-stop row may be
        # ignored, but an earlier timestamp must not be passed off as later.
        instant = trial.recorded_at - _EPOCH
        if instant <= self.plan_time:
            self.temporal_error = True
            self.problems.add("The plan must be created strictly before every attempt.")
        if self.previous_time is not None and instant < self.previous_time:
            self.temporal_error = True
            self.problems.add("Trial timestamps go backwards in the submitted order.")
        self.previous_time = instant

        if post_stop:
            return

        if trial.collection_mode != "prospective":
            self.problems.add(f"Only prospective trials qualify; found {trial.collection_mode}.")
        if trial.training_exposure != "held_out":
            self.problems.add(
                f"Training exposure must be held_out; found {trial.training_exposure}."
            )
        if trial.outcome not in {"success", "failure"}:
            self.problems.add(f"An {trial.outcome} outcome cannot be dropped or replaced.")
        if not trial.human_verified or not trial.reviewer_id:
            self.problems.add("All outcomes must be human-verified with a reviewer.")
        if trial.pair_id is not None:
            self.problems.add("Pair IDs indicate paired attempts; this method is independent only.")
        if trial.session_id in self.sessions:
            self.problems.add("Repeated session IDs indicate possible clustering.")
        self.sessions.add(trial.session_id)
        try:
            source = _source_key(trial.source_uri)
        except ValueError:
            self.problems.add("A source URI cannot identify an auditable source.")
        else:
            if source in self.sources:
                self.problems.add("Duplicate source URI: re-imported footage is not independent.")
            self.sources.add(source)

    def check_scenarios(self) -> None:
        # v1 has no weights or stratified estimator for a different mix across arms.
        if self.baseline.scenarios != self.candidate.scenarios:
            self.problems.add(
                "Different scenario counts across checkpoints can confound the effect."
            )
        if len(self.baseline.scenarios.keys() & self.candidate.scenarios.keys()) != len(
            self.plan.scenario_ids
        ):
            self.problems.add(
                "Not every planned scenario is represented in both arms at this look."
            )
