"""Test cold mode gate — all five gates, disabled mode, edge cases."""

from __future__ import annotations

import pytest
from core.cold_mode import ColdMode


@pytest.fixture
def cold():
    return ColdMode(enabled=True)


@pytest.fixture
def cold_disabled():
    return ColdMode(enabled=False)


# ── Data Verified gate ──────────────────────────────────────────────

def test_low_source_reliability_blocks(cold):
    ctx = ColdMode.build_context(action="read_file", permission="READ", source_reliability=0.3)
    assert cold.should_block(ctx)
    reasons = cold.get_failure_reasons(ctx)
    assert any("reliability" in r.lower() for r in reasons)


def test_high_source_reliability_passes(cold):
    ctx = ColdMode.build_context(action="read_file", permission="READ", source_reliability=0.9)
    assert not cold.should_block(ctx)


def test_default_source_reliability(cold):
    ctx = ColdMode.build_context(action="read_file", permission="READ")
    assert not cold.should_block(ctx)


# ── Parameters In Range gate ───────────────────────────────────────

def test_outlier_parameters_blocks(cold):
    ctx = ColdMode.build_context(action="read_file", permission="READ", numeric_values=[1]*19 + [500])
    assert cold.should_block(ctx)


def test_in_range_parameters_passes(cold):
    ctx = ColdMode.build_context(action="read_file", permission="READ", numeric_values=[10, 11, 12])
    assert not cold.should_block(ctx)


def test_empty_numeric_values_passes(cold):
    ctx = ColdMode.build_context(action="read_file", permission="READ", numeric_values=[])
    assert not cold.should_block(ctx)


def test_single_value_does_not_crash(cold):
    ctx = ColdMode.build_context(action="read_file", permission="READ", numeric_values=[42])
    assert not cold.should_block(ctx)


# ── Confidence gate ────────────────────────────────────────────────

def test_low_confidence_blocks(cold):
    ctx = ColdMode.build_context(action="read_file", permission="READ", confidence=0.3)
    assert cold.should_block(ctx)
    reasons = cold.get_failure_reasons(ctx)
    assert any("confidence" in r.lower() for r in reasons)


def test_high_confidence_passes(cold):
    ctx = ColdMode.build_context(action="read_file", permission="READ", confidence=0.95)
    assert not cold.should_block(ctx)


def test_default_confidence_read(cold):
    ctx = ColdMode.build_context(action="read_file", permission="READ")
    assert not cold.should_block(ctx)


# ── Risk / Reversibility gate ──────────────────────────────────────

def test_irreversible_action_blocks(cold):
    ctx = ColdMode.build_context(action="delete", permission="ADMIN")
    assert cold.should_block(ctx)


def test_reversible_action_passes(cold):
    ctx = ColdMode.build_context(action="list", permission="READ")
    assert not cold.should_block(ctx)


# ── Fallback gate ──────────────────────────────────────────────────

def test_execute_without_fallback_blocks(cold):
    ctx = ColdMode.build_context(action="run_command", permission="EXECUTE")
    assert cold.should_block(ctx)
    reasons = cold.get_failure_reasons(ctx)
    assert any("fallback" in r.lower() for r in reasons)


def test_execute_with_fallback_passes(cold):
    ctx = ColdMode.build_context(
        action="run_command", permission="EXECUTE", fallback_script="echo safe", confidence=0.8,
    )
    assert not cold.should_block(ctx)


def test_read_skips_fallback_check(cold):
    ctx = ColdMode.build_context(action="read_file", permission="READ")
    assert not cold.should_block(ctx)


# ── Disabled mode ──────────────────────────────────────────────────

def test_disabled_allows_all(cold_disabled):
    dangerous_actions = [
        {"action": "rm -rf /", "permission": "ADMIN"},
        {"action": "run_command", "permission": "EXECUTE"},
        {"action": "delete", "permission": "ADMIN"},
    ]
    for ctx_data in dangerous_actions:
        ctx = ColdMode.build_context(**ctx_data)
        assert not cold_disabled.should_block(ctx)


def test_disabled_returns_empty_reasons(cold_disabled):
    ctx = ColdMode.build_context(action="run_command", permission="EXECUTE")
    assert cold_disabled.get_failure_reasons(ctx) == []


# ── Edge cases ─────────────────────────────────────────────────────

def test_unknown_action_defaults(cold):
    ctx = ColdMode.build_context(action="unknown_action", permission="READ")
    assert not cold.should_block(ctx)


def test_missing_context_keys_default():
    cold = ColdMode(enabled=True)
    result = cold.evaluate({})
    assert len(result) == 5
    assert all(isinstance(r.passed, bool) for r in result)


def test_get_failure_reasons_returns_strings(cold):
    ctx = ColdMode.build_context(action="run_command", permission="EXECUTE")
    reasons = cold.get_failure_reasons(ctx)
    assert isinstance(reasons, list)
    assert len(reasons) >= 1
    assert all(isinstance(r, str) for r in reasons)


def test_evaluate_returns_checks(cold):
    ctx = ColdMode.build_context(action="read_file", permission="READ")
    results = cold.evaluate(ctx)
    assert len(results) == 5
    names = {r.check_name for r in results}
    assert names == {"data_verified", "parameters_in_range", "confidence", "risk", "fallback"}
