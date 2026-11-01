"""
Pure feature-function logic: normal case, zero-activity default, single record, and the
time-window boundaries. Also a leakage test: transactions inside the label window must not change
any feature.
"""

import pandas as pd
import pytest

from features import build, transforms

AS_OF = "2026-08-01"
CUTOFF = pd.Timestamp("2026-05-02")  # as_of - 91 days: the first instant of the label window
ONE_NS = pd.Timedelta(nanoseconds=1)


def _txns(rows: list[tuple]) -> pd.DataFrame:
    """rows: (customer_id, txn_timestamp, amount, is_returned)."""
    frame = pd.DataFrame(rows, columns=["customer_id", "txn_timestamp", "amount", "is_returned"])
    frame["txn_timestamp"] = pd.to_datetime(frame["txn_timestamp"])
    frame["is_returned"] = frame["is_returned"].astype("int64")
    return frame


def test_history_cutoff_is_91_days_before_as_of():
    assert transforms.history_cutoff(AS_OF) == CUTOFF


def test_txn_count_zero_activity_gets_explicit_zero_not_nan():
    transactions = _txns([(1, "2026-04-01", 10.0, 0)])
    result = transforms.txn_count_prior(transactions, pd.Index([1, 2]), AS_OF, window_days=90)
    assert result.loc[2] == 0
    assert result.isna().sum() == 0
    assert result.dtype == "int64"


def test_txn_count_single_record_inside_window_counts_one():
    transactions = _txns([(1, "2026-04-01", 10.0, 0)])
    result = transforms.txn_count_prior(transactions, pd.Index([1]), AS_OF, window_days=90)
    assert result.loc[1] == 1


def test_txn_count_excludes_label_window_and_starts_exactly_at_cutoff():
    transactions = _txns(
        [
            (1, CUTOFF - ONE_NS, 10.0, 0),  # last instant before the label window: counted
            (1, CUTOFF, 10.0, 0),  # first instant of the label window: NOT counted
            (1, "2026-06-15", 10.0, 0),  # inside the label window: NOT counted
        ]
    )
    result = transforms.txn_count_prior(transactions, pd.Index([1]), AS_OF, window_days=90)
    assert result.loc[1] == 1


def test_txn_count_window_start_is_inclusive_and_exact():
    start = CUTOFF - pd.Timedelta(days=90)
    transactions = _txns(
        [
            (1, start, 10.0, 0),  # exactly at window start: counted
            (1, start - ONE_NS, 10.0, 0),  # one instant before window start: NOT counted
        ]
    )
    result = transforms.txn_count_prior(transactions, pd.Index([1]), AS_OF, window_days=90)
    assert result.loc[1] == 1


def test_longer_window_counts_at_least_as_many_transactions():
    transactions = _txns(
        [(1, "2026-04-01", 10.0, 0), (1, "2025-12-01", 10.0, 0), (1, "2025-07-01", 10.0, 0)]
    )
    short = transforms.txn_count_prior(transactions, pd.Index([1]), AS_OF, window_days=90).loc[1]
    mid = transforms.txn_count_prior(transactions, pd.Index([1]), AS_OF, window_days=180).loc[1]
    long = transforms.txn_count_prior(transactions, pd.Index([1]), AS_OF, window_days=365).loc[1]
    assert (short, mid, long) == (1, 2, 3)


def test_spend_caps_each_transaction_at_cap_amount():
    transactions = _txns([(1, "2026-04-01", 100.0, 0), (1, "2026-03-01", 900.0, 0)])
    result = transforms.spend_prior_winsorized(transactions, pd.Index([1]), AS_OF, cap_amount=500.0)
    assert result.loc[1] == pytest.approx(600.0)


def test_spend_zero_activity_default_is_zero_float():
    transactions = _txns([(1, "2026-04-01", 100.0, 0)])
    result = transforms.spend_prior_winsorized(transactions, pd.Index([2]), AS_OF, cap_amount=500.0)
    assert result.loc[2] == 0.0
    assert result.dtype == "float64"


def test_spend_excludes_label_window_amounts():
    transactions = _txns([(1, "2026-06-01", 999.0, 0), (1, "2026-04-01", 10.0, 0)])
    result = transforms.spend_prior_winsorized(transactions, pd.Index([1]), AS_OF, cap_amount=500.0)
    assert result.loc[1] == pytest.approx(10.0)


def test_return_rate_zero_activity_is_zero_not_nan():
    transactions = _txns([(1, "2026-04-01", 10.0, 1)])
    result = transforms.return_rate_prior_180d(transactions, pd.Index([1, 2]), AS_OF)
    assert result.loc[2] == 0.0
    assert result.isna().sum() == 0


def test_return_rate_single_returned_record_is_one():
    transactions = _txns([(1, "2026-04-01", 10.0, 1)])
    result = transforms.return_rate_prior_180d(transactions, pd.Index([1]), AS_OF)
    assert result.loc[1] == 1.0


def test_return_rate_mixed_records():
    transactions = _txns(
        [(1, "2026-04-01", 10.0, 1), (1, "2026-03-01", 10.0, 0), (1, "2026-02-01", 10.0, 0), (1, "2026-01-01", 10.0, 0)]
    )
    result = transforms.return_rate_prior_180d(transactions, pd.Index([1]), AS_OF)
    assert result.loc[1] == pytest.approx(0.25)


def _monthly(rows: list[tuple]) -> pd.DataFrame:
    """rows: (customer_id, 'YYYY-MM-01', txn_count)."""
    frame = pd.DataFrame(rows, columns=["customer_id", "txn_month", "txn_count"])
    frame["txn_month"] = pd.to_datetime(frame["txn_month"])
    frame["total_amount"] = 10.0
    frame["return_count"] = 0
    return frame


def test_active_months_counts_full_months_in_12_month_window():
    monthly = _monthly(
        [
            (1, "2025-05-01", 2),  # first month of the 12-month window: counted
            (1, "2026-04-01", 1),  # last full month before the label window: counted
        ]
    )
    result = transforms.active_months_prior_12m(monthly, pd.Index([1]), AS_OF)
    assert result.loc[1] == 2


def test_active_months_ignores_months_that_overlap_or_follow_the_label_window():
    monthly = _monthly(
        [
            (1, "2025-04-01", 1),  # one month before the window: NOT counted
            (1, "2026-05-01", 3),  # straddles the cutoff (May 1 vs May 2): NOT counted
            (1, "2026-06-01", 2),  # inside the label window: NOT counted
            (1, "2026-07-01", 2),  # stale and inside the label window: NOT counted
        ]
    )
    result = transforms.active_months_prior_12m(monthly, pd.Index([1]), AS_OF)
    assert result.loc[1] == 0


def test_active_months_zero_activity_gets_explicit_zero():
    monthly = _monthly([(1, "2026-01-01", 1)])
    result = transforms.active_months_prior_12m(monthly, pd.Index([1, 2]), AS_OF)
    assert result.loc[2] == 0
    assert result.isna().sum() == 0


def test_tenure_days_is_days_from_signup_to_as_of():
    customers = pd.DataFrame(
        {"customer_id": [1, 2], "signup_date": pd.to_datetime(["2026-07-01", "2024-08-01"])}
    )
    result = transforms.tenure_days(customers, pd.Index([1, 2]), AS_OF)
    assert result.loc[1] == 31
    assert result.loc[2] == (pd.Timestamp(AS_OF) - pd.Timestamp("2024-08-01")).days


def test_label_window_transactions_do_not_change_any_feature():
    """Leakage control: adding transactions inside the label window must not move any feature."""
    sources = build.load_sources()
    ids = build.population(sources, AS_OF, None)
    before = build.build_features(AS_OF)

    injected = pd.DataFrame(
        {
            "customer_id": ids,
            "txn_timestamp": pd.Timestamp("2026-06-15 12:00:00"),
            "category": "home",
            "channel": "web",
            "amount": 400.0,
            "is_returned": 1,
        }
    )
    tampered = dict(sources)
    tampered["transactions"] = pd.concat([sources["transactions"], injected], ignore_index=True)

    after = pd.DataFrame(
        {
            spec_name: build.compute_feature(spec_name, AS_OF, tampered, ids)
            for spec_name in before.columns
            if spec_name not in ("customer_id", "as_of_date")
        },
        index=ids,
    ).reset_index()
    for name in after.columns:
        if name == "customer_id":
            continue
        pd.testing.assert_series_equal(before[name], after[name], check_names=False)
