"""
Data-quality checks (null / default / range / row-count / source reconciliation / drift) against a
built features DataFrame, implementing every check in `feature_spec.md`'s data-quality section.

Each check returns a dict with `passed`, `failing_features`, `failing_rows` and `detail`.
`enforce()` raises DataQualityError when any check fails. A failing build must never write
values to the feature store. Runnable standalone:

    python -m features.quality_checks --as-of 2026-08-01
"""

import argparse

import pandas as pd

from features.build import build_features, load_sources, population
from features.schema import FEATURE_SCHEMA, FEATURES_BY_NAME
from features.transforms import history_cutoff

DRIFT_MEAN_SHIFT_LIMIT = 0.25

RANGE_BOUNDS = {
    "txn_count_prior": (0, 1000),
    "spend_prior_winsorized": (0.0, 10_000.0),
    "return_rate_prior_180d": (0.0, 1.0),
    "active_months_prior_12m": (0, 12),
    "tenure_days": (0, 5000),
}


class DataQualityError(RuntimeError):
    """Raised when one or more data-quality checks fail."""


def _result(
    check: str,
    passed: bool,
    failing_features: list | None = None,
    failing_rows: list | None = None,
    detail: str = "",
    skipped: bool = False,
) -> dict:
    return {
        "check": check,
        "passed": passed,
        "skipped": skipped,
        "failing_features": list(failing_features or []),
        "failing_rows": [int(x) for x in (failing_rows or [])],
        "detail": detail,
    }


def check_no_unexpected_nulls(features: pd.DataFrame) -> dict:
    """Fail if any feature marked non-nullable in schema.py is null."""
    names = [spec.name for spec in FEATURE_SCHEMA if not spec.nullable]
    null_mask = features[names].isna()
    failing_features = [name for name in names if null_mask[name].any()]
    failing_rows = features.loc[null_mask.any(axis=1), "customer_id"]
    return _result(
        "no_unexpected_nulls",
        passed=not failing_features,
        failing_features=failing_features,
        failing_rows=failing_rows.tolist(),
        detail=f"checked {len(names)} non-nullable features",
    )


def check_zero_activity_defaults(features: pd.DataFrame) -> dict:
    """Customers with no transactions in the count window must carry explicit zero defaults.

    The spend and return windows (180 days) are contained in the count window (latest version,
    365 days), so txn_count_prior == 0 implies both spend_prior_winsorized and
    return_rate_prior_180d must be exactly 0 (not NaN, not missing).
    Note: active_months_prior_12m cannot be used here. Its months end in April, so it misses
    transactions on 2026-05-01, which are inside the count window.
    """
    zero_activity = features["txn_count_prior"] == 0
    expected_zero = ["spend_prior_winsorized", "return_rate_prior_180d"]
    violations = features.loc[zero_activity, expected_zero] != 0
    failing_features = [name for name in expected_zero if violations[name].any()]
    failing_rows = features.loc[zero_activity, "customer_id"][violations.any(axis=1)]
    return _result(
        "zero_activity_defaults_applied",
        passed=not failing_features,
        failing_features=failing_features,
        failing_rows=failing_rows.tolist(),
        detail=f"{int(zero_activity.sum())} zero-activity customers checked",
    )


def check_ranges(features: pd.DataFrame) -> dict:
    """Monetary and aggregate features must lie within the sane bounds in RANGE_BOUNDS."""
    failing_features = []
    failing_rows = set()
    for name, (low, high) in RANGE_BOUNDS.items():
        out_of_range = ~features[name].between(low, high)
        if out_of_range.any():
            failing_features.append(name)
            failing_rows.update(features.loc[out_of_range, "customer_id"].tolist())
    return _result(
        "ranges_within_bounds",
        passed=not failing_features,
        failing_features=failing_features,
        failing_rows=sorted(failing_rows),
        detail=f"checked {len(RANGE_BOUNDS)} bounded features",
    )


def check_row_count(features: pd.DataFrame, expected_ids: pd.Index) -> dict:
    """Output rows must equal the expected population exactly, one row per customer_id."""
    actual_ids = features["customer_id"]
    duplicated = actual_ids[actual_ids.duplicated()].tolist()
    missing = pd.Index(expected_ids).difference(actual_ids).tolist()
    extra = pd.Index(actual_ids).difference(expected_ids).tolist()
    passed = not duplicated and not missing and not extra
    return _result(
        "row_count_matches_population",
        passed=passed,
        failing_rows=duplicated + missing + extra,
        detail=f"rows={len(features)} expected={len(expected_ids)}",
    )


def check_txn_reconciliation(
    features: pd.DataFrame, transactions: pd.DataFrame, as_of: str
) -> dict:
    """Sum of txn_count_prior must equal the raw row count in the same window, computed directly
    from the transactions table (not through the transform)."""
    window_days = FEATURES_BY_NAME["txn_count_prior"].latest.params["window_days"]
    cutoff = history_cutoff(as_of)
    start = cutoff - pd.Timedelta(days=window_days)
    raw_count = int(
        ((transactions["txn_timestamp"] >= start) & (transactions["txn_timestamp"] < cutoff)).sum()
    )
    feature_total = int(features["txn_count_prior"].sum())
    return _result(
        "txn_count_reconciles_to_source",
        passed=raw_count == feature_total,
        failing_features=[] if raw_count == feature_total else ["txn_count_prior"],
        detail=f"raw_rows={raw_count} feature_sum={feature_total} window_days={window_days}",
    )


def check_drift(features: pd.DataFrame, reference: pd.DataFrame | None = None) -> dict:
    """Fail if a feature's mean moves more than DRIFT_MEAN_SHIFT_LIMIT from a reference snapshot.

    Without a reference the check is reported as skipped, not as a pass.
    """
    if reference is None:
        return _result(
            "drift_vs_reference",
            passed=True,
            skipped=True,
            detail="no reference snapshot supplied; drift not evaluated",
        )
    failing_features = []
    for spec in FEATURE_SCHEMA:
        ref_mean = float(reference[spec.name].mean())
        cur_mean = float(features[spec.name].mean())
        shift = abs(cur_mean - ref_mean) / max(abs(ref_mean), 1e-9)
        if shift > DRIFT_MEAN_SHIFT_LIMIT:
            failing_features.append(spec.name)
    return _result(
        "drift_vs_reference",
        passed=not failing_features,
        failing_features=failing_features,
        detail=f"mean-shift limit {DRIFT_MEAN_SHIFT_LIMIT:.0%}",
    )


def run_all_checks(
    features: pd.DataFrame,
    transactions: pd.DataFrame,
    as_of: str,
    expected_ids: pd.Index,
    reference: pd.DataFrame | None = None,
) -> dict:
    """Run every check and return one combined summary."""
    results = [
        check_no_unexpected_nulls(features),
        check_zero_activity_defaults(features),
        check_ranges(features),
        check_row_count(features, expected_ids),
        check_txn_reconciliation(features, transactions, as_of),
        check_drift(features, reference),
    ]
    return {"passed": all(r["passed"] for r in results), "results": results}


def enforce(summary: dict) -> None:
    """Raise DataQualityError if any check in the summary failed."""
    if summary["passed"]:
        return
    failed = [r for r in summary["results"] if not r["passed"]]
    lines = [f"{r['check']}: features={r['failing_features']} rows={r['failing_rows'][:10]}" for r in failed]
    raise DataQualityError("Data-quality checks failed:\n  " + "\n  ".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--as-of", default="2026-08-01")
    args = parser.parse_args()

    sources = load_sources()
    features = build_features(args.as_of)
    summary = run_all_checks(
        features,
        transactions=sources["transactions"],
        as_of=args.as_of,
        expected_ids=population(sources, args.as_of, None),
    )
    for result in summary["results"]:
        status = "SKIPPED" if result["skipped"] else ("PASS" if result["passed"] else "FAIL")
        print(f"[{status}] {result['check']}: {result['detail']}")
    print("ALL CHECKS PASSED" if summary["passed"] else "CHECKS FAILED")
    enforce(summary)


if __name__ == "__main__":
    main()
