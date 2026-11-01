"""
Each quality check fires on deliberately bad input and stays quiet on clean input.
"""

import numpy as np
import pandas as pd
import pytest

from features import build
from features.quality_checks import (
    DataQualityError,
    check_drift,
    check_no_unexpected_nulls,
    check_ranges,
    check_row_count,
    check_txn_reconciliation,
    check_zero_activity_defaults,
    enforce,
    run_all_checks,
)

AS_OF = "2026-08-01"


@pytest.fixture(scope="module")
def clean():
    """The real training build (clean data) plus its expected population and source frames."""
    sources = build.load_sources()
    features = build.build_features(AS_OF)
    expected_ids = build.population(sources, AS_OF, None)
    return {"features": features, "sources": sources, "expected_ids": expected_ids}


def _zero_activity_row(features: pd.DataFrame) -> int:
    """Index of a row with txn_count_prior == 0 (the zero-activity rows are guaranteed by the data)."""
    return int(features.index[features["txn_count_prior"] == 0][0])


def test_clean_build_passes_every_check(clean):
    summary = run_all_checks(
        clean["features"],
        transactions=clean["sources"]["transactions"],
        as_of=AS_OF,
        expected_ids=clean["expected_ids"],
    )
    assert summary["passed"], summary
    enforce(summary)  # must not raise


def test_injected_null_fires_null_check(clean):
    bad = clean["features"].copy()
    bad.loc[bad.index[0], "spend_prior_winsorized"] = np.nan
    result = check_no_unexpected_nulls(bad)
    assert result["passed"] is False
    assert result["failing_features"] == ["spend_prior_winsorized"]
    assert result["failing_rows"] == [int(bad.loc[bad.index[0], "customer_id"])]


def test_zero_activity_row_with_nan_default_fires_zero_activity_check(clean):
    bad = clean["features"].copy()
    row = _zero_activity_row(bad)
    bad.loc[row, "return_rate_prior_180d"] = np.nan
    result = check_zero_activity_defaults(bad)
    assert result["passed"] is False
    assert "return_rate_prior_180d" in result["failing_features"]


def test_zero_activity_row_with_nonzero_spend_fires_zero_activity_check(clean):
    bad = clean["features"].copy()
    row = _zero_activity_row(bad)
    bad.loc[row, "spend_prior_winsorized"] = 12.5
    result = check_zero_activity_defaults(bad)
    assert result["passed"] is False
    assert result["failing_features"] == ["spend_prior_winsorized"]


def test_out_of_range_amount_fires_range_check(clean):
    bad = clean["features"].copy()
    bad.loc[bad.index[0], "spend_prior_winsorized"] = 50_000.0  # unit error: cents vs dollars
    result = check_ranges(bad)
    assert result["passed"] is False
    assert result["failing_features"] == ["spend_prior_winsorized"]


def test_return_rate_above_one_fires_range_check(clean):
    bad = clean["features"].copy()
    bad.loc[bad.index[0], "return_rate_prior_180d"] = 1.5
    result = check_ranges(bad)
    assert result["passed"] is False
    assert "return_rate_prior_180d" in result["failing_features"]


def test_dropped_customer_fires_row_count_check(clean):
    bad = clean["features"].iloc[1:].copy()
    result = check_row_count(bad, clean["expected_ids"])
    assert result["passed"] is False
    assert clean["features"]["customer_id"].iloc[0] in result["failing_rows"]


def test_duplicated_customer_fires_row_count_check(clean):
    bad = pd.concat([clean["features"], clean["features"].iloc[:1]], ignore_index=True)
    result = check_row_count(bad, clean["expected_ids"])
    assert result["passed"] is False


def test_txn_count_off_by_one_window_fires_reconciliation_check(clean):
    bad = clean["features"].copy()
    bad.loc[bad.index[0], "txn_count_prior"] += 1  # e.g. a window boundary off-by-one
    result = check_txn_reconciliation(bad, clean["sources"]["transactions"], AS_OF)
    assert result["passed"] is False
    assert result["failing_features"] == ["txn_count_prior"]


def test_shifted_distribution_fires_drift_check(clean):
    shifted = clean["features"].copy()
    shifted["spend_prior_winsorized"] = shifted["spend_prior_winsorized"] * 2.0
    result = check_drift(shifted, reference=clean["features"])
    assert result["passed"] is False
    assert "spend_prior_winsorized" in result["failing_features"]


def test_identical_distribution_passes_drift_check(clean):
    result = check_drift(clean["features"], reference=clean["features"])
    assert result["passed"] is True
    assert result["skipped"] is False


def test_drift_without_reference_is_reported_as_skipped_not_passed(clean):
    result = check_drift(clean["features"], reference=None)
    assert result["skipped"] is True


def test_enforce_raises_when_any_check_fails(clean):
    bad = clean["features"].copy()
    bad.loc[bad.index[0], "spend_prior_winsorized"] = np.nan
    summary = run_all_checks(
        bad,
        transactions=clean["sources"]["transactions"],
        as_of=AS_OF,
        expected_ids=clean["expected_ids"],
    )
    assert summary["passed"] is False
    with pytest.raises(DataQualityError):
        enforce(summary)
