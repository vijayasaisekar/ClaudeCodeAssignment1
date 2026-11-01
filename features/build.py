"""
The ONE shared feature-build entry point. Both `scripts/build_training_features.py`
(training path: a historical as-of date, batch of many customers) and
`scripts/score_customer.py` (scoring path: single customer_id, same as-of date) call
this same function — that is the entire train/score parity guarantee for this pipeline.

There is exactly one code path. The only difference between the two call sites is which
customer_ids are selected (see `population`). Every transform runs identically either way.
"""

import pandas as pd

from features import ingest, transforms
from features.schema import FEATURE_SCHEMA, FEATURES_BY_NAME

DEFAULT_SOURCE_PATHS = {
    "customers": "data/customers.csv",
    "transactions": "data/transactions.db",
    "monthly_agg": "data/transactions_monthly_agg.parquet",
}


def load_sources(source_paths: dict | None = None) -> dict[str, pd.DataFrame]:
    """Load all three raw sources through features/ingest.py. Missing keys use the defaults."""
    paths = {**DEFAULT_SOURCE_PATHS, **(source_paths or {})}
    return {
        "customers": ingest.load_customers(paths["customers"]),
        "transactions": ingest.load_transactions(paths["transactions"]),
        "monthly_agg": ingest.load_monthly_agg(paths["monthly_agg"]),
    }


def population(sources: dict, as_of: str, customer_ids: list[int] | None) -> pd.Index:
    """Customers the build covers, sorted by customer_id.

    customer_ids=None (training): every customer who has signed up by as_of.
    customer_ids given (scoring): exactly those customers. Unknown ids and ids that had not
    signed up by as_of raise an error rather than returning an empty result.
    """
    customers = sources["customers"]
    eligible = customers.loc[customers["signup_date"] <= pd.Timestamp(as_of), "customer_id"]
    if customer_ids is None:
        return pd.Index(sorted(eligible), name="customer_id")

    requested = pd.Index(sorted(set(customer_ids)), name="customer_id")
    unknown = requested.difference(customers["customer_id"])
    if len(unknown) > 0:
        raise KeyError(f"Unknown customer_id(s): {list(unknown)}")
    not_yet_signed_up = requested.difference(eligible)
    if len(not_yet_signed_up) > 0:
        raise ValueError(f"customer_id(s) not signed up as of {as_of}: {list(not_yet_signed_up)}")
    return requested


def compute_feature(
    name: str,
    as_of: str,
    sources: dict,
    customer_ids: pd.Index,
    params: dict | None = None,
) -> pd.Series:
    """Compute one feature for `customer_ids`. `params` defaults to the latest registered version."""
    spec = FEATURES_BY_NAME[name]
    if params is None:
        params = spec.latest.params

    if name == "txn_count_prior":
        return transforms.txn_count_prior(
            sources["transactions"], customer_ids, as_of, **params
        )
    if name == "spend_prior_winsorized":
        return transforms.spend_prior_winsorized(
            sources["transactions"], customer_ids, as_of, **params
        )
    if name == "return_rate_prior_180d":
        return transforms.return_rate_prior_180d(sources["transactions"], customer_ids, as_of)
    if name == "active_months_prior_12m":
        return transforms.active_months_prior_12m(sources["monthly_agg"], customer_ids, as_of)
    if name == "tenure_days":
        return transforms.tenure_days(sources["customers"], customer_ids, as_of)
    raise NotImplementedError(f"No transform registered for feature {name}")


def build_features(
    as_of: str,
    source_paths: dict | None = None,
    customer_ids: list[int] | None = None,
) -> pd.DataFrame:
    """Build the full feature set as of `as_of`.

    Training path: `customer_ids=None` gives one row per customer signed up by `as_of`.
    Scoring path: `customer_ids=[...]` gives one row per requested customer.
    Returns `customer_id`, `as_of_date`, then one column per feature in FEATURE_SCHEMA.
    """
    sources = load_sources(source_paths)
    ids = population(sources, as_of, customer_ids)
    columns = {spec.name: compute_feature(spec.name, as_of, sources, ids) for spec in FEATURE_SCHEMA}

    features = pd.DataFrame(columns, index=ids).reset_index()
    features.insert(1, "as_of_date", pd.Timestamp(as_of))
    return features
