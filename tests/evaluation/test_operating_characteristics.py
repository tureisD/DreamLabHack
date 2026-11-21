"""Integration gate: an absent or divergent public engine must not pass this test."""

import pytest
from operating_characteristics import run_audit


@pytest.mark.statistical
def test_seeded_operating_characteristics_against_public_engine():
    audit = run_audit()
    assert audit["status"] == "public-engine-parity"
    assert audit["public_reports_checked"] > 0 and len(audit["rows"]) == 19
