"""
The parity test that matters most for this pipeline: build features for the same customer
via the "training" path (historical as-of date, batch of all customers) and via the "scoring" path
(single customer, same as-of date), and assert the resulting feature values are identical.

The sample includes customers with a transaction between 250 and 500 in the spend window, because
that is exactly where a divergent scoring-only cap would show up. If this test fails, fix
features/build.py. Do not patch the test.
"""

import pandas as pd

from features import build
from features.transforms import SPEND_WINDOW_DAYS, history_cutoff

AS_OF = "2026-08-01"


def _sample_customer_ids(sources: dict) -> list[int]:
    """Deterministic sample: customers with a 250-500 transaction in the spend window, plus
    customers with zero activity and a few ordinary customers."""
    transactions = sources["transactions"]
    cutoff = history_cutoff(AS_OF)
    start = cutoff - pd.Timedelta(days=SPEND_WINDOW_DAYS)
    in_window = transactions[(transactions["txn_timestamp"] >= start) & (transactions["txn_timestamp"] < cutoff)]
    cap_sensitive = sorted(in_window.loc[in_window["amount"].between(250, 500, inclusive="neither"), "customer_id"].unique())[:15]
    zero_activity = sorted(set(sources["customers"]["customer_id"]) - set(transactions["customer_id"]))[:5]
    ordinary = sorted(set(sources["customers"]["customer_id"]))[:5]
    return sorted(set(cap_sensitive + zero_activity + ordinary))


def test_training_and_scoring_paths_agree_for_same_customer():
    sources = build.load_sources()
    training = build.build_features(AS_OF).set_index("customer_id")
    sample = _sample_customer_ids(sources)
    assert len(sample) >= 20, "parity sample should cover cap-sensitive and zero-activity customers"

    for customer_id in sample:
        scoring = build.build_features(AS_OF, customer_ids=[customer_id]).set_index("customer_id")
        pd.testing.assert_frame_equal(
            training.loc[[customer_id]],
            scoring,
            check_exact=True,
            obj=f"customer {customer_id}",
        )


def test_batch_scoring_matches_training_for_the_same_customers():
    sources = build.load_sources()
    training = build.build_features(AS_OF).set_index("customer_id")
    sample = _sample_customer_ids(sources)

    batch = build.build_features(AS_OF, customer_ids=sample).set_index("customer_id")
    pd.testing.assert_frame_equal(training.loc[sample], batch, check_exact=True)


def test_scoring_returns_exactly_the_requested_customers():
    scoring = build.build_features(AS_OF, customer_ids=[2, 697])
    assert scoring["customer_id"].tolist() == [2, 697]
    assert (scoring["as_of_date"] == pd.Timestamp(AS_OF)).all()
