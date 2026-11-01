"""
One pure function per candidate feature named in `feature_spec.md`.

Each function:
- Is independent of any I/O (takes already-loaded DataFrames in, returns a Series out).
- Takes `as_of` as an argument and never reads the current date.
- Reads only the one source feature_spec.md names for that feature.
- Applies its zero-activity default explicitly through `reindex(..., fill_value=...)`,
  not by filling NaN after the fact.

Every feature only uses history strictly before `history_cutoff(as_of)`, which is the start of the
label window. Using anything later would leak the churn label (see feature_spec.md).
"""

import pandas as pd

# The churn label is "no transaction in [as_of - 91 days, as_of)" (data_dictionary.md, verified
# 1500/1500). Features must never read that window.
LABEL_WINDOW_DAYS = 91
SPEND_WINDOW_DAYS = 180
RETURN_WINDOW_DAYS = 180
ACTIVE_MONTHS_LOOKBACK = 12


def history_cutoff(as_of: str) -> pd.Timestamp:
    """Start of the label window. All features use transactions strictly before this instant."""
    return pd.Timestamp(as_of) - pd.Timedelta(days=LABEL_WINDOW_DAYS)


def _window_transactions(transactions: pd.DataFrame, as_of: str, window_days: int) -> pd.DataFrame:
    """Transactions in [history_cutoff - window_days, history_cutoff)."""
    cutoff = history_cutoff(as_of)
    start = cutoff - pd.Timedelta(days=window_days)
    ts = transactions["txn_timestamp"]
    return transactions[(ts >= start) & (ts < cutoff)]


def txn_count_prior(
    transactions: pd.DataFrame, customer_ids: pd.Index, as_of: str, window_days: int
) -> pd.Series:
    """Number of transactions in the `window_days` history before the label window. Default 0."""
    rows = _window_transactions(transactions, as_of, window_days)
    counts = rows.groupby("customer_id").size()
    return counts.reindex(customer_ids, fill_value=0).astype("int64").rename("txn_count_prior")


def spend_prior_winsorized(
    transactions: pd.DataFrame, customer_ids: pd.Index, as_of: str, cap_amount: float
) -> pd.Series:
    """Sum of per-transaction amounts, each capped at `cap_amount`, over the 180-day history
    before the label window. Default 0.0."""
    rows = _window_transactions(transactions, as_of, SPEND_WINDOW_DAYS)
    capped = rows["amount"].clip(upper=cap_amount)
    totals = capped.groupby(rows["customer_id"]).sum()
    return totals.reindex(customer_ids, fill_value=0.0).astype("float64").rename(
        "spend_prior_winsorized"
    )


def return_rate_prior_180d(
    transactions: pd.DataFrame, customer_ids: pd.Index, as_of: str
) -> pd.Series:
    """Share of returned transactions over the 180-day history before the label window.

    Default 0.0 for a customer with no transactions in the window. That means "no observed
    returns", not a measured rate. Zero activity is identified by txn_count_prior and
    active_months_prior_12m.
    """
    rows = _window_transactions(transactions, as_of, RETURN_WINDOW_DAYS)
    grouped = (
        rows.groupby("customer_id")["is_returned"].agg(["sum", "count"]).reindex(
            customer_ids, fill_value=0
        )
    )
    rate = (grouped["sum"] / grouped["count"]).where(grouped["count"] > 0, 0.0)
    return rate.astype("float64").rename("return_rate_prior_180d")


def active_months_prior_12m(
    monthly_agg: pd.DataFrame, customer_ids: pd.Index, as_of: str
) -> pd.Series:
    """Number of calendar months with activity in the 12 full months before the label window.

    Uses the monthly parquet. Every month used ends before history_cutoff, which avoids the
    partial/straddling months and the stale 2026-07 aggregate. Default 0.
    """
    cutoff = history_cutoff(as_of)
    last_full_month = cutoff.to_period("M") - 1
    if (last_full_month + 1).to_timestamp() > cutoff:
        raise ValueError(f"Month {last_full_month} does not end before history cutoff {cutoff}")
    first_month = last_full_month - (ACTIVE_MONTHS_LOOKBACK - 1)

    in_window = (monthly_agg["txn_month"] >= first_month.to_timestamp()) & (
        monthly_agg["txn_month"] <= last_full_month.to_timestamp()
    )
    active = monthly_agg[in_window & (monthly_agg["txn_count"] > 0)]
    counts = active.groupby("customer_id").size()
    return counts.reindex(customer_ids, fill_value=0).astype("int64").rename(
        "active_months_prior_12m"
    )


def tenure_days(customers: pd.DataFrame, customer_ids: pd.Index, as_of: str) -> pd.Series:
    """Days from signup to as_of. Callers pass only customers signed up by as_of."""
    signup = customers.set_index("customer_id")["signup_date"].reindex(customer_ids)
    return (pd.Timestamp(as_of) - signup).dt.days.astype("int64").rename("tenure_days")
