"""Round trip the standalone evaluator and exercise its failure boundaries."""

import errno
import io
import json
import os
import re
import shutil
import subprocess
import sys
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from threading import Event, Thread

import pytest
from eval_cases import FIXTURE, assert_refused, assert_snapshot, make_payload
from interval_reference import newcombe_difference

import dreamlab
from dreamlab.contracts import EvaluationReport, EvaluationRequest, EvaluationUnavailable
from dreamlab.evaluation import artifacts, cli
from dreamlab.evaluation.engine import StatisticalEvaluator

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="CLI publication is Linux-only")

REPORT = Path(__file__).parent / "examples" / "evaluation_report.json"
SUCCESS_FILES = {"request.raw.json", "request.json", "report.json", "summary.txt", "manifest.json"}
FAILURE_FILES = {"request.raw.json", "request.json", "diagnostics.json"}


def _command(input_path, output):
    return ["evaluate", "--input", str(input_path), "--output-dir", str(output)]


def _contents(path):
    return {child.name for child in path.iterdir()}


def _json(path):
    return json.loads(path.read_bytes())


def _report(output):
    return EvaluationReport.model_validate_json((output / "report.json").read_bytes())


def _diagnostics(output, status, code, stage, files=FAILURE_FILES):
    assert _contents(output) == files
    diagnostics = _json(output / "diagnostics.json")
    assert diagnostics["schema_version"] == 1
    assert diagnostics["exit_code"] == status
    assert diagnostics["code"] == code
    assert diagnostics["stage"] == stage
    assert diagnostics["message"]
    return diagnostics["details"]


def _submit(tmp_path, payload, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw = json.dumps(payload, ensure_ascii=False, indent=2).replace("\n", "\r\n").encode()
    source = Path("input.json")
    source.write_bytes(raw)
    output = Path("run")
    status = cli.main(_command(source, output))
    assert source.read_bytes() == raw
    assert (output / "request.raw.json").read_bytes() == raw
    assert _contents(tmp_path) == {"run", "input.json"}
    return output, status


def test_evaluate_round_trips_exact_input_canonical_request_and_report(tmp_path, monkeypatch):
    payload = make_payload("1" * 10 + "0" * 20, "1" * 19 + "0" * 11, budget=30, margin=0.04)
    payload["trials"][0]["reviewer_id"] = "réviseur-1"
    del payload["plan"]["alpha"]  # The canonical snapshot includes effective defaults.
    output, status = _submit(tmp_path, payload, monkeypatch)
    assert status == 0
    assert _contents(output) == SUCCESS_FILES
    request = EvaluationRequest.model_validate(payload)
    canonical = (output / "request.json").read_bytes()
    assert request == EvaluationRequest.model_validate_json(canonical)
    assert (
        canonical
        == json.dumps(
            request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    )
    report = _report(output)
    assert_snapshot(report, request)
    assert report == StatisticalEvaluator().evaluate(request)
    assert report.decision == "improved"
    assert report.difference == pytest.approx(0.30)
    assert (report.difference_interval.lower, report.difference_interval.upper) == pytest.approx(
        newcombe_difference(10, 19, 30, 0.05)
    )
    assert len(report.trial_ids) == report.baseline.attempted + report.candidate.attempted == 60

    manifest = _json(output / "manifest.json")
    assert manifest["schema_version"] == 1
    raw = (output / "request.raw.json").read_bytes()
    assert manifest["input"] == {
        "submitted": {
            "path": "request.raw.json",
            "size_bytes": len(raw),
            "sha256": sha256(raw).hexdigest(),
        },
        "canonical": {"path": "request.json", "sha256": report.input_sha256},
    }
    assert sha256(canonical).hexdigest() == report.input_sha256
    assert manifest["plan"] == request.plan.model_dump(mode="json")
    assert manifest["engine"] == {
        "version": report.engine_version,
        "method": report.method,
        "settings": {
            "arm_interval_alpha": 0.05,
            "difference_interval_alpha": 0.05,
            "uses_rng": False,
        },
    }
    assert manifest["runtime"]["packages"]["dreamlab-hack"] == version("dreamlab-hack")
    assert manifest["runtime"]["packages"]["scipy"] == version("scipy")
    assert manifest["runtime"]["python"] and manifest["runtime"]["platform"]
    source = manifest["source"]
    assert re.fullmatch(r"[0-9a-f]{64}", source["tree_sha256"])
    package = Path(dreamlab.__file__).resolve().parent
    lock = (
        package.parent.parent / "uv.lock"
        if source["uv_lock"]["origin"] == "source_tree"
        else (package / "uv.lock")
    )
    assert source["uv_lock"]["sha256"] == sha256(lock.read_bytes()).hexdigest()
    if source["git_revision"] is not None:
        assert re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source["git_revision"])
    summary = (output / "summary.txt").read_text(encoding="utf-8")
    assert "Decision: improved" in summary
    assert "Submitted attempts: 60 total" in summary
    assert "probability units" in summary and "percentage points" in summary
    assert report.rationale in summary and all(warning in summary for warning in report.warnings)


def test_not_evaluable_is_a_valid_success_and_preserves_all_raw_buckets(tmp_path, monkeypatch):
    payload = make_payload("1010?x", "10??x", budget=6)
    output, status = _submit(tmp_path, payload, monkeypatch)
    assert status == 0
    assert _contents(output) == SUCCESS_FILES
    report = _report(output)
    assert_refused(report)
    assert_snapshot(report, EvaluationRequest.model_validate(payload))
    assert sum(arm.attempted for arm in [report.baseline, report.candidate]) == 11
    assert (
        report.baseline.attempted,
        report.baseline.successes,
        report.baseline.failures,
        report.baseline.unknown,
        report.baseline.invalid,
    ) == (6, 2, 2, 1, 1)
    assert (
        report.candidate.attempted,
        report.candidate.successes,
        report.candidate.failures,
        report.candidate.unknown,
        report.candidate.invalid,
    ) == (5, 1, 1, 2, 1)
    assert "Candidate minus baseline (probability units): unavailable" in (
        output / "summary.txt"
    ).read_text(encoding="utf-8")


def test_bundle_counts_post_stop_attempts_while_recording_effective_look_policy(
    tmp_path, monkeypatch
):
    payload = make_payload("0" * 18 + "1x", "1" * 18 + "0?", budget=30, looks=(18, 30), alpha=0.07)
    output, status = _submit(tmp_path, payload, monkeypatch)
    assert status == 0
    report = _report(output)
    assert_snapshot(report, EvaluationRequest.model_validate(payload))
    assert report.decision == "improved" and report.difference == 1.0
    assert report.baseline.attempted == report.candidate.attempted == 20
    assert report.baseline.invalid == report.candidate.unknown == 1
    manifest = _json(output / "manifest.json")
    assert manifest["plan"]["planned_looks"] == [18, 30]
    assert manifest["engine"]["settings"]["arm_interval_alpha"] == 0.07 / (2 * 2)
    assert "4 post-stop attempts" in (output / "summary.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("raw", [b"", b"{", b'{"bad_utf8": "\xff"}', b"[]", b"{}"])
def test_malformed_or_corrupted_json_saves_exact_input_and_diagnostic(tmp_path, monkeypatch, raw):
    def unexpected_evaluation(_):
        pytest.fail("malformed input reached the evaluator")

    monkeypatch.setattr(cli, "_evaluate", unexpected_evaluation)
    source = tmp_path / "input.json"
    source.write_bytes(raw)
    output = tmp_path / "run"
    assert cli.main(_command(source, output)) == 2
    assert (output / "request.raw.json").read_bytes() == raw
    details = _diagnostics(
        output, 2, "malformed_request", "validate_request", {"diagnostics.json", "request.raw.json"}
    )
    assert details[0]["code"] and "field" in details[0]


@pytest.mark.parametrize(
    "change",
    [
        {"episode_id": "episode-1"},
        {"trial_id": "trial-1"},
        {"task_version": 2},
        {"checkpoint_id": "other-checkpoint"},
        {"scenario_id": "unplanned"},
        {"reviewer_id": None},
        {"outcome": "invalid"},
    ],
)
def test_invalid_trial_membership_or_provenance_is_rejected(tmp_path, monkeypatch, change):
    payload = make_payload("01", "10", budget=2)
    payload["trials"][1].update(change)
    output, status = _submit(tmp_path, payload, monkeypatch)
    assert status == 2
    _diagnostics(
        output, 2, "malformed_request", "validate_request", {"diagnostics.json", "request.raw.json"}
    )


@pytest.mark.parametrize("schedule", [[], [24, 24], [12], [12, 4, 24]])
def test_invalid_sequential_schedule_is_rejected(tmp_path, monkeypatch, schedule):
    payload = make_payload("0", "1", budget=24, looks=(12, 24))
    payload["plan"]["planned_looks"] = schedule
    output, status = _submit(tmp_path, payload, monkeypatch)
    assert status == 2
    details = _diagnostics(
        output, 2, "malformed_request", "validate_request", {"diagnostics.json", "request.raw.json"}
    )
    assert details[0]["field"] == ["plan"]


@pytest.mark.parametrize("directory", [False, True], ids=["missing", "is-directory"])
def test_input_read_error_creates_diagnostics_only(tmp_path, directory):
    source = tmp_path / "input.json"
    if directory:
        source.mkdir()
    output = tmp_path / "run"
    assert cli.main(_command(source, output)) == 5
    _diagnostics(output, 5, "input_unreadable", "read_input", {"diagnostics.json"})


def test_closed_stdin_descriptor_publishes_input_unreadable(tmp_path):
    output = tmp_path / "run"
    result = subprocess.run(
        [
            "sh",
            "-c",
            'exec 0<&-; exec "$@"',
            "sh",
            sys.executable,
            "-m",
            "dreamlab.evaluation",
            *_command("-", output),
        ],
        cwd=tmp_path,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 5, result.stderr.decode(errors="replace")
    assert b"Traceback" not in result.stderr
    _diagnostics(output, 5, "input_unreadable", "read_input", {"diagnostics.json"})


def test_closed_python_stdin_stream_publishes_input_unreadable(tmp_path, monkeypatch):
    stdin = io.TextIOWrapper(io.BytesIO())
    stdin.close()
    monkeypatch.setattr(sys, "stdin", stdin)
    output = tmp_path / "run"
    assert cli.main(_command("-", output)) == 5
    _diagnostics(output, 5, "input_unreadable", "read_input", {"diagnostics.json"})


@pytest.mark.parametrize(
    ("error", "code"),
    [(ArithmeticError, "evaluator_error"), (EvaluationUnavailable, "evaluator_unavailable")],
)
def test_evaluator_error_preserves_both_inputs_without_a_report(tmp_path, monkeypatch, error, code):
    def fail(_):
        raise error("injected failure")

    monkeypatch.setattr(cli, "_evaluate", fail)
    output, status = _submit(tmp_path, make_payload("01", "10", budget=2), monkeypatch)
    assert status == 3
    assert _diagnostics(output, 3, code, "evaluate") == [
        {"exception_type": error.__name__, "message": "injected failure"}
    ]
    assert EvaluationRequest.model_validate_json((output / "request.json").read_bytes())


@pytest.mark.parametrize(
    ("update", "fields"),
    [
        (lambda r: {"evaluation_id": "other-evaluation"}, [["evaluation_id"]]),
        (lambda r: {"trial_ids": r.trial_ids[::-1]}, [["trial_ids"]]),
        (lambda r: {"trial_ids": r.trial_ids[:-1]}, [["trial_ids"]]),
        (
            lambda r: {"baseline": r.candidate, "candidate": r.baseline},
            [["baseline", "checkpoint_id"], ["candidate", "checkpoint_id"]],
        ),
        (
            lambda r: {"baseline": r.baseline.model_copy(update={"attempted": 5, "successes": 2})},
            [["baseline", "attempted"], ["baseline", "successes"]],
        ),
        (
            lambda r: {"candidate": r.candidate.model_copy(update={"failures": 0, "unknown": 2})},
            [["candidate", "failures"], ["candidate", "unknown"]],
        ),
        (
            lambda r: {"baseline": r.baseline.model_copy(update={"failures": 2, "invalid": 0})},
            [["baseline", "failures"], ["baseline", "invalid"]],
        ),
    ],
)
def test_report_with_incorrect_ids_or_raw_counts_is_rejected(tmp_path, monkeypatch, update, fields):
    def mismatched(request):
        report = StatisticalEvaluator().evaluate(request)
        return report.model_copy(update=update(report))

    monkeypatch.setattr(cli, "_evaluate", mismatched)
    output, status = _submit(tmp_path, make_payload("10?x", "10?x", budget=4), monkeypatch)
    assert status == 4
    details = _diagnostics(output, 4, "report_mismatch", "verify_report")
    assert [item["field"] for item in details] == fields
    assert all(item["actual"] != item["expected"] for item in details)


def test_wrong_task_report_has_same_ids_and_counts_but_different_hash(tmp_path, monkeypatch):
    def wrong_task(request):
        changed = request.model_dump(mode="json")
        changed["plan"]["task"].update(task_id="other-task", version=2)
        for trial in changed["trials"]:
            trial.update(task_id="other-task", task_version=2)
        return StatisticalEvaluator().evaluate(EvaluationRequest.model_validate(changed))

    monkeypatch.setattr(cli, "_evaluate", wrong_task)
    output, status = _submit(tmp_path, make_payload("01", "10", budget=2), monkeypatch)
    assert status == 4
    details = _diagnostics(output, 4, "report_mismatch", "verify_report")
    assert [item["field"] for item in details] == [["input_sha256"]]
    assert details[0]["expected"] == sha256((output / "request.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("update", [{"difference": float("nan")}, {"decision": "not-a-verdict"}])
def test_malformed_evaluator_report_is_rejected(tmp_path, monkeypatch, update):
    def malformed(request):
        return StatisticalEvaluator().evaluate(request).model_copy(update=update)

    monkeypatch.setattr(cli, "_evaluate", malformed)
    output, status = _submit(tmp_path, make_payload("01", "10", budget=2), monkeypatch)
    assert status == 4
    assert _diagnostics(output, 4, "invalid_report", "validate_report")


def _tamper_fixture_report(tmp_path, monkeypatch, path, value):
    payload = _json(REPORT)
    field = payload
    for segment in path[:-1]:
        field = field[segment]
    field[path[-1]] = value
    report = EvaluationReport.model_validate(payload)  # The shared schema alone accepts it.
    monkeypatch.setattr(cli, "_evaluate", lambda _: report)
    output = tmp_path / "run"
    assert cli.main(_command(FIXTURE, output)) == 4
    return _diagnostics(output, 4, "report_mismatch", "verify_report")


def test_fixture_decision_flipped_to_improved_is_rejected(tmp_path, monkeypatch):
    errors = _tamper_fixture_report(tmp_path, monkeypatch, ["decision"], "improved")
    assert errors == [{"field": ["decision"], "expected": "inconclusive", "actual": "improved"}]


@pytest.mark.parametrize(
    ("field", "value", "expected_field"),
    [
        (["decision"], "regressed", ["decision"]),
        (["decision"], "not_evaluable", ["difference"]),
        (["difference"], 0.25, ["difference"]),
        (["difference_interval", "upper"], 0.4, ["difference"]),
        (["difference_interval", "lower"], 0.6, ["difference"]),
        (["difference_interval", "lower"], 0.2, ["decision"]),
        (
            ["difference_interval", "confidence_level"],
            0.9,
            ["difference_interval", "confidence_level"],
        ),
        (["difference_interval"], None, ["difference_interval"]),
        (["baseline", "success_rate"], None, ["baseline", "success_rate"]),
        (["baseline", "success_interval", "upper"], 0.4, ["baseline", "success_rate"]),
        (["candidate", "success_interval", "lower"], 1.0, ["candidate", "success_interval"]),
    ],
)
def test_report_estimates_must_be_internally_consistent(
    tmp_path, monkeypatch, field, value, expected_field
):
    assert expected_field in [
        error["field"] for error in _tamper_fixture_report(tmp_path, monkeypatch, field, value)
    ]


@pytest.mark.parametrize(
    ("decision", "lower", "upper", "valid"),
    [
        ("inconclusive", 0.1, 0.6, True),  # Exactly the practical margin is not directional.
        ("improved", 0.1, 0.6, False),
        ("improved", 0.10000000000000002, 0.6, True),
        ("inconclusive", -0.6, 0.0, True),  # Exactly zero is not regression.
        ("regressed", -0.6, 0.0, False),
        ("regressed", -0.6, -0.000001, True),
    ],
)
def test_report_verification_uses_strict_decision_thresholds(decision, lower, upper, valid):
    payload = _json(REPORT)
    report = EvaluationReport.model_validate(payload)
    if upper <= 0.0:
        payload["baseline"]["success_rate"] = 1.0
        payload["candidate"]["success_rate"] = 0.5
        payload["baseline"]["success_interval"] = report.candidate.success_interval.model_dump()
        payload["difference"] = -0.5
    payload["difference_interval"].update(lower=lower, upper=upper)
    payload["decision"] = decision
    request = EvaluationRequest.model_validate_json(FIXTURE.read_bytes())
    errors = cli._estimate_errors(request, EvaluationReport.model_validate(payload))
    assert [error["field"] for error in errors] == ([] if valid else [["decision"]])


@pytest.mark.parametrize("kind", ["directory", "empty-directory", "file", "symlink", "dangling"])
def test_existing_destinations_are_not_overwritten(tmp_path, capsys, kind):
    output = tmp_path / "run"
    referent = tmp_path / "referent"
    if kind == "directory":
        output.mkdir()
        (output / "old").write_bytes(b"old data")
    elif kind == "empty-directory":
        output.mkdir()
    elif kind == "file":
        output.write_bytes(b"old data")
    else:
        if kind == "symlink":
            referent.mkdir()
            (referent / "old").write_bytes(b"old data")
        output.symlink_to(referent, target_is_directory=True)
    before = _contents(tmp_path)
    link_target = output.readlink() if output.is_symlink() else None
    assert cli.main(_command(FIXTURE, output)) == 5
    assert "output_collision" in capsys.readouterr().err
    assert _contents(tmp_path) == before
    if kind in {"directory", "symlink"}:
        assert _contents(output) == {"old"}
        assert (output / "old").read_bytes() == b"old data"
    elif kind == "empty-directory":
        assert output.is_dir() and not _contents(output)
    elif kind == "file":
        assert output.read_bytes() == b"old data"
    if kind in {"symlink", "dangling"}:
        assert link_target is not None
        assert output.readlink() == link_target


def test_output_parent_must_exist(tmp_path, capsys):
    output = tmp_path / "absent" / "run"
    assert cli.main(_command(FIXTURE, output)) == 5
    assert "output_error" in capsys.readouterr().err
    assert not _contents(tmp_path)


def test_only_one_concurrent_invocation_reserves_output_and_nothing_publishes_early(
    tmp_path,
    monkeypatch,
    capsys,
):
    output = tmp_path / "run"
    inside = Event()
    resume = Event()
    statuses = []
    real_evaluate = cli._evaluate

    def wait(request):
        inside.set()
        assert resume.wait(timeout=10)
        return real_evaluate(request)

    monkeypatch.setattr(cli, "_evaluate", wait)
    worker = Thread(target=lambda: statuses.append(cli.main(_command(FIXTURE, output))))
    worker.start()
    try:
        assert inside.wait(timeout=10)
        assert not output.exists()
        [lock] = tmp_path.glob("*.lock")
        assert cli.main(_command(FIXTURE, output)) == 5
        assert lock.is_file()
        assert "reserved" in capsys.readouterr().err
        assert not output.exists()
    finally:
        resume.set()
        worker.join(timeout=10)
    assert statuses == [0]
    assert _contents(tmp_path) == {"run"}
    assert _contents(output) == SUCCESS_FILES


def test_atomic_publish_cannot_clobber_a_racing_empty_directory(tmp_path, monkeypatch, capsys):
    output = tmp_path / "run"
    rename = artifacts._rename_new

    def race(source_fd, name, destination_fd, destination):
        os.mkdir(destination, dir_fd=destination_fd)
        rename(source_fd, name, destination_fd, destination)

    monkeypatch.setattr(artifacts, "_rename_new", race)
    assert cli.main(_command(FIXTURE, output)) == 5
    assert "output_collision" in capsys.readouterr().err
    assert _contents(tmp_path) == {"run"} and not _contents(output)


def test_rename_error_leaves_no_partial_output_or_lock(tmp_path, monkeypatch, capsys):
    output = tmp_path / "run"

    def fail(source_fd, name, destination_fd, destination):
        with artifacts._directory(name, dir_fd=source_fd) as bundle_fd:
            assert set(os.listdir(bundle_fd)) == SUCCESS_FILES
        assert not output.exists()
        raise OSError(errno.EIO, "injected rename failure")

    monkeypatch.setattr(artifacts, "_rename_new", fail)
    assert cli.main(_command(FIXTURE, output)) == 5
    assert "injected rename failure" in capsys.readouterr().err
    assert not _contents(tmp_path)


@pytest.mark.parametrize("filename", ["request.raw.json", "report.json", "diagnostics.json"])
def test_artifact_write_error_never_publishes_partial_bundle(
    tmp_path, monkeypatch, capsys, filename
):
    source = FIXTURE
    if filename == "diagnostics.json":
        source = tmp_path / "malformed.json"
        source.write_bytes(b"{")
    before = _contents(tmp_path)
    write = artifacts.StagedBundle.write_bytes

    def fail(bundle, name, data):
        if name == filename:
            write(bundle, name, data[:3])
            raise OSError(errno.ENOSPC, "injected write failure")
        return write(bundle, name, data)

    monkeypatch.setattr(artifacts.StagedBundle, "write_bytes", fail)
    assert cli.main(_command(source, tmp_path / "run")) == 5
    assert "injected write failure" in capsys.readouterr().err
    assert _contents(tmp_path) == before


def test_staged_bundle_requires_verified_directory_before_publication(
    tmp_path, monkeypatch, capsys
):
    original_check = artifacts._entry_matches
    refused = []

    def verify_entry(parent, name, fd):
        if name == "bundle":
            refused.append(name)
            return False
        return original_check(parent, name, fd)

    monkeypatch.setattr(artifacts, "_entry_matches", verify_entry)
    assert cli.main(_command(FIXTURE, tmp_path / "run")) == 5
    assert refused == ["bundle"]
    assert "output_error" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_reservation_cleanup_failure_keeps_successful_result(tmp_path, monkeypatch, capsys):
    output = tmp_path / "run"
    unlink = os.unlink

    def fail(path, *, dir_fd=None):
        if str(path).endswith(".lock"):
            assert _contents(output) == SUCCESS_FILES
            raise PermissionError(errno.EACCES, "injected reservation cleanup failure\nsecond line")
        return unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(artifacts.os, "unlink", fail)
    assert cli.main(_command(FIXTURE, output)) == 0
    assert (output / "report.json").read_bytes() == REPORT.read_bytes()
    stderr = capsys.readouterr().err
    assert stderr.count("\n") == 1 and r"cleanup failure\nsecond line" in stderr
    assert "cleanup_warning: remove reservation" in stderr
    assert len(list(tmp_path.glob("*.lock"))) == 1


def test_cleanup_warning_cannot_fail_successful_process_when_stderr_pipe_is_broken(tmp_path):
    output = tmp_path / "run"
    entry = """
import errno
import sys
from dreamlab.evaluation import artifacts, cli

remove_entry = artifacts._remove_entry
def fail(parent, name, fd, **kwargs):
    if name.endswith(".lock"):
        raise PermissionError(errno.EACCES, "injected cleanup failure")
    return remove_entry(parent, name, fd, **kwargs)

artifacts._remove_entry = fail
sys.exit(cli.main(sys.argv[1:]))
"""
    reader, writer = os.pipe()
    os.close(reader)
    try:
        result = subprocess.run(
            [sys.executable, "-c", entry, *_command(FIXTURE, output)],
            stderr=writer,
            timeout=30,
            check=False,
        )
    finally:
        os.close(writer)
    assert result.returncode == 0
    assert (output / "report.json").read_bytes() == REPORT.read_bytes()


def test_module_and_installed_entry_point_produce_identical_report(tmp_path):
    executable = shutil.which("dream-eval", path=str(Path(sys.executable).parent))
    assert executable is not None, "Sync the project to install the console entry point."
    raw = FIXTURE.read_bytes()
    for command, input_path, output in (
        ([sys.executable, "-m", "dreamlab.evaluation"], "-", "module"),
        ([executable], FIXTURE, "console"),
    ):
        result = subprocess.run(
            [*command, *_command(input_path, output)],
            cwd=tmp_path,
            capture_output=True,
            input=raw if input_path == "-" else None,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        assert result.stdout == result.stderr == b""
        assert _contents(tmp_path / output) == SUCCESS_FILES
        assert (tmp_path / output / "report.json").read_bytes() == REPORT.read_bytes()
        assert (tmp_path / output / "request.raw.json").read_bytes() == raw
    assert (tmp_path / "module" / "manifest.json").read_bytes() == (
        tmp_path / "console" / "manifest.json"
    ).read_bytes()
    lock = _json(tmp_path / "console" / "manifest.json")["source"]["uv_lock"]
    assert re.fullmatch(r"[0-9a-f]{64}", lock["sha256"])
