"""Regression tests for artifact integrity, evidence identity, and provenance."""

import errno
import json
import os
import shutil
import subprocess
import sys
from hashlib import sha256
from importlib.metadata import distribution
from pathlib import Path
from zipfile import ZipFile

import pytest
from eval_cases import FIXTURE, assert_refused, assert_snapshot, evaluate, make_payload

from dreamlab.contracts import EvaluationReport, EvaluationRequest, Interval
from dreamlab.evaluation import cli, provenance
from dreamlab.evaluation.engine import StatisticalEvaluator

ROOT = Path(__file__).resolve().parents[2]
SUCCESS_FILES = {"request.raw.json", "request.json", "report.json", "summary.txt", "manifest.json"}


def _command(source, output):
    return ["evaluate", "--input", str(source), "--output-dir", str(output)]


def _complete_bundle(output, expected_raw):
    assert output.is_dir() and not output.is_symlink()
    assert {path.name for path in output.iterdir()} == SUCCESS_FILES
    assert (output / "request.raw.json").read_bytes() == expected_raw
    canonical = (output / "request.json").read_bytes()
    request = EvaluationRequest.model_validate_json(canonical)
    assert request == EvaluationRequest.model_validate_json(expected_raw)
    report = EvaluationReport.model_validate_json((output / "report.json").read_bytes())
    assert_snapshot(report, request)
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert manifest["input"]["submitted"]["sha256"] == sha256(expected_raw).hexdigest()
    assert manifest["input"]["canonical"]["sha256"] == sha256(canonical).hexdigest()
    assert f"Decision: {report.decision}" in (output / "summary.txt").read_text(encoding="utf-8")
    return manifest


@pytest.mark.skipif(sys.platform != "linux", reason="Secure artifact publication is Linux-only")
def test_completed_bundle_keeps_all_request_and_report_files_private(tmp_path):
    output = tmp_path / "run"
    assert cli.main(_command(FIXTURE, output)) == 0
    _complete_bundle(output, FIXTURE.read_bytes())
    assert not output.stat().st_mode & 0o077
    for artifact in output.iterdir():
        assert artifact.is_file() and not artifact.is_symlink()
        assert not artifact.stat().st_mode & 0o077


@pytest.mark.skipif(sys.platform != "linux", reason="Secure artifact publication is Linux-only")
def test_improved_report_with_lower_bound_below_plan_margin_is_rejected(tmp_path, monkeypatch):
    payload = make_payload("1" * 10 + "0" * 20, "1" * 19 + "0" * 11, budget=30, margin=0.10)
    request = EvaluationRequest.model_validate(payload)
    report = StatisticalEvaluator().evaluate(request)
    assert report.decision == "inconclusive"
    assert report.difference_interval is not None
    assert report.difference is not None
    assert (
        0 < report.difference_interval.lower < request.plan.minimum_improvement < report.difference
    )
    forged = report.model_copy(
        update={"decision": "improved", "rationale": "Candidate exceeded the planned margin."}
    )
    assert_snapshot(forged, request)
    monkeypatch.setattr(cli, "_evaluate", lambda _: forged)
    source = tmp_path / "request.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "run"

    assert cli.main(_command(source, output)) == 4
    assert {path.name for path in output.iterdir()} == {
        "request.raw.json",
        "request.json",
        "diagnostics.json",
    }
    diagnostics = json.loads((output / "diagnostics.json").read_bytes())
    assert diagnostics["schema_version"] == 1
    assert diagnostics["exit_code"] == 4
    assert (diagnostics["code"], diagnostics["stage"]) in {
        ("invalid_report", "validate_report"),
        ("report_mismatch", "verify_report"),
    }


@pytest.mark.skipif(sys.platform != "linux", reason="Secure artifact publication is Linux-only")
def test_lock_cleanup_error_after_publication_keeps_success_and_complete_bundle(
    tmp_path, monkeypatch
):
    output = tmp_path / "run"
    real_unlink = os.unlink
    failed_removals = []

    def fail_lock_cleanup(path, *args, **kwargs):
        if Path(os.fsdecode(path)).suffix == ".lock" and output.is_dir():
            failed_removals.append(path)
            raise PermissionError(errno.EACCES, "injected lock cleanup error", path)
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", fail_lock_cleanup)
    if real_unlink in os.supports_dir_fd:
        monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {fail_lock_cleanup})

    status = cli.main(_command(FIXTURE, output))
    assert failed_removals, "The lock removal must be attempted after publication."
    _complete_bundle(output, FIXTURE.read_bytes())
    assert status == 0, "The complete bundle was already published when lock cleanup failed."


@pytest.mark.skipif(sys.platform != "linux", reason="Secure artifact publication is Linux-only")
def test_closed_stdin_publishes_read_error_diagnostics(tmp_path, monkeypatch):
    # CPython can initialize sys.stdin to None when descriptor 0 is closed.
    monkeypatch.setattr(sys, "stdin", None)
    output = tmp_path / "run"

    assert cli.main(_command("-", output)) == 5
    assert {path.name for path in output.iterdir()} == {"diagnostics.json"}
    diagnostics = json.loads((output / "diagnostics.json").read_bytes())
    assert diagnostics["schema_version"] == 1
    assert diagnostics["exit_code"] == 5
    assert diagnostics["code"] == "input_unreadable"
    assert diagnostics["stage"] == "read_input"
    assert diagnostics["message"]


@pytest.mark.skipif(sys.platform != "linux", reason="Secure artifact publication is Linux-only")
def test_self_consistent_estimates_must_match_submitted_outcomes(tmp_path, monkeypatch):
    payload = make_payload("10", "10", budget=2, margin=0.1)
    request = EvaluationRequest.model_validate(payload)
    report = StatisticalEvaluator().evaluate(request)
    forged = report.model_copy(
        update={
            "baseline": report.baseline.model_copy(
                update={
                    "success_rate": 0.0,
                    "success_interval": Interval(lower=0.0, upper=1.0, confidence_level=0.95),
                }
            ),
            "candidate": report.candidate.model_copy(
                update={
                    "success_rate": 1.0,
                    "success_interval": Interval(lower=0.0, upper=1.0, confidence_level=0.95),
                }
            ),
            "difference": 1.0,
            "difference_interval": Interval(lower=0.2, upper=1.0, confidence_level=0.95),
            "decision": "improved",
        }
    )
    assert_snapshot(forged, request)
    monkeypatch.setattr(cli, "_evaluate", lambda _: forged)
    source = tmp_path / "request.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "run"

    assert cli.main(_command(source, output)) == 4
    assert {path.name for path in output.iterdir()} == {
        "request.raw.json",
        "request.json",
        "diagnostics.json",
    }
    diagnostics = json.loads((output / "diagnostics.json").read_bytes())
    assert diagnostics["exit_code"] == 4
    assert diagnostics["code"] == "report_mismatch"
    assert any(
        error["field"]
        in (
            ["baseline", "success_rate"],
            ["candidate", "success_rate"],
            ["difference_interval"],
        )
        for error in diagnostics["details"]
    )


@pytest.mark.skipif(sys.platform != "linux", reason="Secure artifact publication is Linux-only")
def test_self_consistent_estimates_cannot_replace_terminal_prefix_with_all_rows(
    tmp_path, monkeypatch
):
    payload = make_payload("0" * 18 + "1", "1" * 18 + "0", budget=30, looks=(18, 30))
    request = EvaluationRequest.model_validate(payload)
    report = StatisticalEvaluator().evaluate(request)
    assert report.decision == "improved"
    assert report.baseline.success_rate == 0.0
    assert report.candidate.success_rate == 1.0
    # Forge mutually consistent rates from all rows rather than the terminal n=18 prefix.
    baseline_rate, candidate_rate = 1 / 19, 18 / 19
    forged = report.model_copy(
        update={
            "baseline": report.baseline.model_copy(
                update={
                    "success_rate": baseline_rate,
                    "success_interval": Interval(lower=0.0, upper=0.5, confidence_level=0.9875),
                }
            ),
            "candidate": report.candidate.model_copy(
                update={
                    "success_rate": candidate_rate,
                    "success_interval": Interval(lower=0.5, upper=1.0, confidence_level=0.9875),
                }
            ),
            "difference": candidate_rate - baseline_rate,
            "difference_interval": Interval(lower=0.2, upper=1.0, confidence_level=0.95),
        }
    )
    assert_snapshot(forged, request)
    monkeypatch.setattr(cli, "_evaluate", lambda _: forged)
    source = tmp_path / "request.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "run"

    assert cli.main(_command(source, output)) == 4
    diagnostics = json.loads((output / "diagnostics.json").read_bytes())
    assert diagnostics["code"] == "report_mismatch"
    assert any(error["field"] == ["baseline"] for error in diagnostics["details"])
    assert any(error["field"] == ["candidate"] for error in diagnostics["details"])


def test_bare_path_with_literal_hash_and_encoded_file_uri_are_duplicate_sources():
    payload = make_payload("0" * 24, "1" * 24, budget=24)
    payload["trials"][0]["source_uri"] = "/tmp/run#1.mp4"
    payload["trials"][1]["source_uri"] = "file:///tmp/run%232.mp4"
    assert evaluate(payload).decision == "improved"

    payload["trials"][1]["source_uri"] = "file:///tmp/run%231.mp4"
    report = evaluate(payload)
    assert "Duplicate source URI" in report.rationale
    assert_refused(report)


def test_editable_direct_url_uses_checkout_lock(tmp_path, monkeypatch):
    checkout = tmp_path / "editable checkout"
    package = checkout / "src" / "dreamlab"
    package.mkdir(parents=True)
    (package / "__init__.py").touch()
    (package / "uv.lock").write_bytes(b"different package lock\n")
    checkout_lock = b"editable checkout lock\n"
    (checkout / "uv.lock").write_bytes(checkout_lock)
    (checkout / "pyproject.toml").write_text(
        '[project]\nname = "dreamlab-hack"\n', encoding="utf-8"
    )

    site = tmp_path / "site-packages"
    info = site / "dreamlab_hack-0.1.0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: dreamlab-hack\nVersion: 0.1.0\n", encoding="utf-8"
    )
    direct_url = {"url": checkout.as_uri(), "dir_info": {"editable": True}}
    (info / "direct_url.json").write_text(json.dumps(direct_url), encoding="utf-8")
    monkeypatch.syspath_prepend(str(site))
    assert json.loads(distribution("dreamlab-hack").read_text("direct_url.json")) == direct_url

    assert provenance._source_identity(package)["uv_lock"] == {
        "path": "uv.lock",
        "origin": "source_tree",
        "sha256": sha256(checkout_lock).hexdigest(),
    }


def _run(command, *, cwd, env=None):
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"{command!r}\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(sys.platform != "linux", reason="Secure artifact publication is Linux-only")
def test_wheel_target_install_hashes_embedded_lock_in_cli_manifest(tmp_path):
    uv = shutil.which("uv")
    assert uv is not None, "The wheel smoke test requires the project's uv build tool."
    dist = tmp_path / "dist"
    _run(
        [uv, "build", "--offline", "--wheel", "--python", sys.executable, "--out-dir", str(dist)],
        cwd=ROOT,
    )
    [wheel] = dist.glob("*.whl")
    with ZipFile(wheel) as archive:
        embedded = archive.read("dreamlab/uv.lock")
    assert embedded == (ROOT / "uv.lock").read_bytes()

    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\nname = "other-project"\n', encoding="utf-8")
    (project / "uv.lock").write_bytes(b"unrelated project lock\n")
    target = project / "src"
    _run(
        [
            uv,
            "pip",
            "install",
            "--offline",
            "--no-deps",
            "--python",
            sys.executable,
            "--target",
            str(target),
            str(wheel),
        ],
        cwd=tmp_path,
    )
    assert (target / "dreamlab" / "uv.lock").read_bytes() == embedded
    scripts = os.pathsep.join(str(target / name) for name in ("bin", "Scripts"))
    executable = shutil.which("dream-eval", path=scripts)
    assert executable is not None, "Wheel installation did not provide the CLI entry point."
    output = project / "run"
    _run(
        [executable, *_command(FIXTURE, output)],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(target)},
    )
    manifest = _complete_bundle(output, FIXTURE.read_bytes())
    assert manifest["source"]["uv_lock"] == {
        "path": "uv.lock",
        "origin": "wheel",
        "sha256": sha256(embedded).hexdigest(),
    }
