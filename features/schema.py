"""
Versioned output feature schema: the authoritative list of every feature this pipeline
produces, with dtype, nullability, source(s), feature-set version, and every registered version
with its parameters and business rationale.

Mirrors feature_spec.md. FEATURE_LINEAGE.md is generated from this list plus the feature store
registry, and feature_store registration reads the versions from here.
"""

from dataclasses import dataclass, field

FEATURE_SET_VERSION = "1.0"


@dataclass(frozen=True)
class FeatureVersion:
    version: int
    params: dict
    business_rationale: str


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    dtype: str
    nullable: bool
    source: str
    feature_set_version: str
    description: str
    transform_summary: str
    rationale: str
    zero_activity_default: str
    source_justification: str
    versions: tuple[FeatureVersion, ...] = field(default=())

    @property
    def latest(self) -> FeatureVersion:
        """The highest version. The training/scoring build uses its parameters by default."""
        return self.versions[-1]

    @property
    def is_versioned(self) -> bool:
        return len(self.versions) > 1


FEATURE_SCHEMA: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="txn_count_prior",
        dtype="int64",
        nullable=False,
        source="data/transactions.db:transactions.customer_id,txn_timestamp",
        feature_set_version=FEATURE_SET_VERSION,
        description="Number of transactions in the window before the label window.",
        transform_summary=(
            "count of rows with history_cutoff - window_days <= txn_timestamp < history_cutoff; "
            "history_cutoff = as_of - 91 days; zero-activity customers get 0"
        ),
        rationale=(
            "Frequency drop before the label window separates a fading customer from one who "
            "has always bought rarely."
        ),
        zero_activity_default="0",
        source_justification=(
            "Row table chosen over the monthly parquet. The window boundary (as_of - 91 days - N) "
            "falls mid-month, which the monthly grain cannot express exactly."
        ),
        versions=(
            FeatureVersion(
                version=1,
                params={"window_days": 90},
                business_rationale=(
                    "90 days immediately before the label window, the same length as the label, "
                    "so the first version gives a direct comparison."
                ),
            ),
            FeatureVersion(
                version=2,
                params={"window_days": 180},
                business_rationale=(
                    "Widened to 180 days because many customers buy about once a month, so a "
                    "90-day count is often zero or one. Widening reduces that sparsity noise."
                ),
            ),
            FeatureVersion(
                version=3,
                params={"window_days": 365},
                business_rationale=(
                    "Widened to a full year so that seasonal buyers are not counted as fading "
                    "when they have not reached their usual season."
                ),
            ),
        ),
    ),
    FeatureSpec(
        name="spend_prior_winsorized",
        dtype="float64",
        nullable=False,
        source="data/transactions.db:transactions.amount,txn_timestamp",
        feature_set_version=FEATURE_SET_VERSION,
        description="Capped spend in the 180-day window before the label window.",
        transform_summary=(
            "sum of min(amount, cap_amount) over rows with history_cutoff - 180 days <= "
            "txn_timestamp < history_cutoff; zero-activity customers get 0.0"
        ),
        rationale=(
            "Capped spend level relative to history shows disengagement without letting one "
            "large purchase hide it."
        ),
        zero_activity_default="0.0",
        source_justification=(
            "Row table chosen. Capping needs individual transaction amounts, and the monthly "
            "aggregate only has monthly totals."
        ),
        versions=(
            FeatureVersion(
                version=1,
                params={"cap_amount": 250.0},
                business_rationale=(
                    "Cap at about the 99th percentile of transaction amounts (255.66). "
                    "Removes the rare very large purchases."
                ),
            ),
            FeatureVersion(
                version=2,
                params={"cap_amount": 500.0},
                business_rationale=(
                    "Cap at about the 99.9th percentile (518.34). Keeps genuine large purchases, "
                    "over-represented in electronics, that version 1 truncated."
                ),
            ),
        ),
    ),
    FeatureSpec(
        name="return_rate_prior_180d",
        dtype="float64",
        nullable=False,
        source="data/transactions.db:transactions.is_returned,txn_timestamp",
        feature_set_version=FEATURE_SET_VERSION,
        description="Share of returned transactions in the 180-day window before the label window.",
        transform_summary=(
            "sum(is_returned) / count(*) over the 180-day window before history_cutoff; "
            "0.0 when the customer has no transactions in the window"
        ),
        rationale=(
            "A rising share of returns before the label window signals unmet expectations "
            "that precede a lapse, distinct from low spend."
        ),
        zero_activity_default="0.0 (no observed returns; not a measured rate)",
        source_justification=(
            "Row table chosen. The 180-day window is not month-aligned, and the monthly "
            "return_count cannot give the exact share."
        ),
        versions=(
            FeatureVersion(
                version=1,
                params={},
                business_rationale="Initial definition. Not versioned.",
            ),
        ),
    ),
    FeatureSpec(
        name="active_months_prior_12m",
        dtype="int64",
        nullable=False,
        source="data/transactions_monthly_agg.parquet:txn_month,txn_count",
        feature_set_version=FEATURE_SET_VERSION,
        description="Calendar months with activity in the 12 full months before the label window.",
        transform_summary=(
            "count of months in [2025-05, 2026-04] with txn_count > 0; every month ends before "
            "history_cutoff; zero-activity customers get 0"
        ),
        rationale=(
            "Engagement breadth across months separates a steady buyer from one with a single "
            "burst of purchases."
        ),
        zero_activity_default="0",
        source_justification=(
            "Monthly parquet chosen on purpose. It counts whole calendar months, which is its "
            "native grain. Verified identical to the row table for these months. The stale "
            "2026-07 month and the straddling 2026-05 month are excluded."
        ),
        versions=(
            FeatureVersion(
                version=1,
                params={},
                business_rationale="Initial definition. Not versioned.",
            ),
        ),
    ),
    FeatureSpec(
        name="tenure_days",
        dtype="int64",
        nullable=False,
        source="data/customers.csv:signup_date",
        feature_set_version=FEATURE_SET_VERSION,
        description="Days from signup to the as-of date.",
        transform_summary="(as_of - signup_date) in days; population is signup_date <= as_of",
        rationale=(
            "Tenure is the baseline for judging whether low activity is normal for a customer "
            "of this age."
        ),
        zero_activity_default="not applicable (every customer has a signup_date)",
        source_justification="Only one source carries signup_date (customers.csv).",
        versions=(
            FeatureVersion(
                version=1,
                params={},
                business_rationale="Initial definition. Not versioned.",
            ),
        ),
    ),
)

FEATURES_BY_NAME: dict[str, FeatureSpec] = {spec.name: spec for spec in FEATURE_SCHEMA}
