"""Unsupported platforms must never use an unsafe publication fallback."""

import sys

import pytest
from eval_cases import FIXTURE

from dreamlab.evaluation import cli


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_cli_fails_closed_without_secure_publication(platform, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sys, "platform", platform)
    output = tmp_path / "run"
    assert cli.main(["evaluate", "--input", str(FIXTURE), "--output-dir", str(output)]) == 5
    assert "output_error" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())
